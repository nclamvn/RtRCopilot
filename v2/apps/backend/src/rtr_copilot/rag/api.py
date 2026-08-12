import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text

from rtr_copilot.auth.api import current_subject
from rtr_copilot.auth.models import Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.service import (
    decode_signed_cursor,
    encode_signed_cursor,
)
from rtr_copilot.limits.breaker import ProviderUnavailable
from rtr_copilot.limits.budget import BudgetExhausted
from rtr_copilot.limits.errors import limit_response
from rtr_copilot.observability.metrics import ASK_STREAM_MILESTONE_DURATION
from rtr_copilot.rag.answering import AnswerService, GroundingError
from rtr_copilot.rag.models import (
    AskProgressEvent,
    AskRequest,
    AskResponse,
    Citation,
    ConversationListPage,
    ConversationMessage,
    ConversationResponse,
    ConversationSummary,
    KnowledgeErrorEnvelope,
    SearchRequest,
    SearchResponse,
)
from rtr_copilot.rag.retrieval import RetrievalError, RetrievalService
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.governance import GovernanceError

router = APIRouter(
    prefix="/api/v1",
    tags=["knowledge"],
    responses={
        status: {"model": KnowledgeErrorEnvelope}
        for status in (400, 401, 403, 404, 409, 413, 422, 503)
    },
)

logger = logging.getLogger("rtr_copilot.rag.api")


async def rag_subject(request: Request) -> Subject | None:
    settings = get_settings()
    return await current_subject(
        request,
        request.cookies.get(settings.session_cookie_name),
    )


def answer_service() -> AnswerService:
    """Runtime answer service seam; tests inject only explicit test adapters."""
    return AnswerService()


def _error(request: Request, status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": "Knowledge request could not be completed",
            },
            "request_id": str(request.state.request_id),
        },
    )


def _sse(event: str, payload: dict[str, Any]) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def _stream_error(code: str, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": "Knowledge request could not be completed",
        },
        "request_id": request_id,
    }


async def _ask_stream(
    body: AskRequest,
    request: Request,
    subject: Subject,
    service: AnswerService,
    request_id: str,
) -> AsyncIterator[str]:
    """Stream real Ask checkpoints; never prompts, snippets or chain-of-thought."""
    queue: asyncio.Queue[AskProgressEvent] = asyncio.Queue(maxsize=32)
    started = time.monotonic()
    sequence = 0
    stage_started_ms: dict[str, int] = {}
    milestone_by_stage = {
        "understanding": "intent_ready",
        "retrieving": "sources_ready",
        "verifying": "evidence_ready",
        "synthesizing": "draft_ready",
        "grounding": "answer_ready",
    }

    async def publish(event: AskProgressEvent) -> None:
        await queue.put(event)

    task = asyncio.create_task(service.ask(
        subject,
        body.question,
        filters=body.filters,
        require_verified=body.require_verified,
        conversation_id=body.conversation_id,
        request_id=request_id,
        progress=publish,
    ))
    try:
        while not task.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                sequence += 1
                if event.status == "started":
                    stage_started_ms[event.stage] = event.elapsed_ms
                stage_elapsed_ms = None
                if event.status == "completed":
                    stage_elapsed_ms = max(
                        0,
                        event.elapsed_ms
                        - stage_started_ms.get(event.stage, event.elapsed_ms),
                    )
                milestone = (
                    milestone_by_stage[event.stage]
                    if event.status == "completed"
                    # A zero-result retrieval is not useful source feedback.
                    and (event.stage != "retrieving" or event.source_count > 0)
                    else None
                )
                streamed = event.model_copy(update={
                    "sequence": sequence,
                    "stage_elapsed_ms": stage_elapsed_ms,
                    "milestone": milestone,
                })
                if milestone is not None:
                    ASK_STREAM_MILESTONE_DURATION.labels(milestone).observe(
                        event.elapsed_ms / 1000,
                    )
                yield _sse("progress", streamed.model_dump(mode="json"))
            except TimeoutError:
                if await request.is_disconnected():
                    task.cancel()
                    return
                yield _sse("heartbeat", {
                    "elapsed_ms": max(
                        0,
                        round((time.monotonic() - started) * 1000),
                    ),
                    "last_sequence": sequence,
                })
        result = await task
        ASK_STREAM_MILESTONE_DURATION.labels("result_ready").observe(
            max(0.0, time.monotonic() - started),
        )
        yield _sse("result", {
            "response": result.model_dump(mode="json"),
        })
    except RetrievalError as error:
        yield _sse("error", _stream_error(error.code, request_id))
    except BudgetExhausted:
        yield _sse("error", _stream_error("budget_exhausted", request_id))
    except ProviderUnavailable:
        yield _sse("error", _stream_error("provider_unavailable", request_id))
    except GroundingError:
        yield _sse("error", _stream_error("conversation_not_found", request_id))
    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception:
        logger.exception("ask_stream_failed", extra={"request_id": request_id})
        yield _sse("error", _stream_error("ask_service_unavailable", request_id))
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    request: Request,
    subject: Annotated[Subject | None, Depends(rag_subject)],
) -> SearchResponse | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    request_id = str(request.state.request_id)
    service = RetrievalService()
    try:
        hits = await service.search(
            subject,
            body.query,
            filters=body.filters,
            request_id=request_id,
            top_k=body.top_k,
        )
    except RetrievalError as error:
        return _error(request, 413 if "budget" in error.code else 400, error.code)
    async with UnitOfWork().transaction() as session:
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=uuid.UUID(subject.user_id),
            action="rag.search",
            result="success",
            reason_code="authorized_results",
            request_id=request_id,
            resource_type="search",
            details={
                "returned_count": len(hits),
                "query_fingerprint": __import__("hashlib").sha256(
                    body.query.casefold().encode(),
                ).hexdigest(),
                "content_queries": service.trace.content_queries,
                "dlp_rule_ids": sorted(set(service.trace.dlp_rule_ids)),
            },
        )
    return SearchResponse(results=hits, request_id=request_id)


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    request: Request,
    subject: Annotated[Subject | None, Depends(rag_subject)],
    service: Annotated[AnswerService, Depends(answer_service)],
) -> AskResponse | JSONResponse | StreamingResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    request_id = str(request.state.request_id)
    if "text/event-stream" in request.headers.get("accept", "").casefold():
        return StreamingResponse(
            _ask_stream(body, request, subject, service, request_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, no-transform",
                "X-Accel-Buffering": "no",
            },
        )
    try:
        return await service.ask(
            subject,
            body.question,
            filters=body.filters,
            require_verified=body.require_verified,
            conversation_id=body.conversation_id,
            request_id=request_id,
        )
    except RetrievalError as error:
        return _error(request, 413 if "budget" in error.code else 400, error.code)
    except BudgetExhausted as breach:
        return limit_response(
            request_id, "budget_exhausted", retry_after=breach.retry_after,
        )
    except ProviderUnavailable as outage:
        return limit_response(
            request_id, "provider_unavailable", retry_after=outage.retry_after,
        )
    except GroundingError:
        return _error(request, 404, "conversation_not_found")


def _citation(row: dict[str, Any]) -> Citation:
    return Citation(
        zone_label=row.get("zone_label", "sot"),
        marker=row["marker"],
        chunk_id=uuid.UUID(str(row.get("chunk_id") or row.get("file_chunk_id"))),
        record_key=row["record_key"],
        record_version_id=row["record_version_id"],
        document_version_id=row.get("document_version_id"),
        evidence_key=row["evidence_key"],
        record_checksum=str(row["record_checksum"]),
        evidence_checksum=(
            str(row["evidence_checksum"]) if row["evidence_checksum"] else None
        ),
        source_key=row["source_key"],
        source_revision=row["source_revision"],
        provenance_level=row["provenance_level"],
        verification_state=row["verification_state"],
        freshness_state=row["freshness_state"],
        source_label=row["source_label"],
        locator=dict(row["locator"]),
        redacted=row["redacted"],
    )


CONVERSATION_LIST_SQL = """
    SELECT c.conversation_id, c.created_at AS started_at,
      COALESCE(MAX(m.created_at), c.created_at) AS last_activity_at,
      (ARRAY_AGG(m.content_sha256 ORDER BY m.created_at, m.message_id)
         FILTER (WHERE m.role = 'user'))[1] AS first_question_digest
    FROM conversations c
    LEFT JOIN messages m ON m.conversation_id = c.conversation_id
    WHERE c.owner_subject_id = :owner AND c.lifecycle = 'active'
    GROUP BY c.conversation_id, c.created_at
    HAVING CAST(:cursor_at AS timestamptz) IS NULL
      OR (COALESCE(MAX(m.created_at), c.created_at), c.conversation_id)
         < (CAST(:cursor_at AS timestamptz), CAST(:cursor_id AS uuid))
    ORDER BY last_activity_at DESC, c.conversation_id DESC
    LIMIT :limit
"""


@router.get("/conversations", response_model=ConversationListPage)
async def conversations(
    request: Request,
    subject: Annotated[Subject | None, Depends(rag_subject)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> ConversationListPage | JSONResponse:
    """The caller's own conversations, newest activity first (TIP-011).

    Metadata only, exactly as TIP-007 already stores it: ids, timestamps and
    the first user message's stored content digest — never message content.
    Ownership is enforced in the query itself, so other subjects' history is
    structurally invisible (no counts, no cursors, no timing signal).
    """
    if subject is None:
        return _error(request, 401, "authentication_required")
    request_id = str(request.state.request_id)
    settings = get_settings()
    secret = settings.sot_signing_secret.get_secret_value()
    try:
        boundary = (
            decode_signed_cursor("conversations", cursor, secret)
            if cursor
            else None
        )
    except GovernanceError as failure:
        return _error(request, 400, failure.code)
    async with UnitOfWork().factory() as session:
        rows = (await session.execute(text(CONVERSATION_LIST_SQL), {
            "owner": uuid.UUID(subject.user_id),
            "cursor_at": boundary[0] if boundary else None,
            "cursor_id": boundary[1] if boundary else None,
            "limit": limit + 1,
        })).mappings().all()
    items = [
        ConversationSummary(
            conversation_id=row["conversation_id"],
            started_at=row["started_at"],
            last_activity_at=row["last_activity_at"],
            first_question_digest=(
                str(row["first_question_digest"])
                if row["first_question_digest"] is not None
                else None
            ),
        )
        for row in rows[:limit]
    ]
    next_cursor = (
        encode_signed_cursor(
            "conversations",
            items[-1].last_activity_at,
            items[-1].conversation_id,
            secret,
        )
        if len(rows) > limit
        else None
    )
    async with UnitOfWork().transaction() as session:
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=uuid.UUID(subject.user_id),
            action="rag.conversation.list",
            result="success",
            reason_code="owner_metadata_disclosed",
            request_id=request_id,
            resource_type="conversation",
            details={"returned_count": len(items)},
        )
    return ConversationListPage(
        items=items,
        next_cursor=next_cursor,
        request_id=request_id,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def conversation(
    conversation_id: uuid.UUID,
    request: Request,
    subject: Annotated[Subject | None, Depends(rag_subject)],
) -> ConversationResponse | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    request_id = str(request.state.request_id)
    async with UnitOfWork().factory() as session:
        owner = await session.scalar(text("""
            SELECT owner_subject_id FROM conversations
            WHERE conversation_id=:conversation_id AND lifecycle='active'
        """), {"conversation_id": conversation_id})
        if owner != uuid.UUID(subject.user_id):
            return _error(request, 404, "conversation_not_found")
        headers = (await session.execute(text("""
            SELECT message_id,role,answer_state,created_at
            FROM messages WHERE conversation_id=:conversation_id
            ORDER BY created_at,message_id LIMIT 100
        """), {"conversation_id": conversation_id})).mappings().all()
        citation_metadata = (await session.execute(text("""
            SELECT ar.answer_message_id,ac.citation_id,c.chunk_id,c.chunk_key,
              c.record_id,c.generation_id,c.source_key,c.source_revision,
              c.classification,c.owner_subject_id,c.department_id,c.project_id,
              c.provenance_level,c.verification_state,c.freshness_state,
              (
                c.lifecycle='active' AND g.lifecycle='active'
                AND ag.generation_id=c.generation_id
                AND r.current_version_id=c.record_version_id
                AND rv.lifecycle='active'
              ) AS current_active,
              has_effective_acl_deny(
                c.record_id,CAST(:principal AS uuid),CAST('view' AS text)
              ) AS explicit_deny
            FROM answer_runs ar JOIN answer_citations ac
              ON ac.answer_run_id=ar.answer_run_id
            JOIN chunks c ON c.chunk_id=ac.chunk_id
            JOIN search_generations g ON g.generation_id=c.generation_id
            LEFT JOIN active_search_generations ag
              ON ag.generation_id=c.generation_id
            JOIN records r ON r.record_id=c.record_id
            JOIN record_versions rv ON rv.version_id=c.record_version_id
            WHERE ar.conversation_id=:conversation_id
              AND ac.zone_label='sot'
            ORDER BY ar.created_at,ac.marker
        """), {
            "conversation_id": conversation_id,
            "principal": uuid.UUID(subject.user_id),
        })).mappings().all()
        active_metadata = [
            dict(row) for row in citation_metadata if row["current_active"]
        ]
        allowed_chunks = set(RetrievalService()._allowed(
            subject,
            active_metadata,
            request_id,
        ))
        blocked_messages = {
            row["answer_message_id"]
            for row in citation_metadata
            if not row["current_active"] or row["chunk_id"] not in allowed_chunks
        }
        file_metadata = (await session.execute(text("""
            SELECT ar.answer_message_id,ac.citation_id,ac.file_chunk_id chunk_id,
              ac.document_version_id,
              (fc.lifecycle='active' AND rd.status='ready'
                AND rr.lifecycle_state='active') AS current_active
            FROM answer_runs ar JOIN answer_citations ac
              ON ac.answer_run_id=ar.answer_run_id
            JOIN file_chunks fc ON fc.file_chunk_id=ac.file_chunk_id
            JOIN renditions rd ON rd.rendition_id=fc.rendition_id
            JOIN resources rr ON rr.resource_id=rd.rendition_id
            WHERE ar.conversation_id=:conversation_id
              AND ac.zone_label='private'
            ORDER BY ar.created_at,ac.marker
        """), {"conversation_id": conversation_id})).mappings().all()
        retrieval = RetrievalService()
        authorized_versions: dict[uuid.UUID, bool] = {}
        for row in file_metadata:
            version_id = row["document_version_id"]
            if version_id not in authorized_versions:
                authorized_versions[version_id] = await retrieval._file_authorized(
                    session, subject, version_id, request_id,
                ) is not None
            if not row["current_active"] or not authorized_versions[version_id]:
                blocked_messages.add(row["answer_message_id"])
        readable_message_ids = [
            row["message_id"]
            for row in headers
            if row["role"] == "user"
            or row["answer_state"] != "grounded"
            or row["message_id"] not in blocked_messages
        ]
        content_rows = (await session.execute(text("""
            SELECT message_id,sanitized_content FROM messages
            WHERE message_id=ANY(CAST(:message_ids AS uuid[]))
        """), {"message_ids": readable_message_ids})).mappings().all()
        contents: dict[uuid.UUID, str] = {
            row["message_id"]: row["sanitized_content"]
            for row in content_rows
        }
        allowed_citation_ids = [
            row["citation_id"]
            for row in citation_metadata
            if (
                row["answer_message_id"] not in blocked_messages
                and row["chunk_id"] in allowed_chunks
            )
        ]
        allowed_citation_ids.extend(
            row["citation_id"] for row in file_metadata
            if (
                row["answer_message_id"] not in blocked_messages
                and authorized_versions.get(row["document_version_id"], False)
            )
        )
        citations = (await session.execute(text("""
            SELECT ar.answer_message_id,ac.*
            FROM answer_runs ar JOIN answer_citations ac
              ON ac.answer_run_id=ar.answer_run_id
            WHERE ac.citation_id=ANY(CAST(:citation_ids AS uuid[]))
            ORDER BY ar.created_at,ac.marker
        """), {"citation_ids": allowed_citation_ids})).mappings().all()
    by_message: dict[uuid.UUID, list[Citation]] = {}
    for row in citations:
        by_message.setdefault(row["answer_message_id"], []).append(
            _citation(dict(row)),
        )
    messages = [
        ConversationMessage(
            message_id=row["message_id"],
            role=row["role"],
            content=contents.get(
                row["message_id"],
                "Evidence is no longer available.",
            ),
            answer_state=row["answer_state"],
            citations=by_message.get(row["message_id"], []),
            created_at=row["created_at"],
        )
        for row in headers
    ]
    async with UnitOfWork().transaction() as session:
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=uuid.UUID(subject.user_id),
            action="rag.conversation.view",
            result="success",
            reason_code="owner_access",
            request_id=request_id,
            resource_type="conversation",
            details={
                "conversation_id": str(conversation_id),
                "message_count": len(messages),
                "citation_revocations": len(blocked_messages),
            },
        )
    return ConversationResponse(
        conversation_id=conversation_id,
        messages=messages,
        request_id=request_id,
    )
