"""Small protocol/config checks; native durability is certified separately."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from rtr_copilot.actions.execution_api import bounded
from rtr_copilot.actions.registry import (
    EXECUTION_CONTRACTS,
    EXECUTION_OUTPUT,
    HOST_CONTRACTS,
    ActionError,
    HostRegistry,
    hashes,
    validate_input,
)
from rtr_copilot.config import Settings


def configuration(**updates: Any) -> Settings:
    values = {"postgres_dsn": "postgresql://business:test@db/domain", "migration_dsn": None,
              "redis_url": "redis://redis:6379", "s3_endpoint": "http://objects:9000",
              "s3_access_key": "fixture", "s3_secret_key": "fixture-only-secret",
              "s3_bucket": "fixture-only", "action_executor_enabled": False,
              "action_workflow_dsn": None}
    return Settings(_env_file=None, **{**values, **updates})


def test_default_off_and_v1_immutable() -> None:
    assert not configuration().action_executor_enabled
    registry = HostRegistry()
    for original in HOST_CONTRACTS:
        assert hashes(registry.contract(original.capability_id, "1")) == hashes(original)
        assert not original.execution_available
        assert registry.contract(original.capability_id, "2").execution_available


@pytest.mark.parametrize("updates", [
    {"action_executor_enabled": True},
    {"action_workflow_dsn": "postgresql://engine:test@db/domain"},
    {"action_workflow_dsn": "postgresql://business:test@db/engine"},
    {"action_workflow_dsn": "postgresql://postgres:test@db/engine"},
])
def test_bad_runtime_identity_fails_closed(updates: Any) -> None:
    with pytest.raises(ValidationError):
        configuration(**updates)


def test_isolated_configuration_and_output_schema() -> None:
    configured = configuration(action_executor_enabled=True,
                               action_workflow_dsn="postgresql://engine:test@db/engine")
    assert configured.action_executor_enabled
    validate_input({"outcome": "job_accepted", "output_digest": "a"*64}, EXECUTION_OUTPUT)
    with pytest.raises(ActionError):
        validate_input({"outcome": "fabricated_success", "output_digest": "a"*64}, EXECUTION_OUTPUT)
    for spec in EXECUTION_CONTRACTS:
        with pytest.raises(ValidationError):
            type(spec).model_validate_json(
                spec.model_copy(update={"version": "3"}).model_dump_json())


@pytest.mark.asyncio
async def test_api_timeout_cleans_async_waiter_without_result_thread() -> None:
    cancelled = False

    async def pending() -> None:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True

    request = SimpleNamespace(state=SimpleNamespace(request_id="fixture-only"))
    service = SimpleNamespace(settings=SimpleNamespace(
        action_executor_operation_timeout_seconds=.05))
    response = await bounded(request, SimpleNamespace(), service, pending())
    assert response.status_code == 503 and cancelled
    assert b"action_operation_timeout" in response.body
