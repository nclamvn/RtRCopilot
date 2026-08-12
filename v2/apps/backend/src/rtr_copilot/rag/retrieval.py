import asyncio
import contextlib
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
from rtr_copilot.observability.metrics import EMBEDDING_QUERY_DEGRADED
from rtr_copilot.rag.adapters import (
    EmbeddingProviderError,
    OpenAIEmbedding,
    build_embedding_adapter,
    lexical_query,
    normalize_query,
)
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.rag.models import Citation, RetrievalHit, SearchFilters
from rtr_copilot.rag.query_understanding import QueryIntent
from rtr_copilot.rag.relevance import (
    candidate_relevance_score,
    is_procedure_row,
    profile_query,
)
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
    priority_metadata_rows: int = 0
    policy_allowed: int = 0
    priority_policy_allowed: int = 0
    priority_selected: int = 0
    content_queries: int = 0
    loaded_chunk_ids: list[uuid.UUID] = field(default_factory=list)
    dlp_rule_ids: list[str] = field(default_factory=list)
    enterprise_file_versions: int = 0
    enterprise_file_policy_allowed: int = 0
    enterprise_file_loaded_chunk_ids: list[uuid.UUID] = field(default_factory=list)
    # TIP-014RE: True when a provider embedding failure degraded this request
    # to lexical-only ranking (observable, never fails the question).
    embedding_degraded: bool = False


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
        self.embedding = build_embedding_adapter(self.settings)
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

    @property
    def _semantic_floor(self) -> float | None:
        """TIP-014RE: the semantic-bridge floor applies ONLY with a real
        provider adapter. Offline hash proximity stays hard-excluded, and a
        degraded query self-disables the bridge because every vector_score
        collapses to 0 (< any floor)."""
        if isinstance(self.embedding, OpenAIEmbedding):
            return self.settings.rag_semantic_relevance_floor
        return None

    async def _query_vector(self, terms_text: str) -> list[float] | None:
        """Vectorize the recall terms with the configured adapter.

        TIP-014RE degrade law: a provider embedding failure must never fail
        the question. Returning ``None`` sends SQL ``CAST(NULL AS vector)``;
        ``greatest(0, 1-NULL)`` collapses every vector_score to 0, so ranking
        and the candidate filter degrade to the lexical arm exactly. Falling
        back to the offline hash is deliberately NOT done — hash vectors live
        in a different space from provider-indexed chunks and would produce
        garbage similarity instead of an honest degrade.
        """
        if isinstance(self.embedding, OpenAIEmbedding):
            try:
                return await self.embedding.aembed(terms_text)
            except EmbeddingProviderError:
                EMBEDDING_QUERY_DEGRADED.labels(self.embedding.model).inc()
                self.trace.embedding_degraded = True
                return None
        return self.embedding.embed(terms_text)

    @staticmethod
    def _consume_background_result(task: asyncio.Task[Any]) -> None:
        """Mark an overlapped task's terminal exception as observed."""
        if task.cancelled():
            return
        with contextlib.suppress(Exception):
            task.exception()

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
        ranking_query: str | None,
        support_queries: tuple[str, ...],
    ) -> list[RetrievalHit]:
        assert filters.version_id is not None
        lexquery = lexical_query(normalized)
        if not lexquery:
            return []
        query_profile = profile_query(
            ranking_query or query,
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
        # Use the expanded query for recall. The original question remains the
        # final ranking authority in ``candidate_relevance_score`` below.
        # TIP-014RE: the vector arm embeds the RANKING profile (the user's
        # original wording), not the expanded recall soup. Lexical recall
        # still benefits from planner expansions, but concatenating them
        # into the embedded text diluted the question's semantics until the
        # oracle chunk fell under the calibrated bridge floor (observed
        # live: the company-definition dossier crowded out "tech stack").
        # This also keeps the runtime embedding basis identical to the
        # calibration harness that pre-committed the floor.
        query_vector = await self._query_vector(" ".join(query_profile.terms))
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
                "embedding": (
                    json.dumps(query_vector) if query_vector is not None
                    else None
                ),
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
                support_queries=support_queries,
                semantic_floor=self._semantic_floor,
                allow_unbound_definition=True,
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

    async def _search_enterprise_files(
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
        ranking_query: str | None,
        support_queries: tuple[str, ...],
    ) -> list[RetrievalHit]:
        """Search only file sources promoted by a checksum-bound manifest.

        Source/version metadata is selected first, then the ordinary resource
        policy is evaluated for every version. File content is queried only for
        the resulting authorized version ids. This preserves the metadata-first
        invariant of SOT retrieval while adding approved company documents to
        the default Ask scope.
        """

        lexquery = lexical_query(normalized)
        if not lexquery:
            return []
        ceiling = (
            CLASSIFICATION_RANK[filters.classification_ceiling]
            if filters.classification_ceiling else 3
        )
        async with self.uow.factory() as session:
            candidate_ids = list((await session.execute(text("""
                SELECT dv.version_id
                FROM sources s
                JOIN documents d ON d.source_id=s.source_id
                JOIN document_versions dv ON dv.version_id=d.current_version_id
                JOIN resources vr ON vr.resource_id=dv.version_id
                WHERE s.metadata #>> '{enterprise_ask,state}'='enterprise_approved'
                  AND vr.lifecycle_state='active' AND dv.viewer_state='ready'
                  AND CASE vr.classification
                    WHEN 'public_internal' THEN 0 WHEN 'internal' THEN 1
                    WHEN 'restricted' THEN 2 ELSE 3 END <= :ceiling
                ORDER BY d.logical_name,dv.version_id
            """), {"ceiling": ceiling})).scalars())
            self.trace.enterprise_file_versions = len(candidate_ids)
            authorized: dict[uuid.UUID, tuple[dict[str, Any], ResourceAttributes]] = {}
            for version_id in candidate_ids:
                checked = await self._file_authorized(
                    session, subject, version_id, request_id,
                )
                if checked is not None:
                    authorized[version_id] = checked
        self.trace.enterprise_file_policy_allowed = len(authorized)
        if not authorized:
            return []

        query_profile = profile_query(
            ranking_query or query,
            entities=query_entities,
            intent=query_intent,
        )
        document_candidate_limit = {
            # Procedure answers need the complete workflow table, not only the
            # few rows most similar to the wording of the question. The final
            # answer budget still caps selected evidence at twelve chunks.
            "procedure": 64,
            "summarization": 16,
            "analysis": 16,
            "enumeration": 16,
        }.get(query_profile.intent, 8)
        priority_document_limit = {
            # A procedure is a coherent sequence owned by one governing
            # document. Admitting two equally-prioritized documents into the
            # global candidate window can interleave a workflow with its forms
            # and evict low-lexical rows such as an intermediate QC or repair
            # step before sequence reservation runs. Keep the single strongest
            # process document intact; related forms and SLA documents still
            # compete through the ordinary candidate lane and fill remaining
            # answer slots after the numbered workflow rows are reserved.
            "procedure": 1,
            "summarization": 3,
            "analysis": 4,
            "enumeration": 4,
        }.get(query_profile.intent, 2)
        priority_documents: list[tuple[float, uuid.UUID]] = []
        for version_id, (version, _) in authorized.items():
            metadata_score = candidate_relevance_score(
                query_profile,
                text="",
                record_key=str(version["logical_name"]),
                base_score=0.0,
                vector_score=0.0,
                min_vector_score=self.settings.rag_min_vector_score,
                support_queries=support_queries,
                semantic_floor=self._semantic_floor,
                allow_unbound_definition=True,
            )
            if metadata_score is not None:
                priority_documents.append((metadata_score, version_id))
        priority_version_ids = [
            version_id
            for _, version_id in sorted(
                priority_documents,
                key=lambda item: (-item[0], str(item[1])),
            )[:priority_document_limit]
        ]
        # TIP-014RE: the vector arm embeds the RANKING profile (the user's
        # original wording), not the expanded recall soup. Lexical recall
        # still benefits from planner expansions, but concatenating them
        # into the embedded text diluted the question's semantics until the
        # oracle chunk fell under the calibrated bridge floor (observed
        # live: the company-definition dossier crowded out "tech stack").
        # This also keeps the runtime embedding basis identical to the
        # calibration harness that pre-committed the floor.
        query_vector = await self._query_vector(" ".join(query_profile.terms))
        self.trace.content_queries += 1
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                WITH scored AS (
                  SELECT fc.file_chunk_id,fc.chunk_key,fc.display_text,
                    fc.document_version_id,fc.rendition_kind,fc.source_sha256,
                    fc.rendition_sha256,fc.locator,d.logical_name,
                    dv.original_filename,
                    fc.document_version_id=ANY(
                      CAST(:priority_version_ids AS uuid[])
                    ) priority_document,
                    greatest(
                      ts_rank_cd(fc.lexical,to_tsquery('simple',:lexquery)),
                      ts_rank_cd(
                        to_tsvector(
                          'simple',
                          regexp_replace(d.logical_name,'[._-]+',' ','g')
                        ),
                        to_tsquery('simple',:lexquery)
                      )
                    ) lexical_score,
                    greatest(
                      0,1-(fc.embedding <=> CAST(:embedding AS vector))
                    ) vector_score
                  FROM file_chunks fc
                  JOIN renditions rd ON rd.rendition_id=fc.rendition_id
                  JOIN resources rr ON rr.resource_id=rd.rendition_id
                  JOIN document_versions dv ON dv.version_id=fc.document_version_id
                  JOIN documents d ON d.document_id=dv.document_id
                  WHERE fc.document_version_id=ANY(CAST(:version_ids AS uuid[]))
                    AND fc.lifecycle='active' AND rd.status='ready'
                    AND rr.lifecycle_state='active'
                ), diversified AS (
                  SELECT scored.*,row_number() OVER (
                    PARTITION BY document_version_id
                    ORDER BY lexical_score DESC,vector_score DESC,chunk_key
                  ) document_rank
                  FROM scored
                )
                SELECT * FROM diversified
                WHERE document_rank<=:document_candidate_limit
                ORDER BY priority_document DESC,
                  lexical_score DESC,vector_score DESC,chunk_key
                LIMIT :candidate_limit
            """), {
                "lexquery": lexquery,
                "embedding": (
                    json.dumps(query_vector) if query_vector is not None
                    else None
                ),
                "version_ids": list(authorized),
                "candidate_limit": self.settings.rag_candidate_limit,
                "document_candidate_limit": document_candidate_limit,
                "priority_version_ids": priority_version_ids,
            })).mappings().all()
        content = [dict(row) for row in rows]
        self.trace.enterprise_file_loaded_chunk_ids = [
            row["file_chunk_id"] for row in content
        ]
        self.trace.loaded_chunk_ids.extend(self.trace.enterprise_file_loaded_chunk_ids)
        lex_order = {row["file_chunk_id"]: rank for rank, row in enumerate(
            sorted(
                content,
                key=lambda item: (-float(item["lexical_score"]), item["chunk_key"]),
            ),
            1,
        )}
        vector_order = {row["file_chunk_id"]: rank for rank, row in enumerate(
            sorted(
                content,
                key=lambda item: (-float(item["vector_score"]), item["chunk_key"]),
            ),
            1,
        )}
        ranked: list[tuple[float, dict[str, Any], str]] = []
        for row in content:
            if (
                float(row["lexical_score"]) <= 0
                and float(row["vector_score"]) < self.settings.rag_min_vector_score
            ):
                continue
            version_id = row["document_version_id"]
            _, attributes = authorized[version_id]
            effective_classification = {
                "public": "public_internal",
                "internal": "internal",
                "restricted": "restricted",
                "classified": "highly_restricted",
            }[attributes.classification]
            dlp = self.provider_policy.inspect(
                str(row["display_text"]),
                classification=effective_classification,
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
                record_key=str(row["logical_name"]),
                base_score=base_fusion,
                vector_score=float(row["vector_score"]),
                min_vector_score=self.settings.rag_min_vector_score,
                support_queries=support_queries,
                semantic_floor=self._semantic_floor,
                allow_unbound_definition=True,
            )
            if fusion is not None:
                ranked.append((fusion, row, effective_classification))
        ranked.sort(key=lambda item: (-item[0], str(item[1]["chunk_key"])))
        if query_profile.intent == "procedure":
            workflow_rows: dict[
                uuid.UUID,
                list[tuple[float, dict[str, Any], str]],
            ] = {}
            for item in ranked:
                if is_procedure_row(str(item[1]["display_text"])):
                    workflow_rows.setdefault(
                        item[1]["document_version_id"],
                        [],
                    ).append(item)
            coherent_versions = {
                version_id: rows
                for version_id, rows in workflow_rows.items()
                if len(rows) >= 2
            }
            if coherent_versions:
                workflow_version = max(
                    coherent_versions,
                    key=lambda version_id: max(
                        item[0] for item in coherent_versions[version_id]
                    ),
                )
                reserved = sorted(
                    coherent_versions[workflow_version],
                    key=lambda item: str(item[1]["chunk_key"]),
                )
                reserved_ids = {item[1]["file_chunk_id"] for item in reserved}
                ranked = reserved + [
                    item
                    for item in ranked
                    if item[1]["file_chunk_id"] not in reserved_ids
                ]
        limit = min(
            top_k or self.settings.rag_top_k,
            self.settings.rag_answer_candidate_k,
        )
        output: list[RetrievalHit] = []
        used_bytes = 0
        per_version: dict[uuid.UUID, int] = {}
        per_version_limit = {
            "procedure": 12,
            "summarization": 8,
            "analysis": 6,
            "enumeration": 6,
        }.get(query_profile.intent, 3)
        for fusion, row, classification in ranked:
            version_id = row["document_version_id"]
            if per_version.get(version_id, 0) >= per_version_limit:
                continue
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
                classification=classification,
                citation=Citation(
                    zone_label="private",
                    marker=f"C{len(output) + 1}",
                    chunk_id=chunk_id,
                    record_key=str(row["logical_name"]),
                    document_version_id=version_id,
                    evidence_key=str(row["rendition_kind"]),
                    record_checksum=str(row["source_sha256"]),
                    evidence_checksum=str(row["rendition_sha256"]),
                    source_key=f"enterprise-file:{version_id}",
                    source_revision=1,
                    provenance_level="approved_internal",
                    verification_state="approved",
                    freshness_state="current",
                    source_label=str(row["original_filename"]),
                    locator=dict(row["locator"]),
                ),
            ))
            per_version[version_id] = per_version.get(version_id, 0) + 1
            if len(output) >= limit:
                break
        return output

    @staticmethod
    def _merge_enterprise_hits(
        sot_hits: list[RetrievalHit],
        file_hits: list[RetrievalHit],
        *,
        limit: int,
        priority_record_keys: tuple[str, ...],
        query_intent: QueryIntent | None,
        semantic_floor: float | None = None,
    ) -> list[RetrievalHit]:
        priority = set(priority_record_keys)
        reserved = [
            item
            for item in (*sot_hits, *file_hits)
            if item.citation.record_key in priority
        ]
        reserved_ids = {item.chunk_id for item in reserved}
        # File retrieval already reconstructed coherent procedure rows in
        # ordinal order. Re-sorting every SOT/file hit by scalar fusion here
        # destroyed that contract and could evict intermediate steps from an
        # otherwise complete B1..B9 workflow. Preserve the complete numbered
        # block across source merging; authority-bound SOT rows still lead and
        # ordinary related material fills only the remaining evidence budget.
        if query_intent == "procedure":
            workflow = [
                item
                for item in file_hits
                if item.chunk_id not in reserved_ids
                and is_procedure_row(item.snippet)
            ]
            reserved.extend(workflow)
            reserved_ids.update(item.chunk_id for item in workflow)
        # Once the ontology has resolved a question to one or more curator-
        # bound records, those records are the evidence boundary for an EXACT
        # entity/definition question ("Hera là gì"): appending unrelated
        # high-scoring file chunks made it noisier than an open search and
        # caused the reviewer to reject otherwise supported answers.
        #
        # TIP-014RE: a specific-ATTRIBUTE question ("website công ty dùng tech
        # stack gì?") resolves the SAME entity — pulling its whole definition
        # dossier in as reserved — yet is answered by a NON-reserved record
        # that the strict boundary (remaining=[]) silently discarded. With
        # real embeddings, admit non-reserved records whose semantic cosine
        # clears the provider bridge floor (genuine answers, not low-
        # similarity noise) for lookup/enumeration intents. Definition intent
        # keeps the strict dossier boundary; procedures and open questions are
        # unchanged; offline/degraded (floor is None) collapses to the exact
        # previous behaviour.
        def _by_fusion(items: list[RetrievalHit]) -> list[RetrievalHit]:
            return sorted(
                items, key=lambda item: (-item.fusion_score, item.chunk_key),
            )

        non_reserved = [
            item for item in (*sot_hits, *file_hits)
            if item.chunk_id not in reserved_ids
        ]
        if query_intent == "procedure" or not reserved:
            remaining = _by_fusion(non_reserved)
        elif query_intent == "definition" or semantic_floor is None:
            remaining = []
        else:
            remaining = _by_fusion([
                item for item in non_reserved
                if item.vector_score >= semantic_floor
            ])
        selected = (reserved + remaining)[:limit]
        return [
            item.model_copy(update={
                "citation": item.citation.model_copy(update={"marker": f"C{index}"}),
            })
            for index, item in enumerate(selected, 1)
        ]

    async def _metadata(
        self,
        subject: Subject,
        filters: SearchFilters,
        *,
        after_chunk_key: str | None = None,
        page_limit: int | None = None,
        record_keys: tuple[str, ...] = (),
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
                  AND (cardinality(CAST(:record_keys AS text[]))=0
                    OR c.record_key=ANY(CAST(:record_keys AS text[])))
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
                "record_keys": list(record_keys),
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
        file_rows = (await session.execute(text("""
            SELECT fc.file_chunk_id,fc.document_version_id
            FROM file_chunks fc
            JOIN renditions rd ON rd.rendition_id=fc.rendition_id
            JOIN resources rr ON rr.resource_id=rd.rendition_id
            WHERE fc.file_chunk_id=ANY(CAST(:chunk_ids AS uuid[]))
              AND fc.lifecycle='active' AND rd.status='ready'
              AND rr.lifecycle_state='active'
        """), {"chunk_ids": chunk_ids})).mappings().all()
        file_chunk_ids = {row["file_chunk_id"] for row in file_rows}
        versions = {row["document_version_id"] for row in file_rows}
        for version_id in versions:
            if await self._file_authorized(
                session, subject, version_id, request_id,
            ) is None:
                return False
        sot_chunk_ids = set(chunk_ids) - file_chunk_ids
        if not sot_chunk_ids:
            return len(file_chunk_ids) == len(set(chunk_ids))
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
            "chunk_ids": list(sot_chunk_ids),
        })).mappings().all()
        metadata = [dict(row) for row in rows]
        return (
            len(metadata) + len(file_chunk_ids) == len(set(chunk_ids))
            and set(self._allowed(subject, metadata, request_id)) == sot_chunk_ids
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
        query_definition_record_keys: tuple[str, ...] | None = None,
        query_profile_record_keys: tuple[str, ...] | None = None,
        query_collection_record_keys: tuple[str, ...] | None = None,
        ranking_query: str | None = None,
        support_queries: tuple[str, ...] = (),
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
                ranking_query=ranking_query,
                support_queries=support_queries,
            )
        query_profile = profile_query(
            ranking_query or query,
            entities=query_entities,
            intent=query_intent,
            definition_record_keys=(
                () if filters.version_id is not None
                else query_definition_record_keys
            ),
            profile_record_keys=(
                () if filters.version_id is not None
                else query_profile_record_keys
            ),
            collection_record_keys=(
                () if filters.version_id is not None
                else query_collection_record_keys
            ),
        )
        # Query embedding is independent of metadata authorization. Start it
        # now and overlap provider latency with the bounded policy-only scan;
        # answer content is still loaded strictly after ACL admission.
        embedding_task = asyncio.create_task(
            self._query_vector(" ".join(query_profile.terms)),
        )
        embedding_task.add_done_callback(self._consume_background_result)
        metadata: list[dict[str, Any]] = []
        allowed_ids: list[uuid.UUID] = []
        allowed_id_set: set[uuid.UUID] = set()
        priority_allowed_ids: set[uuid.UUID] = set()
        priority_record_keys = tuple(dict.fromkeys((
            *(query_definition_record_keys or ()),
            *(query_profile_record_keys or ()),
            *(query_collection_record_keys or ()),
        )))
        if priority_record_keys:
            # Authority-bound records are admitted through a separate metadata-
            # only lane before ordinary candidate sampling.  This keeps ACL
            # evaluation ahead of content loading while preventing a verified
            # definition/catalog record from becoming unreachable merely because
            # its stable chunk key sorts after the global candidate cap.
            priority_page = await self._metadata(
                subject,
                filters,
                page_limit=self.settings.rag_metadata_scan_limit,
                record_keys=priority_record_keys,
            )
            self.trace.metadata_rows += len(priority_page)
            self.trace.priority_metadata_rows = len(priority_page)
            priority_allowed_ids = set(self._allowed(
                subject,
                priority_page,
                request_id,
            ))
            for row in priority_page:
                chunk_id = row["chunk_id"]
                if (
                    chunk_id in priority_allowed_ids
                    and chunk_id not in allowed_id_set
                ):
                    metadata.append(row)
                    allowed_ids.append(chunk_id)
                    allowed_id_set.add(chunk_id)
            self.trace.priority_policy_allowed = len(allowed_ids)

        # Scan policy metadata across the bounded corpus window before semantic
        # selection.  Stopping after the first N allowed chunk keys made search
        # depend on arbitrary storage order: a highly relevant method/system
        # record at position 201 was invisible even though the final semantic
        # budget was only 200.  Metadata carries no display text; content is
        # loaded below only for the best bounded semantic candidates plus
        # separately authorized authority bindings.
        cursor: str | None = None
        scanned = 0
        deadline = (
            time.monotonic() + self.settings.rag_retrieval_timeout_ms / 1000
        )
        while scanned < self.settings.rag_metadata_scan_limit:
            page_limit = min(
                self.settings.rag_metadata_page_size,
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
                if (
                    row["chunk_id"] in page_allowed_ids
                    and row["chunk_id"] not in allowed_id_set
                ):
                    metadata.append(row)
                    allowed_ids.append(row["chunk_id"])
                    allowed_id_set.add(row["chunk_id"])
            cursor = str(page[-1]["chunk_key"])
            if len(page) < page_limit:
                break
            if time.monotonic() >= deadline:
                raise RetrievalError("retrieval_budget_exceeded")
        self.trace.policy_allowed = len(allowed_ids)
        if not allowed_ids:
            embedding_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await embedding_task
            if filters.source_key is None:
                return await self._search_enterprise_files(
                    subject,
                    query,
                    normalized,
                    filters=filters,
                    request_id=request_id,
                    top_k=top_k,
                    query_entities=query_entities,
                    query_intent=query_intent,
                    ranking_query=ranking_query,
                    support_queries=support_queries,
                )
            return []
        # TIP-014RE: the vector arm embeds the RANKING profile (the user's
        # original wording), not the expanded recall soup. Lexical recall
        # still benefits from planner expansions, but concatenating them
        # into the embedded text diluted the question's semantics until the
        # oracle chunk fell under the calibrated bridge floor (observed
        # live: the company-definition dossier crowded out "tech stack").
        # This also keeps the runtime embedding basis identical to the
        # calibration harness that pre-committed the floor.
        query_vector = await embedding_task
        self.trace.content_queries += 1
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                WITH scored AS (
                  SELECT c.chunk_id,c.chunk_key,c.record_id,c.generation_id,
                    c.display_text,c.classification,c.record_key,
                    c.record_version_id,c.evidence_key,c.record_checksum,
                    c.evidence_checksum,c.source_key,c.source_revision,
                    c.provenance_level,c.verification_state,c.freshness_state,
                    c.source_label,c.locator,
                    ts_rank_cd(
                      c.lexical,to_tsquery('simple',:lexquery)
                    ) lexical_score,
                    greatest(
                      0,1-(c.embedding <=> CAST(:embedding AS vector))
                    ) vector_score,
                    row_number() OVER (
                      ORDER BY ts_rank_cd(
                        c.lexical,to_tsquery('simple',:lexquery)
                      ) DESC,c.chunk_key
                    ) lex_rank,
                    row_number() OVER (
                      ORDER BY greatest(
                        0,1-(c.embedding <=> CAST(:embedding AS vector))
                      ) DESC,c.chunk_key
                    ) vector_rank,
                    c.chunk_id=ANY(CAST(:priority_ids AS uuid[])) is_priority
                  FROM chunks c
                  JOIN active_search_generations ag
                    ON ag.generation_id=c.generation_id
                  JOIN search_generations g ON g.generation_id=ag.generation_id
                    AND g.lifecycle='active'
                  WHERE c.chunk_id=ANY(CAST(:allowed_ids AS uuid[]))
                    AND c.lifecycle='active'
                ), normal AS (
                  SELECT * FROM scored
                  WHERE NOT is_priority
                    AND (
                      lexical_score>0
                      OR vector_score>=:min_vector_score
                    )
                  ORDER BY (
                    1.0/(60+lex_rank)
                    + 1.0/(60+vector_rank)
                    + least(lexical_score,1.0)*0.1
                  ) DESC,chunk_key
                  LIMIT :candidate_limit
                ), selected AS (
                  SELECT * FROM scored WHERE is_priority
                  UNION ALL
                  SELECT * FROM normal
                )
                SELECT * FROM selected ORDER BY chunk_key
            """), {
                "lexquery": lexquery,
                "embedding": (
                    json.dumps(query_vector) if query_vector is not None
                    else None
                ),
                "allowed_ids": allowed_ids,
                "priority_ids": list(priority_allowed_ids),
                "min_vector_score": self.settings.rag_min_vector_score,
                "candidate_limit": self.settings.rag_candidate_limit,
            })).mappings().all()
        content = [dict(row) for row in rows]
        self.trace.loaded_chunk_ids = [row["chunk_id"] for row in content]
        ranked: list[tuple[float, dict[str, Any]]] = []
        metadata_by_id = {row["chunk_id"]: row for row in metadata}
        for row in content:
            if (
                float(row["lexical_score"]) <= 0
                and float(row["vector_score"])
                < self.settings.rag_min_vector_score
                and row["chunk_id"] not in priority_allowed_ids
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
                1.0 / (60 + int(row["lex_rank"]))
                + 1.0 / (60 + int(row["vector_rank"]))
                + min(float(row["lexical_score"]), 1.0) * 0.1
            )
            fusion = candidate_relevance_score(
                query_profile,
                text=str(row["display_text"]),
                record_key=str(row["record_key"]),
                base_score=base_fusion,
                vector_score=float(row["vector_score"]),
                min_vector_score=self.settings.rag_min_vector_score,
                support_queries=support_queries,
                semantic_floor=self._semantic_floor,
                allow_unbound_definition=filters.source_key is not None,
            )
            if fusion is not None:
                ranked.append((fusion, row))
        ranked.sort(key=lambda item: (-item[0], str(item[1]["chunk_key"])))
        base_limit = min(
            top_k or self.settings.rag_top_k,
            self.settings.rag_answer_candidate_k,
        )
        # Authority bindings are a retrieval contract, not merely extra recall
        # candidates. Reserve one best eligible chunk per bound record (catalog
        # anchors first, then entity definitions), then fill any remaining slots
        # by semantic rank. Without this stable reservation, ordinary high-score
        # chunks can still evict a required member definition after it survives
        # the metadata cap, producing a complete list with missing or unrelated
        # attributes. Only rows that already passed ACL, DLP and relevance are
        # eligible here; a denied or stale mapping is never forced into output.
        priority_order = tuple(dict.fromkeys((
            *(query_collection_record_keys or ()),
            *(query_definition_record_keys or ()),
            *(query_profile_record_keys or ()),
        )))
        ordered_ranked: list[tuple[float, dict[str, Any]]] = []
        reserved_chunk_ids: set[uuid.UUID] = set()
        for record_key in priority_order:
            match = next(
                (
                    item
                    for item in ranked
                    if str(item[1]["record_key"]) == record_key
                    and item[1]["chunk_id"] not in reserved_chunk_ids
                ),
                None,
            )
            if match is None:
                continue
            ordered_ranked.append(match)
            reserved_chunk_ids.add(match[1]["chunk_id"])
        self.trace.priority_selected = len(ordered_ranked)
        # Keep the low, cost-efficient evidence budget for ordinary questions,
        # but never let that generic budget truncate an authorized ontology
        # contract. Expansion is query-scoped, bounded independently, and based
        # only on priority rows that already survived ACL, DLP and relevance.
        # This prevents a 13-record profile or catalog from deterministically
        # losing its final governed facet while leaving simple asks unchanged.
        limit = max(
            base_limit,
            min(
                len(ordered_ranked),
                self.settings.rag_authority_candidate_k,
            ),
        )
        ordered_ranked.extend(
            item
            for item in ranked
            if item[1]["chunk_id"] not in reserved_chunk_ids
        )
        output: list[RetrievalHit] = []

        def _append_hit(fusion: float, row: dict[str, Any]) -> None:
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
                snippet=str(row["display_text"]),
                lexical_score=float(row["lexical_score"]),
                vector_score=float(row["vector_score"]),
                fusion_score=fusion,
                classification=row["classification"],
                citation=citation,
            ))

        used_bytes = 0
        for fusion, row in ordered_ranked:
            used_bytes += len(str(row["display_text"]).encode())
            if used_bytes > self.settings.rag_evidence_max_bytes:
                break
            _append_hit(fusion, row)
            if len(output) >= limit:
                break
        if filters.source_key is None:
            file_hits = await self._search_enterprise_files(
                subject,
                query,
                normalized,
                filters=filters,
                request_id=request_id,
                top_k=top_k,
                query_entities=query_entities,
                query_intent=query_intent,
                ranking_query=ranking_query,
                support_queries=support_queries,
            )
            return self._merge_enterprise_hits(
                output,
                file_hits,
                limit=limit,
                priority_record_keys=priority_order,
                query_intent=query_intent,
                semantic_floor=self._semantic_floor,
            )
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
