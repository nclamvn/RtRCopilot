"""Real synthetic legacy survivors for TIP-054.2/.3 migration-only gates.

Uses the existing signed SOT/import/render contracts. Stored evidence contains
only synthetic row counts and fingerprints, never copied source payloads.
"""

import asyncio
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

BACKEND = Path(__file__).resolve().parents[1] / "apps" / "backend"
sys.path.insert(0, str(BACKEND / "tests"))

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from test_documents_integration import (  # noqa: E402
    approved_template,
    patch_ingestion,
    principal,
    run_render,
)
from test_rag_integration import actor, publish_and_index  # noqa: E402

from rtr_copilot.auth.models import Role  # noqa: E402
from rtr_copilot.db.uow import UnitOfWork  # noqa: E402
from rtr_copilot.repositories.audit import AuditRepository  # noqa: E402

EVIDENCE = Path("/tmp/tip054-migration-survivors.json")
CONTEXT_EVIDENCE = Path("/tmp/tip054-migration-context.json")
TABLES = (
    "subjects", "resources", "acl_entries", "sot_packages", "records", "record_versions",
    "search_generations", "search_generation_term_stats", "templates", "template_versions",
    "render_jobs", "document_publication_outbox", "generated_files", "document_versions",
    "object_blobs", "audit_events",
)


async def main() -> None:
    dsn = os.environ["INTEGRATION_DATABASE_DSN"]
    database = unquote(urlsplit(dsn).path.lstrip("/"))
    if not database.startswith("rtr_tip054_"):
        raise RuntimeError("migration_survivor_database_not_disposable")
    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        if sys.argv[1:] == ["seed"]:
            with tempfile.TemporaryDirectory(prefix="rtr-tip054-migration-") as temporary:
                owner = await actor(factory)
                await publish_and_index(
                    Path(temporary), factory, owner, source_key="tip054.migration.survivor",
                    record_key="TIP054.MIGRATION.SIGNED",
                    text_value="Synthetic migration survivor has an explicitly signed source.",
                )
            with pytest.MonkeyPatch.context() as patch:
                patch_ingestion(patch, factory)
                service, render_owner, version_id = await approved_template(factory)
                status = await run_render(service, render_owner, version_id, "Synthetic survivor")
                if status.state != "completed":
                    raise RuntimeError(f"migration_survivor_render_failed:{status.error_code}")
        elif sys.argv[1:] == ["seed-context"]:
            from rtr_copilot.context.models import MemoryCreate, PacketRequest
            from rtr_copilot.context.service import ContextService

            owner = await principal(factory, "migration-context", {Role.STAFF})
            service = ContextService(factory=factory)
            await service.create_memory(owner, MemoryCreate(
                kind="preference", text="Synthetic migration memory remains a preference",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            ), request_id="migration-context-memory")
            await service.resolve(owner, PacketRequest(
                query="migration survivor", source_keys=("tip054.migration.survivor",),
            ), request_id="migration-context-packet", persist=True)
            context_snapshot: dict[str, list[str]] = {}
            async with factory() as session:
                for table in ("context_packets", "memory_entries"):
                    hashes = await session.scalar(text(
                        f"SELECT array_agg(md5(to_jsonb(t)::text)) FROM {table} t",
                    ))
                    if not hashes:
                        raise RuntimeError(f"migration_context_fixture_missing:{table}")
                    context_snapshot[table] = hashes
            CONTEXT_EVIDENCE.write_text(json.dumps(context_snapshot), encoding="utf-8")
            print("MIGRATION_CONTEXT_SEEDED packet_and_memory=true")
        elif sys.argv[1:] == ["verify-context"]:
            previous_context = json.loads(CONTEXT_EVIDENCE.read_text(encoding="utf-8"))
            async with factory() as session:
                for table, hashes in previous_context.items():
                    if table not in ("context_packets", "memory_entries"):
                        raise RuntimeError("migration_context_table_invalid")
                    current_hashes = await session.scalar(text(
                        f"SELECT array_agg(md5(to_jsonb(t)::text)) FROM {table} t",
                    ))
                    if Counter(hashes) - Counter(current_hashes or []):
                        raise RuntimeError(f"migration_context_survivor_changed:{table}")
            print("MIGRATION_CONTEXT_SURVIVORS_PASS tables=2")
        elif sys.argv[1:] == ["seed-actions"]:
            from rtr_copilot.actions.models import PlanRequest, StepRequest
            from rtr_copilot.actions.service import ActionService
            from rtr_copilot.context.models import SOTReference

            admin = await principal(factory, "migration-action-admin", {Role.STAFF, Role.ADMIN})
            async with factory() as session, session.begin():
                await session.execute(text("""
                    INSERT INTO subject_roles(subject_id,role_id)
                    SELECT CAST(:subject AS uuid),role_id FROM roles WHERE key='admin'
                """), {"subject": admin.user_id})
            service = ActionService(UnitOfWork(factory))
            await service.admit_capability(admin, "sot.read", "1",
                                           request_id="migration-capability-admission")
            async with factory() as session:
                source = (await session.execute(text("""
                    SELECT r.source_key,r.record_key,v.version_id,v.content_sha256
                    FROM records r JOIN record_versions v ON v.version_id=r.current_version_id
                    WHERE r.record_key='TIP054.MIGRATION.SIGNED'
                """))).mappings().one()
            reference = SOTReference(
                source_key=source["source_key"], record_key=source["record_key"],
                record_version_id=source["version_id"], content_sha256=source["content_sha256"],
            )
            plan = await service.create_plan(admin, PlanRequest(
                idempotency_key="tip054-migration-read-plan",
                objective="Validate a synthetic source-read contract without executing it",
                source_refs=(reference,),
                steps=(StepRequest(step_key="read", capability_id="sot.read",
                                   arguments={"record_key": "TIP054.MIGRATION.SIGNED"}),),
            ), request_id="migration-plan-admission")
            if plan.execution_available:
                raise RuntimeError("migration_action_false_executor_claim")
            async with factory() as session:
                for table in ("capability_versions", "action_plans", "action_runs",
                              "action_events", "action_receipts"):
                    if not await session.scalar(text(f"SELECT count(*) FROM {table}")):
                        raise RuntimeError(f"migration_action_fixture_missing:{table}")
            print("MIGRATION_ACTIONS_SEEDED contract_only=true executor=false")
        elif sys.argv[1:] != ["verify"]:
            raise RuntimeError("migration_survivor_mode_invalid")

        snapshot: dict[str, dict[str, object]] = {}
        async with factory() as session:
            valid_audit, audit_count, _ = await AuditRepository().verify(session)
            if not valid_audit or audit_count == 0:
                raise RuntimeError("migration_audit_chain_invalid")
            for table in TABLES:
                row = (await session.execute(text(
                    f"SELECT count(*) AS count, array_agg(md5(to_jsonb(t)::text)) AS row_digests, "
                    f"md5(COALESCE("
                    f"jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text,'[]')) AS digest "
                    f"FROM {table} t",
                ))).mappings().one()
                snapshot[table] = {
                    "count": row["count"], "digest": row["digest"],
                    "row_digests": row["row_digests"] or [],
                }
        if sys.argv[1:] == ["seed"]:
            if any(snapshot[table]["count"] == 0 for table in (
                "sot_packages", "record_versions", "render_jobs", "generated_files", "audit_events",
            )):
                raise RuntimeError("migration_survivor_missing_representative_rows")
            EVIDENCE.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
            summary = {table: {key: value for key, value in row.items() if key != "row_digests"}
                       for table, row in snapshot.items()}
            print("MIGRATION_SURVIVORS_SEEDED", json.dumps(summary, sort_keys=True))
        else:
            previous = json.loads(EVIDENCE.read_text(encoding="utf-8"))
            # New Context/Action admissions legitimately append audit history.
            # Exact fingerprints of every original row must remain present;
            # no changed/deleted legacy row is hidden by those additions.
            changed = [table for table in TABLES if
                       Counter(previous[table]["row_digests"]) -
                       Counter(snapshot[table]["row_digests"])]
            if changed:
                raise RuntimeError(f"migration_survivors_changed:{','.join(changed)}")
            print(f"MIGRATION_SURVIVORS_PASS row_tables={len(TABLES)} audit_chain=true")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
