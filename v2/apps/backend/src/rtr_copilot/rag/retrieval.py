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
from rtr_copilot.rag.adapters import (
    OfflineHashEmbedding,
    lexical_query,
    normalize_query,
)
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.rag.models import Citation, RetrievalHit, SearchFilters
from rtr_copilot.rag.query_understanding import QueryIntent
from rtr_copilot.rag.relevance import candidate_relevance_score, profile_query
from rtr_copilot.repositories.resources import (
    CLASSIFICATION_TO_POLICY,
    ResourceRepository,
)

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

    async def _file_authorized(
        self,
        session: AsyncSession,
        subject: Subject,
        version_id: uuid.UUID,
        request_id: str,
    ) -> tuple[dict[str, Any], ResourceAttributes] | None:
        principal = uuid.UUID(subject.user_id)
        principal_rows = (await session.execute(text("""
            SELECT group_id principal_id FROM subject_groups
            WHERE subject_id=:subject_id AND valid_from<=now()
              AND (expires_at IS NULL OR expires_at>now())
            UNION SELECT role_id FROM subject_roles
            WHERE subject_id=:subject_id AND valid_from<=now()
              AND (expires_at IS NULL OR expires_at>now())
            UNION SELECT CAST(scope_key AS uuid) FROM subject_scopes
            WHERE subject_id=:subject_id AND valid_from<=now()
              AND (expires_at IS NULL OR expires_at>now())
              AND scope_key ~* :uuid_pattern
        """), {
            "subject_id": principal,
            "uuid_pattern": (
                "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
                "[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
            ),
        })).scalars().all()
        principals = {principal, *principal_rows}
        effective = await ResourceRepository().effective_policy_attributes(
            session,
            version_id,
            action="view",
            principal_ids=principals,
        )
        row = (await session.execute(text("""
            SELECT v.version_id,v.sha256,v.original_filename,d.logical_name,
              r.classification
            FROM document_versions v
            JOIN documents d ON d.document_id=v.document_id
            JOIN resources r ON r.resource_id=v.version_id
            WHERE v.version_id=:version_id AND r.lifecycle_state='active'
        """), {"version_id": version_id})).mappings().one_or_none()
        if effective is None or row is None:
            return None
        attributes = effective[0]
        if not self.policy.decide(
            subject,
            "view",
            attributes,
            PolicyContext(request_id=request_id),
        ).allow:
            return None
        return dict(row), attributes

    async def _search_file(
        self,
        subject: Subject,
        query: str,
        normalized: str,
        *,
        filters: SearchFilters,
        request_id: str,
        top_k: int | None,
        query_entities: tuple[str, ...] | None,
        query_intent: QueryIntent | None,
    ) -> list[RetrievalHit]:
        assert filters.version_id is not None
        lexquery = lexical_query(normalized)
        if not lexquery:
            return []
        query_profile = profile_query(
            query,
            entities=query_entities,
            intent=query_intent,
        )
        async with self.uow.factory() as session:
            authorized = await self._file_authorized(
                session, subject, filters.version_id, request_id,
            )
            if authorized is None:
                return []
            version, attributes = authorized
            effective_rank = {
                "public": 0, "internal": 1, "restricted": 2, "classified": 3,
            }[attributes.classification]
            effective_classification = {
                "public": "public_internal",
                "internal": "internal",
                "restricted": "restricted",
                "classified": "highly_restricted",
            }[attributes.classification]
            ceiling = (
                CLASSIFICATION_RANK[filters.classification_ceiling]
                if filters.classification_ceiling else 3
            )
            if effective_rank > ceiling:
                return []
            metadata_count = await session.scalar(text("""
                SELECT count(*)
                FROM file_chunks fc
                JOIN renditions rd ON rd.rendition_id=fc.rendition_id
                JOIN resources rr ON rr.resource_id=rd.rendition_id
                WHERE fc.document_version_id=:version_id
                  AND fc.lifecycle='active' AND rd.status='ready'
                  AND rr.lifecycle_state='active'
            """), {
                "version_id": filters.version_id,
            })
        self.trace.metadata_rows = int(metadata_count or 0)
        self.trace.policy_allowed = self.trace.metadata_rows
        if not metadata_count:
            return []
        query_vector = self.embedding.embed(" ".join(query_profile.terms))
        self.trace.content_queries = 1
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                SELECT fc.file_chunk_id,fc.chunk_key,fc.display_text,
                  fc.document_version_id,fc.rendition_kind,fc.source_sha256,
                  fc.rendition_sha256,fc.locator,
                  ts_rank_cd(fc.lexical,to_tsquery('simple',:lexquery)) lexical_score,
                  greatest(0,1-(fc.embedding <=> CAST(:embedding AS vector))) vector_score
                FROM file_chunks fc
                JOIN renditions rd ON rd.rendition_id=fc.rendition_id
                JOIN resources rr ON rr.resource_id=rd.rendition_id
                WHERE fc.document_version_id=:version_id
                  AND fc.lifecycle='active'
                  AND rd.status='ready' AND rr.lifecycle_state='active'
                ORDER BY lexical_score DESC,vector_score DESC,fc.chunk_key
                LIMIT :candidate_limit
            """), {
                "lexquery": lexquery,
                "embedding": json.dumps(query_vector),
                "version_id": filters.version_id,
                "candidate_limit": self.settings.rag_candidate_limit,
            })).mappings().all()
        content = [dict(row) for row in rows]
        self.trace.loaded_chunk_ids = [row["file_chunk_id"] for row in content]
        lex_order = {row["file_chunk_id"]: rank for rank, row in enumerate(
            sorted(content, key=lambda item: (-float(item["lexical_score"]), item["chunk_key"])), 1,
        )}
        vector_order = {row["file_chunk_id"]: rank for rank, row in enumerate(
            sorted(content, key=lambda item: (-float(item["vector_score"]), item["chunk_key"])), 1,
        )}
        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in content:
            if (
                float(row["lexical_score"]) <= 0
                and float(row["vector_score"])
                < self.settings.rag_min_vector_score
            ):
                continue
            dlp = self.provider_policy.inspect(
                str(row["display_text"]), classification=effective_classification,
            )
            if not dlp.allow or dlp.text is None:
                self.trace.dlp_rule_ids.extend(dlp.rule_ids)
                continue
            row["display_text"] = dlp.text
            base_fusion = (
                1.0 / (60 + lex_order[row["file_chunk_id"]])
                + 1.0 / (60 + vector_order[row["file_chunk_id"]])
                + min(float(row["lexical_score"]), 1.0) * 0.1
            )
            fusion = candidate_relevance_score(
                query_profile,
                text=str(row["display_text"]),
                record_key=str(version["logical_name"]),
                base_score=base_fusion,
                vector_score=float(row["vector_score"]),
                min_vector_score=self.settings.rag_min_vector_score,
            )
            if fusion is not None:
                ranked.append((fusion, row))
        ranked.sort(key=lambda item: (-item[0], item[1]["chunk_key"]))
        limit = min(
            top_k or self.settings.rag_top_k,
            self.settings.rag_answer_candidate_k,
        )
        output: list[RetrievalHit] = []
        used_bytes = 0
        for fusion, row in ranked:
            payload = str(row["display_text"])
            used_bytes += len(payload.encode())
            if used_bytes > self.settings.rag_evidence_max_bytes:
                break
            chunk_id = row["file_chunk_id"]
            output.append(RetrievalHit(
                chunk_id=chunk_id,
                chunk_key=row["chunk_key"],
                snippet=payload,
                lexical_score=float(row["lexical_score"]),
                vector_score=float(row["vector_score"]),
                fusion_score=fusion,
                classification=effective_classification,
                citation=Citation(
                    zone_label="private", marker=f"C{len(output) + 1}",
                    chunk_id=chunk_id, record_key=str(version["logical_name"]),
                    document_version_id=filters.version_id,
                    evidence_key=str(row["rendition_kind"]),
                    record_checksum=str(row["source_sha256"]),
                    evidence_checksum=str(row["rendition_sha256"]),
                    source_key=f"file:{filters.version_id}", source_revision=1,
                    provenance_level="approved_internal",
                    verification_state="approved", freshness_state="current",
                    source_label=str(version["original_filename"]),
                    locator=dict(row["locator"]),
                ),
            ))
            if len(output) >= limit:
                break
        return output

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
        file_versions = list((await session.execute(text("""
            SELECT DISTINCT document_version_id FROM file_chunks
            WHERE file_chunk_id=ANY(CAST(:chunk_ids AS uuid[]))
              AND lifecycle='active'
        """), {"chunk_ids": chunk_ids})).scalars())
        if file_versions:
            file_count = await session.scalar(text("""
                SELECT count(*) FROM file_chunks fc
                JOIN renditions rd ON rd.rendition_id=fc.rendition_id
                JOIN resources rr ON rr.resource_id=rd.rendition_id
                WHERE fc.file_chunk_id=ANY(CAST(:chunk_ids AS uuid[]))
                  AND fc.lifecycle='active' AND rd.status='ready'
                  AND rr.lifecycle_state='active'
            """), {"chunk_ids": chunk_ids})
            if len(file_versions) != 1 or int(file_count or 0) != len(set(chunk_ids)):
                return False
            return await self._file_authorized(
                session, subject, file_versions[0], request_id,
            ) is not None
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
        query_entities: tuple[str, ...] | None = None,
        query_intent: QueryIntent | None = None,
    ) -> list[RetrievalHit]:
        self.trace = RetrievalTrace()
        if len(query.encode()) > self.settings.rag_query_max_bytes:
            raise RetrievalError("query_budget_exceeded")
        normalized = normalize_query(query)
        if not normalized:
            raise RetrievalError("query_empty_after_normalization")
        lexquery = lexical_query(normalized)
        if not lexquery:
            return []
        if filters.version_id is not None:
            return await self._search_file(
                subject,
                query,
                normalized,
                filters=filters,
                request_id=request_id,
                top_k=top_k,
                query_entities=query_entities,
                query_intent=query_intent,
            )
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
        query_profile = profile_query(
            query,
            entities=query_entities,
            intent=query_intent,
        )
        query_vector = self.embedding.embed(" ".join(query_profile.terms))
        self.trace.content_queries += 1
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                SELECT c.chunk_id,c.chunk_key,c.record_id,c.generation_id,
                  c.display_text,c.classification,c.record_key,c.record_version_id,
                  c.evidence_key,c.record_checksum,c.evidence_checksum,c.source_key,
                  c.source_revision,c.provenance_level,c.verification_state,
                  c.freshness_state,c.source_label,c.locator,
                  ts_rank_cd(c.lexical,to_tsquery('simple',:lexquery)) lexical_score,
                  greatest(0,1-(c.embedding <=> CAST(:embedding AS vector))) vector_score
                FROM chunks c
                JOIN active_search_generations ag
                  ON ag.generation_id=c.generation_id
                JOIN search_generations g ON g.generation_id=ag.generation_id
                  AND g.lifecycle='active'
                WHERE c.chunk_id=ANY(:allowed_ids) AND c.lifecycle='active'
                ORDER BY c.chunk_key
            """), {
                "lexquery": lexquery,
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
            base_fusion = (
                1.0 / (60 + lex_order[row["chunk_id"]])
                + 1.0 / (60 + vector_order[row["chunk_id"]])
                + min(float(row["lexical_score"]), 1.0) * 0.1
            )
            fusion = candidate_relevance_score(
                query_profile,
                text=str(row["display_text"]),
                record_key=str(row["record_key"]),
                base_score=base_fusion,
                vector_score=float(row["vector_score"]),
                min_vector_score=self.settings.rag_min_vector_score,
            )
            if fusion is not None:
                ranked.append((fusion, row))
        ranked.sort(key=lambda item: (-item[0], str(item[1]["chunk_key"])))
        limit = min(
            top_k or self.settings.rag_top_k,
            self.settings.rag_answer_candidate_k,
        )
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
