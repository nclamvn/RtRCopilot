"""Create/check a deterministic database-backed enterprise corpus snapshot."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.enterprise.models import digest_of

CANONICAL_SOT_SOURCES = (
    "rtr.boms",
    "rtr.capabilities",
    "rtr.derived_costs",
    "rtr.l3_facts",
    "rtr.prices",
    "rtr.specs",
)


async def _scalar(session: Any, query: str, **parameters: Any) -> int:
    return int(await session.scalar(text(query), parameters) or 0)


async def measurements() -> dict[str, Any]:
    async with UnitOfWork().factory() as session:
        canonical_records = await _scalar(session, """
            SELECT count(*) FROM records r
            JOIN record_versions rv ON rv.version_id=r.current_version_id
            WHERE r.lifecycle='active'
              AND rv.lifecycle='active'
              AND r.source_key=ANY(CAST(:sources AS text[]))
        """, sources=list(CANONICAL_SOT_SOURCES))
        noncanonical_records = await _scalar(session, """
            SELECT count(*) FROM records r
            JOIN record_versions rv ON rv.version_id=r.current_version_id
            WHERE r.lifecycle='active'
              AND rv.lifecycle='active'
              AND NOT (r.source_key=ANY(CAST(:sources AS text[])))
        """, sources=list(CANONICAL_SOT_SOURCES))
        sot_chunks = await _scalar(session, """
            SELECT count(*) FROM chunks c
            JOIN active_search_generations ag ON ag.generation_id=c.generation_id
            WHERE c.lifecycle='active'
              AND c.source_key=ANY(CAST(:sources AS text[]))
        """, sources=list(CANONICAL_SOT_SOURCES))
        canonical_rows = (await session.execute(text("""
            SELECT r.source_key,count(*)::int AS records
            FROM records r
            JOIN record_versions rv ON rv.version_id=r.current_version_id
            WHERE r.lifecycle='active'
              AND rv.lifecycle='active'
              AND r.source_key=ANY(CAST(:sources AS text[]))
            GROUP BY r.source_key ORDER BY r.source_key
        """), {"sources": list(CANONICAL_SOT_SOURCES)})).mappings().all()
        enterprise_documents = await _scalar(session, """
            SELECT count(DISTINCT d.document_id)
            FROM sources s
            JOIN documents d ON d.source_id=s.source_id
            JOIN document_versions dv ON dv.version_id=d.current_version_id
            JOIN resources r ON r.resource_id=dv.version_id
            WHERE s.metadata->'enterprise_ask'->>'state'='enterprise_approved'
              AND dv.viewer_state='ready' AND r.lifecycle_state='active'
        """)
        enterprise_file_chunks = await _scalar(session, """
            SELECT count(fc.file_chunk_id)
            FROM sources s
            JOIN documents d ON d.source_id=s.source_id
            JOIN document_versions dv ON dv.version_id=d.current_version_id
            JOIN resources r ON r.resource_id=dv.version_id
            JOIN file_chunks fc ON fc.document_version_id=dv.version_id
              AND fc.lifecycle='active'
            WHERE s.metadata->'enterprise_ask'->>'state'='enterprise_approved'
              AND dv.viewer_state='ready' AND r.lifecycle_state='active'
        """)
        enterprise_format_rows = (await session.execute(text("""
            SELECT lower(coalesce(
                     substring(dv.original_filename from '\\.([^.]+)$'),
                     'unknown'
                   )) AS extension,
                   count(DISTINCT d.document_id)::int AS documents
            FROM sources s
            JOIN documents d ON d.source_id=s.source_id
            JOIN document_versions dv ON dv.version_id=d.current_version_id
            JOIN resources r ON r.resource_id=dv.version_id
            WHERE s.metadata->'enterprise_ask'->>'state'='enterprise_approved'
              AND dv.viewer_state='ready' AND r.lifecycle_state='active'
            GROUP BY lower(coalesce(
              substring(dv.original_filename from '\\.([^.]+)$'),
              'unknown'
            )) ORDER BY 1
        """))).mappings().all()
        enterprise_source_rows = (await session.execute(text("""
            SELECT s.name,r.classification,
                   count(DISTINCT d.document_id)::int AS documents,
                   count(fc.file_chunk_id)::int AS chunks
            FROM sources s
            JOIN documents d ON d.source_id=s.source_id
            JOIN document_versions dv ON dv.version_id=d.current_version_id
            JOIN resources r ON r.resource_id=dv.version_id
            LEFT JOIN file_chunks fc ON fc.document_version_id=dv.version_id
              AND fc.lifecycle='active'
            WHERE s.metadata->'enterprise_ask'->>'state'='enterprise_approved'
              AND dv.viewer_state='ready' AND r.lifecycle_state='active'
            GROUP BY s.name,r.classification ORDER BY s.name,r.classification
        """))).mappings().all()
        research_rows = (await session.execute(text("""
            WITH latest AS (
              SELECT DISTINCT ON (rp.source_id) rp.package_id,rp.source_id
              FROM research_packages rp
              JOIN research_sources rs ON rs.source_id=rp.source_id
              WHERE rp.import_state='imported' AND rs.lifecycle='active'
              ORDER BY rp.source_id,rp.imported_at DESC,rp.package_id DESC
            )
            SELECT rs.stable_key,count(rr.research_record_id)::int AS records
            FROM latest l
            JOIN research_sources rs ON rs.source_id=l.source_id
            JOIN research_records rr ON rr.package_id=l.package_id
            GROUP BY rs.stable_key ORDER BY rs.stable_key
        """))).mappings().all()
        tier_rows = (await session.execute(text("""
            WITH latest AS (
              SELECT DISTINCT ON (rp.source_id) rp.package_id,rp.source_id
              FROM research_packages rp
              JOIN research_sources rs ON rs.source_id=rp.source_id
              WHERE rp.import_state='imported' AND rs.lifecycle='active'
              ORDER BY rp.source_id,rp.imported_at DESC,rp.package_id DESC
            )
            SELECT rr.tier,count(*)::int AS records
            FROM latest l JOIN research_records rr ON rr.package_id=l.package_id
            GROUP BY rr.tier ORDER BY rr.tier
        """))).mappings().all()
        governance = {
            "active_domains": await _scalar(
                session, "SELECT count(*) FROM enterprise_domains WHERE state='active'",
            ),
            "active_manifests": await _scalar(
                session,
                "SELECT count(*) FROM enterprise_corpus_manifests WHERE state='active'",
            ),
            "active_ontology_revisions": await _scalar(
                session,
                "SELECT count(*) FROM enterprise_ontology_revisions WHERE state='active'",
            ),
            "active_release_attestations": await _scalar(
                session,
                "SELECT count(*) FROM enterprise_release_attestations WHERE state='active'",
            ),
        }
        document_os = {
            "approved_templates": await _scalar(
                session, "SELECT count(*) FROM templates WHERE lifecycle='approved'",
            ),
            "render_jobs": await _scalar(session, "SELECT count(*) FROM render_jobs"),
            "generated_files": await _scalar(
                session, "SELECT count(*) FROM generated_files",
            ),
            "approvals": await _scalar(session, "SELECT count(*) FROM approvals"),
            "issuances": await _scalar(
                session, "SELECT count(*) FROM document_issuances",
            ),
            "revocations": await _scalar(
                session,
                "SELECT count(*) FROM document_issuances WHERE revoked_at IS NOT NULL",
            ),
        }
        open_gaps = await _scalar(
            session,
            "SELECT count(*) FROM gaps WHERE lifecycle IN ('open','triaged','assigned')",
        )
        index_rows = (await session.execute(text("""
            SELECT DISTINCT sg.embedding_model,sg.embedding_dimension
            FROM search_generations sg
            JOIN active_search_generations ag ON ag.generation_id=sg.generation_id
            WHERE sg.lifecycle='active' ORDER BY 1,2
        """))).mappings().all()
    return {
        "canonical_sot": {
            "active_records": canonical_records,
            "active_chunks": sot_chunks,
            "source_keys": list(CANONICAL_SOT_SOURCES),
            "records_by_source": {
                str(row["source_key"]): int(row["records"])
                for row in canonical_rows
            },
        },
        "database_cleanliness": {
            "noncanonical_active_records": noncanonical_records,
            "state": "clean" if noncanonical_records == 0 else "mixed_development",
        },
        "enterprise_files": {
            "approved_documents": enterprise_documents,
            "searchable_chunks": enterprise_file_chunks,
            "documents_by_extension": {
                str(row["extension"]): int(row["documents"])
                for row in enterprise_format_rows
            },
            "sources": [
                {
                    "name": str(row["name"]),
                    "classification": str(row["classification"]),
                    "documents": int(row["documents"]),
                    "chunks": int(row["chunks"]),
                }
                for row in enterprise_source_rows
            ],
        },
        "research": {
            "active_records_by_source": {
                str(row["stable_key"]): int(row["records"]) for row in research_rows
            },
            "tier_counts": {
                str(row["tier"]): int(row["records"]) for row in tier_rows
            },
        },
        "governance": governance,
        "document_os": document_os,
        "open_knowledge_gaps": open_gaps,
        "active_sot_index_profiles": [
            {
                "model": str(row["embedding_model"]),
                "dimension": int(row["embedding_dimension"]),
            }
            for row in index_rows
        ],
    }


async def snapshot() -> dict[str, Any]:
    values = await measurements()
    # Render jobs, issuances and recorded gaps change during ordinary use. They
    # remain visible as operational observations but must not invalidate the
    # corpus release digest. Only evidence, indexes and governance are drift
    # gated.
    corpus_scope = {
        key: value
        for key, value in values.items()
        if key not in {"document_os", "open_knowledge_gaps"}
    }
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "snapshot_digest": digest_of(corpus_scope),
        "digest_scope": sorted(corpus_scope),
        "measurements": values,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = asyncio.run(snapshot())
    if args.check:
        try:
            stored = json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit("INVENTORY DRIFT · stored snapshot unavailable") from error
        if stored.get("snapshot_digest") != current["snapshot_digest"]:
            raise SystemExit(
                "INVENTORY DRIFT · database measurements differ; regenerate snapshot",
            )
        print(f"INVENTORY PASS · digest={current['snapshot_digest']}")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"INVENTORY SNAPSHOT · {args.output} · digest={current['snapshot_digest']}")


if __name__ == "__main__":
    main()
