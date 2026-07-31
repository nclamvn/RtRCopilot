import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.config import Settings, get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.rag.adapters import OfflineHashEmbedding, normalize_query
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.rag.models import Citation, RetrievalHit, SearchFilters
from rtr_copilot.repositories.resources import CLASSIFICATION_TO_POLICY

CLASSIFICATION_RANK = {
    "public_internal": 0,
    "internal": 1,
    "restricted": 2,
    "highly_restricted": 3,
}


class RetrievalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class RetrievalTrace:
    metadata_rows: int = 0
    policy_allowed: int = 0
    content_queries: int = 0
    loaded_chunk_ids: list[uuid.UUID] = field(default_factory=list)
    dlp_rule_ids: list[str] = field(default_factory=list)


class RetrievalService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        provider_policy: ProviderPolicy | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.uow = UnitOfWork(factory)
        self.policy = PolicyEngine(StructuredAuditSink())
        self.embedding = OfflineHashEmbedding(self.settings.rag_embedding_dimension)
        allowlist = frozenset(
            item.strip()
            for item in self.settings.rag_external_classification_allowlist.split(",")
            if item.strip()
        )
        self.provider_policy = provider_policy or ProviderPolicy(
            mode=self.settings.rag_provider_mode,
            external_allowlist=allowlist,
        )
        self.trace = RetrievalTrace()

    async def _metadata(
        self,
        subject: Subject,
        filters: SearchFilters,
        *,
        after_chunk_key: str | None = None,
        page_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        ceiling = (
            CLASSIFICATION_RANK[filters.classification_ceiling]
            if filters.classification_ceiling
            else 3
        )
        principal = uuid.UUID(subject.user_id)
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                SELECT c.chunk_id,c.chunk_key,c.record_id,c.generation_id,
                  c.source_key,c.source_revision,c.classification,c.owner_subject_id,
                  c.department_id,c.project_id,c.provenance_level,
                  c.verification_state,c.freshness_state,
                  has_effective_acl_deny(
                    c.record_id,CAST(:principal AS uuid),CAST('view' AS text)
                  ) AS explicit_deny
                FROM active_search_generations ag
                JOIN search_generations g ON g.generation_id=ag.generation_id
                  AND g.lifecycle='active'
                JOIN chunks c ON c.generation_id=g.generation_id
                  AND c.lifecycle='active'
                WHERE (CAST(:source_key AS text) IS NULL
                  OR c.source_key=CAST(:source_key AS text))
                  AND CASE c.classification
                    WHEN 'public_internal' THEN 0 WHEN 'internal' THEN 1
                    WHEN 'restricted' THEN 2 ELSE 3 END <= :ceiling
                  AND (:include_stale OR c.freshness_state='current')
                  AND (cardinality(CAST(:provenance AS text[]))=0
                    OR c.provenance_level=ANY(CAST(:provenance AS text[])))
                  AND (CAST(:after_chunk_key AS text) IS NULL
                    OR c.chunk_key>CAST(:after_chunk_key AS text))
                ORDER BY c.chunk_key
                LIMIT :page_limit
            """), {
                "principal": principal,
                "source_key": filters.source_key,
                "ceiling": ceiling,
                "include_stale": filters.include_stale,
                "provenance": filters.provenance,
                "after_chunk_key": after_chunk_key,
                "page_limit": page_limit or self.settings.rag_candidate_limit,
            })).mappings().all()
        return [dict(row) for row in rows]

    def _allowed(
        self,
        subject: Subject,
        rows: list[dict[str, Any]],
        request_id: str,
    ) -> list[uuid.UUID]:
        allowed: list[uuid.UUID] = []
        for row in rows:
            attributes = ResourceAttributes(
                resource_id=str(row["record_id"]),
                owner_id=str(row["owner_subject_id"]),
                classification=CLASSIFICATION_TO_POLICY[row["classification"]],
                department=(
                    str(row["department_id"]) if row["department_id"] else None
                ),
                project=str(row["project_id"]) if row["project_id"] else None,
                source_zone="sot",
                lifecycle_state="active",
                explicit_deny=bool(row["explicit_deny"]),
            )
            decision = self.policy.decide(
                subject,
                "view",
                attributes,
                PolicyContext(request_id=request_id),
            )
            if decision.allow:
                allowed.append(row["chunk_id"])
        return allowed

    async def selected_still_allowed(
        self,
        session: AsyncSession,
        subject: Subject,
        chunk_ids: list[uuid.UUID],
        request_id: str,
    ) -> bool:
        """Revalidate exact active lineage and effective policy without content."""
        if not chunk_ids:
            return False
        principal = uuid.UUID(subject.user_id)
        rows = (await session.execute(text("""
            SELECT c.chunk_id,c.chunk_key,c.record_id,c.generation_id,
              c.source_key,c.source_revision,c.classification,c.owner_subject_id,
              c.department_id,c.project_id,c.provenance_level,
              c.verification_state,c.freshness_state,
              has_effective_acl_deny(
                c.record_id,CAST(:principal AS uuid),CAST('view' AS text)
              ) AS explicit_deny
            FROM chunks c
            JOIN active_search_generations ag
              ON ag.generation_id=c.generation_id
            JOIN search_generations g ON g.generation_id=ag.generation_id
              AND g.lifecycle='active'
            JOIN records r ON r.record_id=c.record_id
              AND r.lifecycle='active'
              AND r.current_version_id=c.record_version_id
            JOIN record_versions rv ON rv.version_id=c.record_version_id
              AND rv.lifecycle='active'
            WHERE c.chunk_id=ANY(CAST(:chunk_ids AS uuid[]))
              AND c.lifecycle='active'
            ORDER BY c.chunk_key
        """), {
            "principal": principal,
            "chunk_ids": chunk_ids,
        })).mappings().all()
        metadata = [dict(row) for row in rows]
        return (
            len(metadata) == len(set(chunk_ids))
            and set(self._allowed(subject, metadata, request_id)) == set(chunk_ids)
        )

    async def search(
        self,
        subject: Subject,
        query: str,
        *,
        filters: SearchFilters,
        request_id: str,
        top_k: int | None = None,
    ) -> list[RetrievalHit]:
        self.trace = RetrievalTrace()
        if len(query.encode()) > self.settings.rag_query_max_bytes:
            raise RetrievalError("query_budget_exceeded")
        normalized = normalize_query(query)
        if not normalized:
            raise RetrievalError("query_empty_after_normalization")
        metadata: list[dict[str, Any]] = []
        allowed_ids: list[uuid.UUID] = []
        cursor: str | None = None
        scanned = 0
        deadline = (
            time.monotonic() + self.settings.rag_retrieval_timeout_ms / 1000
        )
        while (
            len(allowed_ids) < self.settings.rag_candidate_limit
            and scanned < self.settings.rag_metadata_scan_limit
        ):
            page_limit = min(
                self.settings.rag_candidate_limit,
                self.settings.rag_metadata_scan_limit - scanned,
            )
            page = await self._metadata(
                subject,
                filters,
                after_chunk_key=cursor,
                page_limit=page_limit,
            )
            if not page:
                break
            scanned += len(page)
            self.trace.metadata_rows += len(page)
            page_allowed_ids = set(self._allowed(subject, page, request_id))
            for row in page:
                if row["chunk_id"] in page_allowed_ids:
                    metadata.append(row)
                    allowed_ids.append(row["chunk_id"])
                    if len(allowed_ids) >= self.settings.rag_candidate_limit:
                        break
            cursor = str(page[-1]["chunk_key"])
            if len(page) < page_limit:
                break
            if time.monotonic() >= deadline:
                raise RetrievalError("retrieval_budget_exceeded")
        self.trace.policy_allowed = len(allowed_ids)
        if not allowed_ids:
            return []
        query_vector = self.embedding.embed(normalized)
        self.trace.content_queries += 1
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                SELECT c.chunk_id,c.chunk_key,c.record_id,c.generation_id,
                  c.display_text,c.classification,c.record_key,c.record_version_id,
                  c.evidence_key,c.record_checksum,c.evidence_checksum,c.source_key,
                  c.source_revision,c.provenance_level,c.verification_state,
                  c.freshness_state,c.source_label,c.locator,
                  ts_rank_cd(c.lexical,plainto_tsquery('simple',:query)) lexical_score,
                  greatest(0,1-(c.embedding <=> CAST(:embedding AS vector))) vector_score
                FROM chunks c
                JOIN active_search_generations ag
                  ON ag.generation_id=c.generation_id
                JOIN search_generations g ON g.generation_id=ag.generation_id
                  AND g.lifecycle='active'
                WHERE c.chunk_id=ANY(:allowed_ids) AND c.lifecycle='active'
                ORDER BY c.chunk_key
            """), {
                "query": normalized,
                "embedding": json.dumps(query_vector),
                "allowed_ids": allowed_ids,
            })).mappings().all()
        content = [dict(row) for row in rows]
        self.trace.loaded_chunk_ids = [row["chunk_id"] for row in content]
        lex_order = {
            row["chunk_id"]: rank
            for rank, row in enumerate(
                sorted(
                    content,
                    key=lambda item: (
                        -float(item["lexical_score"]),
                        str(item["chunk_key"]),
                    ),
                ),
                1,
            )
        }
        vector_order = {
            row["chunk_id"]: rank
            for rank, row in enumerate(
                sorted(
                    content,
                    key=lambda item: (
                        -float(item["vector_score"]),
                        str(item["chunk_key"]),
                    ),
                ),
                1,
            )
        }
        ranked: list[tuple[float, dict[str, Any]]] = []
        metadata_by_id = {row["chunk_id"]: row for row in metadata}
        for row in content:
            if (
                float(row["lexical_score"]) <= 0
                and float(row["vector_score"])
                < self.settings.rag_min_vector_score
            ):
                continue
            security = metadata_by_id.get(row["chunk_id"])
            if security is None or row["chunk_id"] not in self._allowed(
                subject,
                [security],
                request_id,
            ):
                continue
            dlp = self.provider_policy.inspect(
                str(row["display_text"]),
                classification=str(row["classification"]),
            )
            if not dlp.allow or dlp.text is None:
                self.trace.dlp_rule_ids.extend(dlp.rule_ids)
                continue
            row["display_text"] = dlp.text
            fusion = (
                1.0 / (60 + lex_order[row["chunk_id"]])
                + 1.0 / (60 + vector_order[row["chunk_id"]])
                + min(float(row["lexical_score"]), 1.0) * 0.1
            )
            ranked.append((fusion, row))
        ranked.sort(key=lambda item: (-item[0], str(item[1]["chunk_key"])))
        limit = min(top_k or self.settings.rag_top_k, self.settings.rag_top_k)
        output: list[RetrievalHit] = []
        used_bytes = 0
        for fusion, row in ranked:
            payload = str(row["display_text"])
            used_bytes += len(payload.encode())
            if used_bytes > self.settings.rag_evidence_max_bytes:
                break
            citation = Citation(
                marker=f"C{len(output) + 1}",
                chunk_id=row["chunk_id"],
                record_key=row["record_key"],
                record_version_id=row["record_version_id"],
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
            )
            output.append(RetrievalHit(
                chunk_id=row["chunk_id"],
                chunk_key=row["chunk_key"],
                snippet=payload,
                lexical_score=float(row["lexical_score"]),
                vector_score=float(row["vector_score"]),
                fusion_score=fusion,
                classification=row["classification"],
                citation=citation,
            ))
            if len(output) >= limit:
                break
        return output


def scope_fingerprint(subject: Subject, chunk_ids: list[uuid.UUID]) -> str:
    value = {
        "subject": subject.user_id,
        "roles": sorted(role.value for role in subject.roles),
        "groups": sorted(subject.groups),
        "departments": sorted(subject.departments),
        "projects": sorted(subject.projects),
        "chunks": sorted(str(item) for item in chunk_ids),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()
