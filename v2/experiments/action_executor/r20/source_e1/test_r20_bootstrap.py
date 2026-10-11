"""Two separately admitted fresh-child probes; no product imports at collection."""

import os
from uuid import UUID, uuid4

import pytest

from env_contract import DATABASE, DSN, environment


def assert_settings(settings):
    assert str(settings.postgres_dsn) == DSN
    assert settings.action_executor_enabled is False and settings.action_workflow_dsn is None
    assert settings.rag_embedding_provider == "offline" and settings.rag_provider_mode == "local"
    assert not settings.openai_api_key.get_secret_value()
    assert not settings.anthropic_api_key.get_secret_value()
    assert (settings.limits_rate_render_max, settings.limits_rate_default_read_max,
            settings.limits_rate_window_seconds, settings.action_executor_operation_timeout_seconds) == (30, 120, 60, .9)


def test_missing_integration_import_capture_rejected_without_sql(monkeypatch, tmp_path):
    environment(os.environ)
    # Explicitly admitted read-only diagnostic exception, NOT a bootstrap envelope.
    monkeypatch.delenv("INTEGRATION_DATABASE_DSN")
    from pydantic import ValidationError
    from test_tip054_baseline_integration import DATABASE_DSN, synthetic_settings

    assert DATABASE_DSN == "" and os.environ["POSTGRES_DSN"] == DSN
    with pytest.raises(ValidationError) as caught:
        synthetic_settings(tmp_path)
    errors = caught.value.errors()
    assert len(errors) == 1 and errors[0]["loc"] == ("postgres_dsn",)
    assert errors[0]["input"] == "" and errors[0]["type"] == "url_parsing"
    print("R20_NEGATIVE_CAPTURE_PASS no_SQL_no_engine_no_HTTP")


@pytest.mark.asyncio
async def test_same_unchanged_dependency_chain_owned_seed_bootstrap(tmp_path):
    environment(os.environ)
    from sqlalchemy import text
    from test_action_contracts_integration import principal
    from test_context_memory_integration import DSN as context_dsn, publish
    from test_tip054_baseline_integration import DATABASE_DSN, synthetic_settings

    from rtr_copilot.actions.service import ActionService, correlation
    from rtr_copilot.auth.models import Role
    from rtr_copilot.config import get_settings
    from rtr_copilot.db.engine import runtime_engine, session_factory
    from rtr_copilot.db.uow import UnitOfWork

    assert context_dsn == DATABASE_DSN == DSN
    assert_settings(get_settings())
    assert_settings(synthetic_settings(tmp_path))
    engine = runtime_engine()
    try:
        factory = session_factory()
        assert factory.kw["bind"] is engine and factory.kw["expire_on_commit"] is False
        assert engine.sync_engine.pool.size() == 5
        assert engine.sync_engine.pool._max_overflow == 5 and engine.sync_engine.pool._pre_ping is True
        admin, owner = await principal(factory, Role.ADMIN), await principal(factory)
        assert admin.user_id != owner.user_id and Role.ADMIN in admin.roles and Role.STAFF in owner.roles
        source, core = "tip054.latency." + uuid4().hex, "TIP054.LATENCY." + uuid4().hex
        refs = await publish(tmp_path, factory, owner, source, core)
        assert len(refs) == 1 and (refs[0].source_key, refs[0].record_key) == (source, core)
        actions = ActionService(UnitOfWork(factory))
        admitted = await actions.admit_capability(admin, "sot.read", "2", request_id="latency-capability-admit")
        assert admitted.admission == "admitted"
        async with factory() as session:
            identity = (await session.execute(text("SELECT current_database(),current_user"))).one()
            assert tuple(identity) == (DATABASE, "rtr_app")
            roles = (await session.execute(text("""
                SELECT s.user_id,s.issuer,s.status,r.key FROM subjects s
                JOIN subject_roles sr ON sr.subject_id=s.user_id JOIN roles r ON r.role_id=sr.role_id
                WHERE s.user_id IN (:admin,:owner) AND sr.valid_from<=now()
                  AND (sr.expires_at IS NULL OR sr.expires_at>now())
            """), {"admin": UUID(admin.user_id), "owner": UUID(owner.user_id)})).all()
            assert len(roles) == 2
            assert {(str(row[0]), row[3]) for row in roles} == {(admin.user_id, "admin"), (owner.user_id, "staff")}
            assert all(row[1] == "tip054-synthetic" and row[2] == "active" for row in roles)
            reference = (await session.execute(text("""
                SELECT r.current_version_id,v.content_sha256,r.owner_subject_id,r.lifecycle,
                  v.lifecycle,rs.lifecycle_state,p.lifecycle,ar.package_id,
                  EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=r.record_id
                    AND a.principal_type='user' AND a.principal_id=:owner
                    AND a.action='view' AND a.effect='allow'
                    AND a.valid_from<=now() AND (a.expires_at IS NULL OR a.expires_at>now())) AS owner_view
                FROM records r JOIN record_versions v ON v.version_id=r.current_version_id
                  AND v.record_id=r.record_id
                JOIN resources rs ON rs.resource_id=r.record_id
                JOIN sot_packages p ON p.package_id=v.package_id
                JOIN sot_active_revisions ar ON ar.source_key=r.source_key
                WHERE r.source_key=:source AND r.record_key=:core AND ar.package_id=p.package_id
                  AND p.source_key=r.source_key AND p.revision=ar.revision
                  AND rs.owner_subject_id=:owner
            """), {"owner": UUID(owner.user_id), "source": source, "core": core})).one()
            assert reference[0] == refs[0].record_version_id and reference[1] == refs[0].content_sha256
            assert reference[2] == UUID(owner.user_id) and tuple(reference[3:7]) == ("active",) * 4
            assert reference[8] is True
            capability = (await session.execute(text("""
                SELECT admission,admitted_by,contract_digest,schema_digest FROM capability_versions
                WHERE capability_id='sot.read' AND version='2'
            """))).one()
            assert tuple(capability) == ("admitted", UUID(admin.user_id),
                                         admitted.contract_digest, admitted.schema_digest)
            audit = (await session.execute(text("""
                SELECT actor_user_id,action,result,reason_code,request_id FROM audit_events
                WHERE action='action.capability.admit'
            """))).one()
            assert tuple(audit) == (UUID(admin.user_id), "action.capability.admit", "success",
                                   "contract_recorded", correlation("latency-capability-admit"))
            outbox = (await session.execute(text("""
                SELECT status,dispatched_at FROM sot_reindex_outbox WHERE source_key=:source
            """), {"source": source})).one()
            assert tuple(outbox) == ("pending", None)
            counts = (await session.execute(text("""
                SELECT (SELECT count(*) FROM action_plans),(SELECT count(*) FROM action_runs),
                  (SELECT count(*) FROM action_executions)
            """))).one()
            assert tuple(counts) == (0, 0, 0)
        print("R20_POSITIVE_SEED_PASS subjects=2 refs=1 capability=1 audit=1 pending_outbox=1 actions=0")
    finally:
        await engine.dispose()
