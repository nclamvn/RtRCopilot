import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.config import Settings, get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.rag.adapters import build_embedding_adapter, normalize_query
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.sot.package import canonical_json, sha256_bytes

CHUNKER_VERSION = "rtr-evidence-chunker/1"
PIPELINE_VERSION = "rtr-reindex/1"
BOUNDARY_RE = re.compile(r"\n{2,}|(?<=[.!?])\s+")


class ReindexError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ChunkCandidate:
    chunk_id: uuid.UUID
    chunk_key: str
    package_id: uuid.UUID
    record_id: uuid.UUID
    record_version_id: uuid.UUID
    evidence_span_id: uuid.UUID | None
    record_key: str
    evidence_key: str | None
    source_key: str
    source_revision: int
    classification: str
    owner_subject_id: uuid.UUID
    department_id: uuid.UUID | None
    project_id: uuid.UUID | None
    provenance_level: str
    verification_state: str
    freshness_state: str
    display_text: str
    normalized_text: str
    text_sha256: str
    locator: dict[str, Any]
    source_label: str
    record_checksum: str
    evidence_checksum: str | None
    ordinal: int
    chunking_fingerprint: str
    embedding: list[float]


def stable_split(value: str, *, maximum: int, overlap: int) -> list[str]:
    value = " ".join(value.split())
    if len(value) <= maximum:
        return [value] if value else []
    units = [item.strip() for item in BOUNDARY_RE.split(value) if item.strip()]
    chunks: list[str] = []
    current = ""
    for unit in units:
        remaining = unit
        while len(remaining) > maximum:
            prefix = remaining[:maximum]
            cut = prefix.rfind(" ")
            cut = cut if cut >= maximum // 2 else maximum
            if current:
                chunks.append(current)
                current = ""
            chunks.append(remaining[:cut].strip())
            remaining = remaining[max(1, cut - overlap):].strip()
        candidate = f"{current} {remaining}".strip()
        if len(candidate) <= maximum:
            current = candidate
        else:
            chunks.append(current)
            prefix = current[-overlap:] if overlap else ""
            current = f"{prefix} {remaining}".strip()
    if current:
        chunks.append(current)
    return chunks


class ReindexService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.uow = UnitOfWork(factory)
        self.embedding = build_embedding_adapter(self.settings)
        self.index_dlp = ProviderPolicy(mode="local")

    async def pending_outbox_id(self) -> uuid.UUID | None:
        async with self.uow.factory() as session:
            value = await session.scalar(text("""
                SELECT outbox_id FROM sot_reindex_outbox
                WHERE status IN ('pending','dispatching')
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
            """))
        return uuid.UUID(str(value)) if value else None

    async def process_next(self) -> uuid.UUID | None:
        outbox_id = await self.pending_outbox_id()
        if outbox_id is None:
            return None
        await self.process(outbox_id)
        return outbox_id

    async def _load_source(
        self,
        outbox_id: uuid.UUID,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        async with self.uow.factory() as session:
            outbox = (await session.execute(text("""
                SELECT o.outbox_id,o.run_id,o.source_key,o.revision,o.status,
                  ar.package_id,ar.payload_sha256
                FROM sot_reindex_outbox o
                JOIN sot_active_revisions ar ON ar.source_key=o.source_key
                  AND ar.activated_run_id=o.run_id AND ar.revision=o.revision
                JOIN sot_packages p ON p.package_id=ar.package_id
                  AND p.lifecycle='active'
                WHERE o.outbox_id=:outbox_id
            """), {"outbox_id": outbox_id})).mappings().one_or_none()
            if outbox is None:
                raise ReindexError("outbox_not_current_active_revision")
            rows = (await session.execute(text("""
                SELECT r.record_id,r.record_key,rv.version_id,rv.package_id,
                  rv.owner_subject_id,rv.classification,rv.department_id,rv.project_id,
                  rv.searchable_text,rv.provenance_level,rv.verification_state,
                  rv.freshness_state,rv.content_sha256,
                  e.span_id,e.evidence_key,e.normalized_text AS evidence_text,
                  e.locator,e.source_label,e.evidence_sha256
                FROM records r
                JOIN record_versions rv ON rv.version_id=r.current_version_id
                LEFT JOIN evidence_spans e ON e.record_version_id=rv.version_id
                  AND e.lifecycle='active'
                WHERE rv.package_id=:package_id AND r.lifecycle='active'
                  AND rv.lifecycle='active'
                ORDER BY r.record_key,e.evidence_key
            """), {"package_id": outbox["package_id"]})).mappings().all()
        return dict(outbox), [dict(row) for row in rows]

    def _candidates(
        self,
        outbox: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> list[ChunkCandidate]:
        candidates: list[ChunkCandidate] = []
        # TIP-014RE: chunk texts are embedded in one batched pass AFTER the
        # loop (provider adapters page requests; the offline hash embeds
        # per-text). Candidates are built with an empty vector and completed
        # below — a length mismatch is a hard error, never a silent skip.
        part_texts: list[str] = []
        # TIP-014RE: chunk identity must be generation-space distinct. Before
        # real embeddings, a source revision was only ever indexed once, so
        # (revision × chunking_fingerprint) sufficed. Re-embedding the SAME
        # revision under a different adapter creates a NEW generation whose
        # candidates would otherwise collide with the retained old-generation
        # rows on the global UNIQUE(chunk_key) / chunk_id — ON CONFLICT DO
        # NOTHING would skip every insert and the generation_count_mismatch
        # integrity gate fires (observed live, 09/08). Suffixing a digest of
        # the embedding identity keeps identical-adapter reruns idempotent
        # (same key → same generation → early no-op) while distinct adapters
        # produce disjoint chunk rows.
        embedding_fp = sha256_bytes(canonical_json({
            "model": self.embedding.model,
            "version": self.embedding.version,
            "dimension": self.embedding.dimension,
        }))[:12]
        for row in rows:
            base = str(row["evidence_text"] or row["searchable_text"]).strip()
            if not base:
                continue
            if not self.index_dlp.inspect(
                base,
                classification=str(row["classification"]),
            ).allow:
                continue
            parts = stable_split(
                base,
                maximum=self.settings.rag_chunk_max_chars,
                overlap=self.settings.rag_chunk_overlap_chars,
            )
            for ordinal, part in enumerate(parts, 1):
                identity = {
                    "version_id": str(row["version_id"]),
                    "evidence_span_id": (
                        str(row["span_id"]) if row["span_id"] else None
                    ),
                    "record_checksum": str(row["content_sha256"]),
                    "evidence_checksum": (
                        str(row["evidence_sha256"]) if row["evidence_sha256"] else None
                    ),
                    "locator": dict(row["locator"] or {}),
                    "ordinal": ordinal,
                    "chunker": CHUNKER_VERSION,
                }
                chunking_fingerprint = sha256_bytes(canonical_json(identity))
                chunk_key = (
                    f"{outbox['source_key']}:{outbox['revision']}:"
                    f"{row['record_key']}:{chunking_fingerprint}:{embedding_fp}"
                )
                chunk_id = uuid.uuid5(uuid.NAMESPACE_URL, f"rtr-chunk:{chunk_key}")
                candidates.append(ChunkCandidate(
                    chunk_id=chunk_id,
                    chunk_key=chunk_key,
                    package_id=row["package_id"],
                    record_id=row["record_id"],
                    record_version_id=row["version_id"],
                    evidence_span_id=row["span_id"],
                    record_key=str(row["record_key"]),
                    evidence_key=row["evidence_key"],
                    source_key=str(outbox["source_key"]),
                    source_revision=int(outbox["revision"]),
                    classification=str(row["classification"]),
                    owner_subject_id=row["owner_subject_id"],
                    department_id=row["department_id"],
                    project_id=row["project_id"],
                    provenance_level=str(row["provenance_level"]),
                    verification_state=str(row["verification_state"]),
                    freshness_state=str(row["freshness_state"]),
                    display_text=part,
                    normalized_text=normalize_query(part),
                    text_sha256=hashlib.sha256(
                        normalize_query(part).encode(),
                    ).hexdigest(),
                    locator=dict(row["locator"] or {}),
                    source_label=str(row["source_label"] or row["record_key"]),
                    record_checksum=str(row["content_sha256"]),
                    evidence_checksum=(
                        str(row["evidence_sha256"]) if row["evidence_sha256"] else None
                    ),
                    ordinal=ordinal,
                    chunking_fingerprint=chunking_fingerprint,
                    embedding=[],
                ))
                part_texts.append(part)
        vectors = self.embedding.embed_batch(part_texts)
        return [
            replace(candidate, embedding=vector)
            for candidate, vector in zip(candidates, vectors, strict=True)
        ]

    async def process(
        self,
        outbox_id: uuid.UUID,
        *,
        inject_failure: str | None = None,
    ) -> uuid.UUID:
        outbox, rows = await self._load_source(outbox_id)
        candidates = self._candidates(outbox, rows)
        fingerprint = sha256_bytes(canonical_json({
            "pipeline": PIPELINE_VERSION,
            "chunker": CHUNKER_VERSION,
            "embedding": {
                "model": self.embedding.model,
                "version": self.embedding.version,
                "dimension": self.embedding.dimension,
            },
            "chunks": [
                {
                    "key": item.chunk_key,
                    "sha256": item.text_sha256,
                    "security": [
                        item.classification,
                        str(item.owner_subject_id),
                        str(item.department_id),
                        str(item.project_id),
                    ],
                }
                for item in candidates
            ],
        }))
        generation_id = uuid.uuid5(outbox_id, fingerprint)
        job_id = uuid.uuid5(outbox_id, PIPELINE_VERSION)
        async with self.uow.transaction() as session:
            current = await session.scalar(text("""
                SELECT generation_id FROM active_search_generations
                WHERE source_key=:source_key
            """), {"source_key": outbox["source_key"]})
            if current == generation_id:
                return generation_id
            await session.execute(text("""
                INSERT INTO search_generations(
                  generation_id,source_key,source_revision,publish_run_id,package_id,
                  index_fingerprint,embedding_model,embedding_version,
                  embedding_dimension,chunker_version,lifecycle
                ) VALUES (
                  :generation_id,:source_key,:revision,:run_id,:package_id,
                  :fingerprint,:model,:model_version,:dimension,:chunker,'building'
                ) ON CONFLICT(generation_id) DO NOTHING
            """), {
                "generation_id": generation_id,
                "source_key": outbox["source_key"],
                "revision": outbox["revision"],
                "run_id": outbox["run_id"],
                "package_id": outbox["package_id"],
                "fingerprint": fingerprint,
                "model": self.embedding.model,
                "model_version": self.embedding.version,
                "dimension": self.embedding.dimension,
                "chunker": CHUNKER_VERSION,
            })
            await session.execute(text("""
                INSERT INTO index_jobs(
                  job_id,outbox_id,generation_id,source_key,source_revision,
                  publish_run_id,status,pipeline_version,model_version,request_id
                ) VALUES (
                  :job_id,:outbox_id,:generation_id,:source_key,:revision,
                  :run_id,'running',:pipeline,:model_version,:request_id
                ) ON CONFLICT(outbox_id) DO UPDATE SET status='running',updated_at=now()
            """), {
                "job_id": job_id,
                "outbox_id": outbox_id,
                "generation_id": generation_id,
                "source_key": outbox["source_key"],
                "revision": outbox["revision"],
                "run_id": outbox["run_id"],
                "pipeline": PIPELINE_VERSION,
                "model_version": self.embedding.version,
                "request_id": f"reindex:{outbox['run_id']}",
            })
        try:
            async with self.uow.transaction() as session:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:source_key))"),
                    {"source_key": outbox["source_key"]},
                )
                active = (await session.execute(text("""
                    SELECT ar.package_id,ar.revision,ar.activated_run_id
                    FROM sot_active_revisions ar
                    WHERE ar.source_key=:source_key FOR UPDATE
                """), {"source_key": outbox["source_key"]})).mappings().one_or_none()
                if (
                    active is None
                    or active["package_id"] != outbox["package_id"]
                    or int(active["revision"]) != int(outbox["revision"])
                    or active["activated_run_id"] != outbox["run_id"]
                ):
                    raise ReindexError("active_revision_changed")
                pointer = await session.scalar(text("""
                    SELECT generation_id FROM active_search_generations
                    WHERE source_key=:source_key FOR UPDATE
                """), {"source_key": outbox["source_key"]})
                if pointer == generation_id:
                    return generation_id
                for item in candidates:
                    await session.execute(text("""
                        INSERT INTO chunks(
                          chunk_id,chunk_key,generation_id,package_id,record_id,
                          record_version_id,evidence_span_id,record_key,evidence_key,
                          source_key,source_revision,source_zone,classification,
                          owner_subject_id,department_id,project_id,provenance_level,
                          verification_state,freshness_state,display_text,
                          normalized_text,text_sha256,locator,source_label,
                          record_checksum,evidence_checksum,ordinal,
                          chunking_fingerprint,embedding,lifecycle
                        ) VALUES (
                          :chunk_id,:chunk_key,:generation_id,:package_id,:record_id,
                          :version_id,:span_id,:record_key,:evidence_key,
                          :source_key,:revision,'sot',:classification,
                          :owner,:department,:project,:provenance,:verification,
                          :freshness,:display_text,:content,:text_sha,
                          CAST(:locator AS jsonb),:label,
                          :record_checksum,:evidence_checksum,:ordinal,:chunking,
                          CAST(:embedding AS vector),'active'
                        ) ON CONFLICT(chunk_id) DO NOTHING
                    """), {
                        "chunk_id": item.chunk_id,
                        "chunk_key": item.chunk_key,
                        "generation_id": generation_id,
                        "package_id": item.package_id,
                        "record_id": item.record_id,
                        "version_id": item.record_version_id,
                        "span_id": item.evidence_span_id,
                        "record_key": item.record_key,
                        "evidence_key": item.evidence_key,
                        "source_key": item.source_key,
                        "revision": item.source_revision,
                        "classification": item.classification,
                        "owner": item.owner_subject_id,
                        "department": item.department_id,
                        "project": item.project_id,
                        "provenance": item.provenance_level,
                        "verification": item.verification_state,
                        "freshness": item.freshness_state,
                        "display_text": item.display_text,
                        "content": item.normalized_text,
                        "text_sha": item.text_sha256,
                        "locator": json.dumps(item.locator),
                        "label": item.source_label,
                        "record_checksum": item.record_checksum,
                        "evidence_checksum": item.evidence_checksum,
                        "ordinal": item.ordinal,
                        "chunking": item.chunking_fingerprint,
                        "embedding": json.dumps(item.embedding),
                    })
                if inject_failure == "after_chunks":
                    raise ReindexError("injected_failure")
                count = await session.scalar(text("""
                    SELECT count(*) FROM chunks WHERE generation_id=:generation_id
                """), {"generation_id": generation_id})
                if int(count or 0) != len(candidates):
                    raise ReindexError("generation_count_mismatch")
                await session.execute(text("""
                    UPDATE search_generations SET lifecycle='superseded'
                    WHERE source_key=:source_key AND lifecycle='active'
                """), {"source_key": outbox["source_key"]})
                await session.execute(text("""
                    UPDATE search_generations SET lifecycle='active',
                      chunk_count=:count,document_count=:documents,finished_at=now()
                    WHERE generation_id=:generation_id
                """), {
                    "generation_id": generation_id,
                    "count": len(candidates),
                    "documents": len({item.record_id for item in candidates}),
                })
                await session.execute(text("""
                    INSERT INTO active_search_generations(
                      source_key,generation_id,source_revision,index_fingerprint
                    ) VALUES (:source_key,:generation_id,:revision,:fingerprint)
                    ON CONFLICT(source_key) DO UPDATE SET
                      generation_id=excluded.generation_id,
                      source_revision=excluded.source_revision,
                      index_fingerprint=excluded.index_fingerprint,
                      activated_at=now()
                """), {
                    "source_key": outbox["source_key"],
                    "generation_id": generation_id,
                    "revision": outbox["revision"],
                    "fingerprint": fingerprint,
                })
                await session.execute(text("""
                    UPDATE index_jobs SET status='succeeded',
                      progress=CAST(:progress AS jsonb),finished_at=now(),updated_at=now()
                    WHERE job_id=:job_id
                """), {
                    "job_id": job_id,
                    "progress": json.dumps({"chunks": len(candidates)}),
                })
                await session.execute(text("""
                    UPDATE sot_reindex_outbox SET status='dispatched',dispatched_at=now()
                    WHERE outbox_id=:outbox_id
                """), {"outbox_id": outbox_id})
        except ReindexError as error:
            fingerprint_error = hashlib.sha256(error.code.encode()).hexdigest()
            async with self.uow.transaction() as session:
                await session.execute(text("""
                    UPDATE search_generations SET lifecycle='failed',
                      failure_code=:code,failure_fingerprint=:fingerprint,finished_at=now()
                    WHERE generation_id=:generation_id AND lifecycle='building'
                """), {
                    "generation_id": generation_id,
                    "code": error.code,
                    "fingerprint": fingerprint_error,
                })
                await session.execute(text("""
                    UPDATE index_jobs SET status='failed',failure_code=:code,
                      failure_fingerprint=:fingerprint,finished_at=now(),updated_at=now()
                    WHERE job_id=:job_id
                """), {
                    "job_id": job_id,
                    "code": error.code,
                    "fingerprint": fingerprint_error,
                })
            raise
        return generation_id
