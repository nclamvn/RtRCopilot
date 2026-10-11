"""Fresh intended-load Settings capture and cold pool; no SQL or driver import."""

import os

import pytest
from qualification import DSN, WORKFLOW, environment


@pytest.mark.asyncio
async def test_captured_load_envelope_without_sql(tmp_path):
    environment(os.environ, "load")
    from test_action_contracts_integration import principal
    from test_context_memory_integration import DSN as context_dsn
    from test_context_memory_integration import publish
    from test_tip054_baseline_integration import DATABASE_DSN, synthetic_settings

    from rtr_copilot.config import get_settings
    from rtr_copilot.db.engine import runtime_engine, session_factory

    assert principal and publish  # Import dependency chain only; neither is called.
    assert context_dsn == DATABASE_DSN == DSN
    for settings in (get_settings(), synthetic_settings(tmp_path)):
        assert str(settings.postgres_dsn) == DSN
        assert settings.action_executor_enabled is True
        assert str(settings.action_workflow_dsn) == WORKFLOW
        assert (
            settings.rag_embedding_provider == "offline" and settings.rag_provider_mode == "local"
        )
        assert not settings.openai_api_key.get_secret_value()
        assert not settings.anthropic_api_key.get_secret_value()
        assert (
            settings.limits_rate_render_max,
            settings.limits_rate_default_read_max,
            settings.limits_rate_window_seconds,
            settings.action_executor_operation_timeout_seconds,
        ) == (5000, 5000, 60, 0.9)
    engine = runtime_engine()
    try:
        assert session_factory().kw["bind"] is engine
        pool = engine.sync_engine.pool
        assert pool.size() == 5 and pool._max_overflow == 5 and pool._pre_ping is True
        assert pool.checkedout() == 0 and pool.checkedin() == 0 and pool.overflow() == -5
        print("R21_ENVELOPE_PASS captured_DSN_cold_pool_no_SQL_no_seed_no_HTTP")
    finally:
        await engine.dispose()
