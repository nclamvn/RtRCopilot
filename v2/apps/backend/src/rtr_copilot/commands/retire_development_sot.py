"""Retire non-canonical development SOT lineages without deleting evidence.

This is an operator-only repair for local/demo databases that accumulated SOT
packages created by automated tests.  It is deliberately conservative:

* dry-run is the default;
* apply needs an explicit approval flag and the exact dry-run fingerprint;
* production is refused;
* every target producer must be a known test/integration producer;
* mutable lineage rows are lifecycle-retired and active pointers are removed;
* immutable retrieval chunks remain byte-for-byte intact for audit/rollback;
* canonical RtR SOT and enterprise-file measurements are drift-checked in the
  same transaction.

Run this through the ``migrate`` compose service because the runtime database
role cannot delete active-pointer rows by design.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rtr_copilot.config import get_settings
from rtr_copilot.db.engine import async_dsn
from rtr_copilot.db.uow import ensure_mutation_allowed
from rtr_copilot.repositories.audit import AuditRepository

CANONICAL_SOT_SOURCES = (
    "rtr.boms",
    "rtr.capabilities",
    "rtr.derived_costs",
    "rtr.l3_facts",
    "rtr.prices",
    "rtr.specs",
)

ALLOWED_DEVELOPMENT_PRODUCERS = frozenset({
    "governance-admin-tests",
    "governance-service-tests",
    "governance-tests",
    "rtr-graduation-gate",
    "test-fixture",
    "tip011-integration",
})

ZERO_TARGET_KEYS = (
    "active_revisions",
    "active_search_pointers",
    "active_generations",
    "active_chunks",
    "active_records",
    "active_record_versions",
    "active_evidence_spans",
    "active_resources",
    "active_packages",
    "open_outbox_rows",
    "open_index_jobs",
)


class CleanupRefused(RuntimeError):
    """The database does not match the explicitly bounded cleanup contract."""


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def cleanup_fingerprint(inventory: Mapping[str, Any]) -> str:
    """Return a stable digest for the complete pre-mutation observation."""
    payload = json.dumps(
        _json_value(inventory),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_inventory(inventory: Mapping[str, Any]) -> None:
    producers = set(inventory["targets"]["producers"])
    unknown = sorted(producers - ALLOWED_DEVELOPMENT_PRODUCERS)
    if unknown:
        raise CleanupRefused(f"unapproved_target_producers:{','.join(unknown)}")
    sources = set(inventory["targets"]["source_keys"])
    overlap = sorted(sources.intersection(CANONICAL_SOT_SOURCES))
    if overlap:
        raise CleanupRefused(f"canonical_source_in_target:{','.join(overlap)}")
    missing_producer = inventory["targets"]["missing_producer_sources"]
    if missing_producer:
        raise CleanupRefused(
            "target_lineage_missing_producer:" + ",".join(missing_producer),
        )


def validate_postconditions(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    remaining = {
        key: int(after["targets"]["counts"][key])
        for key in ZERO_TARGET_KEYS
        if int(after["targets"]["counts"][key]) != 0
    }
    if remaining:
        raise CleanupRefused(f"noncanonical_active_state_remains:{remaining}")
    for section in ("canonical", "enterprise_files"):
        if before[section] != after[section]:
            raise CleanupRefused(f"protected_measurement_changed:{section}")


async def _scalar(
    session: AsyncSession,
    query: str,
    parameters: Mapping[str, Any] | None = None,
) -> int:
    return int(await session.scalar(text(query), dict(parameters or {})) or 0)


async def _rows(
    session: AsyncSession,
    query: str,
    parameters: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = (await session.execute(text(query), dict(parameters or {}))).mappings().all()
    rows = [_json_value(dict(row)) for row in result]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


async def inventory(session: AsyncSession) -> dict[str, Any]:
    params = {"canonical": list(CANONICAL_SOT_SOURCES)}
    canonical_rows = await _rows(session, """
        SELECT ar.source_key,ar.revision,ar.package_id,ar.payload_sha256,
               ar.activated_run_id,ag.generation_id,ag.index_fingerprint,
               sg.embedding_model,sg.embedding_version,sg.embedding_dimension,
               count(c.chunk_id)::int AS active_chunks
        FROM sot_active_revisions ar
        LEFT JOIN active_search_generations ag ON ag.source_key=ar.source_key
        LEFT JOIN search_generations sg ON sg.generation_id=ag.generation_id
        LEFT JOIN chunks c ON c.generation_id=ag.generation_id AND c.lifecycle='active'
        WHERE ar.source_key=ANY(CAST(:canonical AS text[]))
        GROUP BY ar.source_key,ar.revision,ar.package_id,ar.payload_sha256,
                 ar.activated_run_id,ag.generation_id,ag.index_fingerprint,
                 sg.embedding_model,sg.embedding_version,sg.embedding_dimension
        ORDER BY ar.source_key
    """, params)
    canonical_records = await _scalar(session, """
        SELECT count(*) FROM records r
        JOIN record_versions rv ON rv.version_id=r.current_version_id
        WHERE r.lifecycle='active' AND rv.lifecycle='active'
          AND r.source_key=ANY(CAST(:canonical AS text[]))
    """, params)
    canonical_chunks = await _scalar(session, """
        SELECT count(*) FROM chunks c
        JOIN active_search_generations ag ON ag.generation_id=c.generation_id
        WHERE c.lifecycle='active'
          AND c.source_key=ANY(CAST(:canonical AS text[]))
    """, params)
    enterprise_documents = await _scalar(session, """
        SELECT count(DISTINCT d.document_id)
        FROM sources s
        JOIN documents d ON d.source_id=s.source_id
        JOIN document_versions dv ON dv.version_id=d.current_version_id
        JOIN resources r ON r.resource_id=dv.version_id
        WHERE s.metadata->'enterprise_ask'->>'state'='enterprise_approved'
          AND dv.viewer_state='ready' AND r.lifecycle_state='active'
    """)
    enterprise_chunks = await _scalar(session, """
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
    target_lineage = await _rows(session, """
        WITH active_lineage AS (
          SELECT ar.source_key,ar.package_id FROM sot_active_revisions ar
          WHERE NOT (ar.source_key=ANY(CAST(:canonical AS text[])))
          UNION
          SELECT r.source_key,rv.package_id FROM records r
          LEFT JOIN record_versions rv ON rv.version_id=r.current_version_id
          WHERE r.lifecycle='active'
            AND NOT (r.source_key=ANY(CAST(:canonical AS text[])))
          UNION
          SELECT c.source_key,c.package_id FROM chunks c
          JOIN active_search_generations ag ON ag.generation_id=c.generation_id
          WHERE c.lifecycle='active'
            AND NOT (c.source_key=ANY(CAST(:canonical AS text[])))
          UNION
          SELECT sg.source_key,sg.package_id FROM search_generations sg
          WHERE sg.lifecycle='active'
            AND NOT (sg.source_key=ANY(CAST(:canonical AS text[])))
          UNION
          SELECT p.source_key,p.package_id FROM sot_packages p
          WHERE p.lifecycle='active'
            AND NOT (p.source_key=ANY(CAST(:canonical AS text[])))
        )
        SELECT al.source_key,al.package_id,p.producer,p.revision
        FROM active_lineage al
        LEFT JOIN sot_packages p ON p.package_id=al.package_id
        ORDER BY al.source_key,al.package_id
    """, params)
    target_revisions = await _rows(session, """
        SELECT ar.source_key,ar.package_id,ar.revision,ar.payload_sha256,
               ar.activated_run_id,p.producer
        FROM sot_active_revisions ar
        JOIN sot_packages p ON p.package_id=ar.package_id
        WHERE NOT (ar.source_key=ANY(CAST(:canonical AS text[])))
        ORDER BY ar.source_key
    """, params)
    target_search_pointers = await _rows(session, """
        SELECT ag.source_key,ag.generation_id,ag.source_revision,ag.index_fingerprint
        FROM active_search_generations ag
        WHERE NOT (ag.source_key=ANY(CAST(:canonical AS text[])))
        ORDER BY ag.source_key
    """, params)
    target_records = await _rows(session, """
        SELECT r.source_key,r.record_id,r.record_key,r.current_version_id,
               rv.package_id,p.producer
        FROM records r
        LEFT JOIN record_versions rv ON rv.version_id=r.current_version_id
        LEFT JOIN sot_packages p ON p.package_id=rv.package_id
        WHERE r.lifecycle='active'
          AND NOT (r.source_key=ANY(CAST(:canonical AS text[])))
        ORDER BY r.source_key,r.record_key
    """, params)
    target_generations = await _rows(session, """
        SELECT sg.source_key,sg.generation_id,sg.package_id,sg.source_revision,
               sg.index_fingerprint,sg.embedding_model,sg.embedding_version,
               sg.embedding_dimension,p.producer
        FROM search_generations sg
        JOIN sot_packages p ON p.package_id=sg.package_id
        WHERE sg.lifecycle='active'
          AND NOT (sg.source_key=ANY(CAST(:canonical AS text[])))
        ORDER BY sg.source_key,sg.generation_id
    """, params)
    count_queries = {
        "active_revisions": """
            SELECT count(*) FROM sot_active_revisions
            WHERE NOT (source_key=ANY(CAST(:canonical AS text[])))
        """,
        "active_search_pointers": """
            SELECT count(*) FROM active_search_generations
            WHERE NOT (source_key=ANY(CAST(:canonical AS text[])))
        """,
        "active_generations": """
            SELECT count(*) FROM search_generations WHERE lifecycle='active'
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """,
        "active_chunks": """
            SELECT count(*) FROM chunks c
            JOIN active_search_generations ag ON ag.generation_id=c.generation_id
            WHERE c.lifecycle='active'
              AND NOT (c.source_key=ANY(CAST(:canonical AS text[])))
        """,
        "active_records": """
            SELECT count(*) FROM records WHERE lifecycle='active'
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """,
        "active_record_versions": """
            SELECT count(*) FROM record_versions rv
            JOIN records r ON r.record_id=rv.record_id
            WHERE rv.lifecycle='active'
              AND NOT (r.source_key=ANY(CAST(:canonical AS text[])))
        """,
        "active_evidence_spans": """
            SELECT count(*) FROM evidence_spans e
            JOIN record_versions rv ON rv.version_id=e.record_version_id
            JOIN records r ON r.record_id=rv.record_id
            WHERE e.lifecycle='active'
              AND NOT (r.source_key=ANY(CAST(:canonical AS text[])))
        """,
        "active_resources": """
            SELECT count(*) FROM resources rs
            JOIN records r ON r.record_id=rs.resource_id
            WHERE rs.lifecycle_state='active'
              AND NOT (r.source_key=ANY(CAST(:canonical AS text[])))
        """,
        "active_packages": """
            SELECT count(*) FROM sot_packages WHERE lifecycle='active'
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """,
        "open_outbox_rows": """
            SELECT count(*) FROM sot_reindex_outbox
            WHERE status IN ('pending','dispatching')
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """,
        "open_index_jobs": """
            SELECT count(*) FROM index_jobs
            WHERE status IN ('pending','leased','running','retry_wait')
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """,
    }
    counts = {
        key: await _scalar(session, query, params)
        for key, query in count_queries.items()
    }
    source_keys = sorted({str(row["source_key"]) for row in target_lineage})
    producers = sorted({str(row["producer"]) for row in target_lineage if row["producer"]})
    missing = sorted({
        str(row["source_key"]) for row in target_lineage if not row["producer"]
    })
    return {
        "schema_version": 1,
        "canonical": {
            "active_source_revisions": len(canonical_rows),
            "active_records": canonical_records,
            "active_chunks": canonical_chunks,
            "sources": canonical_rows,
        },
        "enterprise_files": {
            "approved_documents": enterprise_documents,
            "active_chunks": enterprise_chunks,
        },
        "targets": {
            "source_keys": source_keys,
            "producers": producers,
            "missing_producer_sources": missing,
            "counts": counts,
            "rollback": {
                "active_revisions": target_revisions,
                "active_search_pointers": target_search_pointers,
                "active_records": target_records,
                "active_generations": target_generations,
            },
        },
    }


async def _mutate(session: AsyncSession) -> dict[str, int]:
    params = {
        "canonical": list(CANONICAL_SOT_SOURCES),
        "retirement_fingerprint": hashlib.sha256(
            b"fixture_lineage_retired",
        ).hexdigest(),
    }
    statements = (
        ("search_pointers_removed", """
            DELETE FROM active_search_generations
            WHERE NOT (source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("generations_superseded", """
            UPDATE search_generations SET lifecycle='superseded'
            WHERE lifecycle='active'
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("index_jobs_closed", """
            UPDATE index_jobs SET status='failed',updated_at=now(),finished_at=now(),
              failure_code='fixture_lineage_retired',
              failure_fingerprint=:retirement_fingerprint
            WHERE status IN ('pending','leased','running','retry_wait')
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("outbox_closed", """
            UPDATE sot_reindex_outbox SET status='dispatched',dispatched_at=now()
            WHERE status IN ('pending','dispatching')
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("evidence_superseded", """
            UPDATE evidence_spans e SET lifecycle='superseded'
            FROM record_versions rv JOIN records r ON r.record_id=rv.record_id
            WHERE e.record_version_id=rv.version_id AND e.lifecycle='active'
              AND NOT (r.source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("record_versions_superseded", """
            UPDATE record_versions rv SET lifecycle='superseded'
            FROM records r
            WHERE rv.record_id=r.record_id AND rv.lifecycle='active'
              AND NOT (r.source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("resources_superseded", """
            UPDATE resources rs SET lifecycle_state='superseded',updated_at=now()
            FROM records r
            WHERE rs.resource_id=r.record_id AND rs.lifecycle_state='active'
              AND NOT (r.source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("records_superseded", """
            UPDATE records SET lifecycle='superseded',current_version_id=NULL,
              updated_at=now()
            WHERE lifecycle='active'
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("revision_pointers_removed", """
            DELETE FROM sot_active_revisions
            WHERE NOT (source_key=ANY(CAST(:canonical AS text[])))
        """),
        ("packages_superseded", """
            UPDATE sot_packages SET lifecycle='superseded'
            WHERE lifecycle='active'
              AND NOT (source_key=ANY(CAST(:canonical AS text[])))
        """),
    )
    changed: dict[str, int] = {}
    for key, statement in statements:
        result = await session.execute(text(statement), params)
        changed[key] = int(getattr(result, "rowcount", 0) or 0)
    return changed


async def run(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    if args.apply and settings.app_env == "production":
        raise CleanupRefused("production_cleanup_forbidden")
    if args.apply and settings.migration_dsn is None:
        raise CleanupRefused("migration_dsn_required_for_apply")
    dsn = settings.migration_dsn if args.apply else settings.postgres_dsn
    engine = create_async_engine(async_dsn(dsn), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            if not args.apply:
                before = await inventory(session)
                validate_inventory(before)
                fingerprint = cleanup_fingerprint(before)
                return {
                    "operation": "retire_development_sot",
                    "mode": "dry_run",
                    "status": "ready",
                    "captured_at": datetime.now(UTC).isoformat(),
                    "fingerprint": fingerprint,
                    "inventory": before,
                    "external_calls": 0,
                }
            async with session.begin():
                await ensure_mutation_allowed(session)
                await session.execute(text("SELECT pg_advisory_xact_lock(827006)"))
                before = await inventory(session)
                validate_inventory(before)
                fingerprint = cleanup_fingerprint(before)
                if fingerprint != args.expected_fingerprint:
                    raise CleanupRefused(
                        f"fingerprint_mismatch:expected={args.expected_fingerprint}:actual={fingerprint}",
                    )
                changed = await _mutate(session)
                after = await inventory(session)
                validate_postconditions(before, after)
                event_id = await AuditRepository().append(
                    session,
                    actor_kind="service",
                    actor_user_id=None,
                    action="sot.development_lineage.retire",
                    result="success",
                    reason_code="fixture_lineage_retired",
                    request_id=f"retire-development-sot:{fingerprint[:16]}",
                    resource_type="sot_runtime",
                    details={
                        "fingerprint": fingerprint,
                        "target_counts": before["targets"]["counts"],
                        "target_producers": before["targets"]["producers"],
                        "changed": changed,
                    },
                )
            return {
                "operation": "retire_development_sot",
                "mode": "apply",
                "status": "completed",
                "captured_at": datetime.now(UTC).isoformat(),
                "fingerprint": fingerprint,
                "audit_event_id": str(event_id),
                "changed": changed,
                "before": before,
                "after": after,
                "external_calls": 0,
            }
    finally:
        await engine.dispose()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retire allowlisted development SOT lineages (dry-run by default).",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.apply and not args.approve:
        parser.error("--apply requires --approve")
    if args.apply and not args.expected_fingerprint:
        parser.error("--apply requires --expected-fingerprint from the dry-run")
    if not args.apply and (args.approve or args.expected_fingerprint):
        parser.error("--approve/--expected-fingerprint are valid only with --apply")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = asyncio.run(run(args))
    except CleanupRefused as error:
        print(f"CLEANUP REFUSED · {error}", file=sys.stderr)
        return 2
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
