"""Independent late-disclosure SQL proofs; not native SDK/runtime proofs.

The frozen 22-case module is unchanged. These eight additional scenarios use
its domain setup helpers, real source/output rows and real authorization.
Scheduling hooks only pause completed content/receipt reads; they never replace
authority, source status, guards or outcomes. No provider method is invoked.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_execution_adversarial as adversarial
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from test_action_contracts_integration import deny, principal

from rtr_copilot.actions import execution as execution_module
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.models import Role
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion import api as files_api
from rtr_copilot.rag.answering import AnswerService
from rtr_copilot.rag.models import ProviderAnswer, SearchFilters
from rtr_copilot.rag.provider_usage import ProviderUsage
from rtr_copilot.rag.retrieval import RetrievalService

pytestmark = adversarial.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for session_factory in adversarial.factory.__wrapped__():
        yield session_factory


@pytest.fixture
def execution_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


class NeverCalledProvider:
    name = "synthetic-no-provider"
    model = "not-called"

    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("this disclosure test must never invoke a provider")


async def linked_file(factory: Any, tmp_path: Path, execution_config: Any) -> Any:
    executor, owner, refs, documents, _, view = await adversarial.submitted(
        factory,
        tmp_path,
        execution_config,
        draft=True,
    )
    job = await adversarial.accepted_job(executor, owner, view.run_id)
    await documents.process_render(job, worker_id="independent-disclosure")
    source = await documents.status(owner, job, request_id="disclosure-file")
    assert source.state == "completed" and source.generated_file_id and source.version_id
    settings = execution_config.model_copy(
        update={
            "rag_embedding_provider": "offline",
            "rag_provider_mode": "local",
            "rag_rewrite_enabled": False,
            "rag_answer_llm_required": False,
            "openai_api_key": None,
            "anthropic_api_key": None,
        }
    )
    retrieval = RetrievalService(settings, factory=factory)
    answer = AnswerService(
        settings, factory=factory, retrieval=retrieval, provider=NeverCalledProvider()
    )
    hits = await retrieval.search(
        owner,
        "HERA",
        filters=SearchFilters(
            version_id=source.version_id,
        ),
        request_id="disclosure-retrieve",
    )
    assert hits and all(hit.citation.document_version_id == source.version_id for hit in hits)
    assert all(hit.citation.record_version_id is None for hit in hits)
    async with factory() as session:
        template_id = await session.scalar(
            text("""
            SELECT tv.template_id FROM template_versions tv
            JOIN render_jobs j ON j.template_version_id=tv.version_id
            WHERE j.render_job_id=:job
        """),
            {"job": job},
        )
    return executor, owner, refs, documents, source, answer, retrieval, hits, template_id


async def denied_final_admission(
    answer: AnswerService, owner: Any, hits: Any, *, use_class: str, request_id: str
) -> None:
    # Denial happens before persistence, so invented conversation/run rows are
    # not required and no fabricated grounded assistant message is committed.
    admitted = await answer._persist_grounded(
        owner,
        conversation_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        request_id=request_id,
        output=ProviderAnswer(answer="HERA [C1]", used_markers=["C1"]),
        selected=hits,
        serialized="synthetic-denied-only",
        grounding_error="",
        coverage_state="complete",
        provider_usage=ProviderUsage(),
        started=time.monotonic(),
        use_class=use_class,
    )
    assert not admitted


@pytest.mark.asyncio
@pytest.mark.parametrize("seam", ["resolved_content", "receipt_lookup"])
@pytest.mark.parametrize("mutation", ["acl", "actor_version"])
async def test_r0_late_revocation_cannot_disclose_already_resolved_text(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
    mutation: str,
) -> None:
    executor, owner, refs, _, _, view = await adversarial.submitted(
        factory,
        tmp_path,
        execution_config,
    )
    await executor.advance(view.run_id)
    entered, release = asyncio.Event(), asyncio.Event()
    if seam == "resolved_content":
        actual_resolve = execution_module.revalidate_sot_references

        async def pause_resolution(*args: Any, **kwargs: Any) -> Any:
            result = await actual_resolve(*args, **kwargs)
            assert result.sources and "HERA" in result.sources[0].text
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(execution_module, "revalidate_sot_references", pause_resolution)
    else:
        actual_scalar = AsyncSession.scalar

        async def pause_receipt(
            session: AsyncSession, statement: Any, *args: Any, **kwargs: Any
        ) -> Any:
            result = await actual_scalar(session, statement, *args, **kwargs)
            if "action_execution_receipts" in str(statement) and "output_digest" in str(statement):
                assert result is True
                entered.set()
                await release.wait()
            return result

        monkeypatch.setattr(AsyncSession, "scalar", pause_receipt)
    disclosure = asyncio.create_task(
        executor.read_output(
            owner,
            view.run_id,
            "read",
            request_id="late-disclosure",
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 10)
        if mutation == "acl":
            await deny(factory, refs[0], owner)
        else:
            async with factory() as session, session.begin():
                await session.execute(
                    text("""
                    UPDATE subjects SET security_version=security_version+1
                    WHERE user_id=:actor
                """),
                    {"actor": uuid.UUID(owner.user_id)},
                )
    finally:
        release.set()
    with pytest.raises(ActionError):
        await asyncio.wait_for(disclosure, 10)
    # Only metadata remained recorded: no newly returned resolved-text payload.
    state = await executor.status(owner, view.run_id)
    assert len(state.receipts) == 1 and state.receipts[0].kind == "read_verified"
    assert "HERA" not in state.model_dump_json()


@pytest.mark.asyncio
async def test_linked_file_only_ask_filter_respects_requested_purpose_and_final_admission(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    _, owner, _, _, _, answer, _, hits, _ = await linked_file(
        factory,
        tmp_path,
        execution_config,
    )
    kept, denied = await answer._use_class_filtered(
        hits,
        use_class="proposal",
        request_id="proposal-filter",
    )
    assert kept == hits and not denied
    excluded, denied = await answer._use_class_filtered(
        hits,
        use_class="attestation",
        request_id="attestation-filter",
    )
    assert not excluded and denied
    # Changing Ask purpose after initial selection must still be rejected at
    # actual final DB admission, not only by the initial retrieval filter.
    await denied_final_admission(
        answer, owner, kept, use_class="attestation", request_id="attestation-final"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["acl", "narrower_revision"])
async def test_late_linked_source_revocation_blocks_every_content_surface_and_final_ask(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    (
        executor,
        owner,
        refs,
        documents,
        source,
        answer,
        retrieval,
        hits,
        template_id,
    ) = await linked_file(factory, tmp_path, execution_config)
    kept, denied = await answer._use_class_filtered(
        hits,
        use_class="proposal",
        request_id="initial-permitted-filter",
    )
    assert kept == hits and not denied
    if mutation == "acl":
        await deny(factory, refs[0], owner)
    else:
        await adversarial.narrower_revision(factory, tmp_path, owner, refs)
    with pytest.raises(LookupError):
        await documents.generated_detail(owner, source.generated_file_id, request_id="late-detail")
    with pytest.raises(LookupError):
        await documents.generated_history(owner, template_id, request_id="late-history")
    monkeypatch.setattr(files_api, "UnitOfWork", lambda: UnitOfWork(factory))
    file_authorized = await files_api._version_authorized(
        owner,
        source.version_id,
        action="download",
        request_id="late-file",
    )
    assert file_authorized is None or not file_authorized[1]
    async with factory() as session:
        assert (
            await retrieval._file_authorized(session, owner, source.version_id, "late-rag") is None
        )
        assert not await retrieval.selected_still_allowed(
            session,
            owner,
            [hit.chunk_id for hit in hits],
            "late-selected",
        )
    await denied_final_admission(
        answer, owner, kept, use_class="proposal", request_id="late-final-ask"
    )
    if mutation == "narrower_revision":
        excluded, denied = await answer._use_class_filtered(
            hits,
            use_class="proposal",
            request_id="late-purpose-filter",
        )
        assert not excluded and denied
    async with factory() as session:
        run_id = await session.scalar(
            text("""
            SELECT run_id FROM action_source_links WHERE render_job_id=:job
        """),
            {"job": source.render_job_id},
        )
    assert run_id is not None
    state = await executor.status(owner, run_id)
    assert "HERA" not in state.model_dump_json()


@pytest.mark.asyncio
async def test_private_template_allow_expiring_during_final_transaction_is_not_authority(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    actions, _, refs, _, template_version = await adversarial.domain(
        factory,
        tmp_path,
        locked=True,
    )
    delegated = await principal(factory, Role.CURATOR)
    actor = uuid.UUID(delegated.user_id)
    acl_ids = [uuid.uuid4(), uuid.uuid4()]
    async with factory() as session, session.begin():
        for acl_id, action in zip(acl_ids, ["view", "render"], strict=True):
            await session.execute(
                text("""
                INSERT INTO acl_entries(acl_id,resource_id,principal_type,principal_id,
                  action,effect,expires_at,reason)
                VALUES(:acl,:template,'user',:actor,:action,'allow',
                  statement_timestamp()+interval '1 hour','synthetic-temporary-delegation')
            """),
                {"acl": acl_id, "template": template_version, "actor": actor, "action": action},
            )
    plan = await actions.create_plan(
        delegated,
        PlanRequest(
            idempotency_key=f"expiry-plan-{uuid.uuid4()}",
            objective="Explicit delegated draft",
            source_refs=refs,
            requested_internal_draft=True,
            steps=(
                StepRequest(
                    step_key="draft",
                    capability_id="documents.create_draft",
                    capability_version="2",
                    arguments={"template_version_id": str(template_version), "parameters": {}},
                ),
            ),
        ),
        request_id="temporal-delegation-plan",
    )
    expires = datetime.now(UTC) + timedelta(seconds=2)
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            UPDATE acl_entries SET expires_at=:expires WHERE acl_id=ANY(:ids)
        """),
            {"expires": expires, "ids": acl_ids},
        )
    # The same private-template final guard succeeds while the grant is current.
    async with actions.uow.transaction() as session:
        await actions._snapshot(session, delegated, plan.payload, "before-expiry")
    # Begin the FINAL transaction before expiry, then deliberately wait beyond
    # it. PostgreSQL now() remains transaction-start time; statement time must
    # remove the private allow instead of letting the old snapshot authorize.
    with pytest.raises(ActionError):
        async with actions.uow.transaction() as session:
            started = await session.scalar(text("SELECT statement_timestamp()"))
            assert started < expires
            await asyncio.sleep(max(0, (expires - datetime.now(UTC)).total_seconds()) + 0.05)
            current = await session.scalar(text("SELECT statement_timestamp()"))
            assert current >= expires
            await actions._snapshot(session, delegated, plan.payload, "after-expiry-final")
