"""Opt-in DBOS 3.2.0 worker; the API never imports/launches this module."""

import asyncio
import signal
import uuid
from contextlib import suppress
from typing import Any

from dbos import DBOS, DBOSConfig, SetWorkflowID
from sqlalchemy import text

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.execution_models import ExecutionLeaseLost
from rtr_copilot.config import Settings, get_settings


@DBOS.step(retries_allowed=False)
async def action_tick(run_id: str) -> dict[str, Any]:
    try:
        decision = await ExecutionService().advance(uuid.UUID(run_id))
        return decision.model_dump(mode="json")
    except ExecutionLeaseLost:
        return {"run_id": run_id, "state": "waiting", "terminal": False}


@DBOS.workflow()
async def action_workflow(run_id: str) -> dict[str, Any]:
    while True:
        decision = await action_tick(run_id)
        if decision["terminal"]:
            return decision
        await DBOS.sleep_async(get_settings().action_executor_poll_seconds)


def runtime_config(settings: Settings) -> DBOSConfig:
    if not settings.action_executor_enabled or settings.action_workflow_dsn is None:
        raise ValueError("executor_unavailable")
    return DBOSConfig(
        name="rtr-action-executor", application_version=settings.action_executor_version,
        executor_id=settings.action_executor_id,
        system_database_url=str(settings.action_workflow_dsn), dbos_system_schema="dbos",
        sys_db_pool_size=4, max_executor_threads=4, enable_otlp=False,
        run_migrations=True, use_listen_notify=False,
        db_engine_kwargs={"connect_args": {"connect_timeout": 2}, "pool_timeout": 2},
    )


async def dispatch_pending(service: ExecutionService) -> int:
    async with service.uow.factory() as session:
        rows = (await session.execute(text("""
            SELECT run_id,workflow_id,executor_version,build_id FROM action_executions
            WHERE dispatch_pending AND state NOT IN
              ('succeeded','partial','failed','cancelled','needs_review','paused')
            ORDER BY created_at LIMIT 20
        """))).mappings().all()
    count = 0
    for row in rows:
        if (row["executor_version"] != service.settings.action_executor_version
                or row["build_id"] != service.settings.rtr_build_sha):
            await service.claim(row["run_id"])
            continue
        # Stable native identity repairs dispatch-before-ack and DB-before-dispatch gaps.
        with SetWorkflowID(row["workflow_id"]):
            await DBOS.start_workflow_async(action_workflow, str(row["run_id"]))
        async with service.uow.transaction() as session:
            await session.execute(text("""
                UPDATE action_executions SET dispatch_pending=false,updated_at=now()
                WHERE run_id=:run AND executor_version=:version
            """), {"run": row["run_id"], "version": service.settings.action_executor_version})
        count += 1
    return count


async def worker() -> None:
    settings = get_settings()
    config = runtime_config(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    DBOS(config=config)
    DBOS.launch()
    service = ExecutionService()
    try:
        while not stop.is_set():
            await dispatch_pending(service)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.action_executor_poll_seconds)
    finally:
        # No synchronous get_result or waiter thread. Pending histories are recovered
        # by a compatible worker; zero completion wait avoids recv/drain deadlock.
        DBOS.destroy(workflow_completion_timeout_sec=0)


def main() -> None:
    asyncio.run(worker())


if __name__ == "__main__":
    main()
