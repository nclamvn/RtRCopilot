"""Content-free provenance for build-bound enterprise evaluations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.db.engine import session_factory
from rtr_copilot.rag.ontology import load_runtime_ontology


@dataclass(frozen=True)
class EvaluationProvenance:
    database_digest: str
    ontology_digest: str
    schema_revision: str
    active_record_count: int
    active_generation_count: int
    active_chunk_count: int


def retrieval_snapshot_digest(
    *,
    schema_revision: str,
    records: list[dict[str, Any]],
    generations: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> str:
    """Digest only deterministic retrieval and authorization state."""
    payload = {
        "schema_revision": schema_revision,
        "records": records,
        "generations": generations,
        "chunks": chunks,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def load_evaluation_provenance(
    factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    ontology_path: Path | None = None,
) -> EvaluationProvenance:
    """Snapshot the exact active record/index/ontology basis used for answers."""
    runtime_factory = factory or session_factory()
    async with runtime_factory() as session:
        # All database components must come from one MVCC snapshot. Without
        # this, PostgreSQL READ COMMITTED could observe a different state for
        # records, generations and chunks if curation changes concurrently.
        await session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        schema_revision = str(
            await session.scalar(text("SELECT version_num FROM alembic_version"))
            or ""
        )
        if not schema_revision:
            raise ValueError("evaluation_provenance_schema_revision_missing")

        record_rows = (
            await session.execute(text("""
                SELECT r.source_key,r.record_key,rv.content_sha256,
                  r.classification,r.owner_subject_id::text AS owner_subject_id,
                  r.department_id::text AS department_id,
                  r.project_id::text AS project_id,
                  rv.provenance_level,rv.verification_state,rv.freshness_state
                FROM records r
                JOIN record_versions rv ON rv.version_id=r.current_version_id
                WHERE r.lifecycle='active' AND rv.lifecycle='active'
                ORDER BY r.source_key,r.record_key
            """))
        ).mappings().all()
        generation_rows = (
            await session.execute(text("""
                SELECT sg.source_key,sg.source_revision,sg.index_fingerprint,
                  sg.embedding_model,sg.embedding_version,sg.embedding_dimension,
                  sg.chunker_version
                FROM active_search_generations ag
                JOIN search_generations sg ON sg.generation_id=ag.generation_id
                WHERE sg.lifecycle='active'
                ORDER BY sg.source_key,sg.source_revision,sg.index_fingerprint
            """))
        ).mappings().all()
        chunk_rows = (
            await session.execute(text("""
                SELECT sg.index_fingerprint,c.source_key,c.record_key,c.ordinal,
                  c.text_sha256,c.record_checksum,c.evidence_checksum,
                  c.chunking_fingerprint,
                  encode(digest(c.embedding::text,'sha256'),'hex')
                    AS embedding_sha256,
                  c.evidence_key,c.locator::text AS locator,c.source_label,
                  c.classification,
                  c.owner_subject_id::text AS owner_subject_id,
                  c.department_id::text AS department_id,
                  c.project_id::text AS project_id,
                  c.provenance_level,c.verification_state,c.freshness_state
                FROM active_search_generations ag
                JOIN search_generations sg ON sg.generation_id=ag.generation_id
                JOIN chunks c ON c.generation_id=sg.generation_id
                WHERE sg.lifecycle='active' AND c.lifecycle='active'
                ORDER BY sg.source_key,c.record_key,c.ordinal,c.chunk_key
            """))
        ).mappings().all()

    records = [dict(row) for row in record_rows]
    generations = [dict(row) for row in generation_rows]
    chunks = [dict(row) for row in chunk_rows]
    ontology = await load_runtime_ontology(
        runtime_factory,
        fallback_path=ontology_path,
    )
    return EvaluationProvenance(
        database_digest=retrieval_snapshot_digest(
            schema_revision=schema_revision,
            records=records,
            generations=generations,
            chunks=chunks,
        ),
        ontology_digest=ontology.digest,
        schema_revision=schema_revision,
        active_record_count=len(records),
        active_generation_count=len(generations),
        active_chunk_count=len(chunks),
    )
