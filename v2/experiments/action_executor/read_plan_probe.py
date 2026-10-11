"""Finite SELECT-only metadata timing; never logs source bodies or SQL parameters."""
import asyncio
from collections import Counter
from contextvars import ContextVar
import json
import math
import os
import time

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.actions.service import ActionService
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository

active = ContextVar("probe", default=None)


def p95(values):
    return sorted(values)[math.ceil(len(values) * .95) - 1]


async def main():
    engine = create_async_engine(
        os.environ["POSTGRES_DSN"].replace("postgresql://", "postgresql+asyncpg://", 1),
        pool_size=5, max_overflow=5, pool_pre_ping=True,
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    counts, times = Counter(), Counter()

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        context.probe_started = time.perf_counter()
        if active.get() is not None:
            active.get()["queries"] += 1

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, executemany):
        if active.get() is not None:
            elapsed = (time.perf_counter() - context.probe_started) * 1000
            active.get()["sql_ms"] += elapsed
            normalized = " ".join(statement.split())
            counts[normalized] += 1
            times[normalized] += elapsed

    original_get = engine.sync_engine.pool._do_get

    def measured_get():
        started = time.perf_counter()
        result = original_get()
        if active.get() is not None:
            active.get()["checkouts"] += 1
            active.get()["pool_ms"] += (time.perf_counter() - started) * 1000
        return result

    engine.sync_engine.pool._do_get = measured_get
    try:
        async with factory() as session:
            assert await session.scalar(text("SHOW default_transaction_read_only")) == "on"
            row = (await session.execute(text(
                "SELECT plan_id, actor_id FROM action_plans ORDER BY created_at DESC LIMIT 1"
            ))).one()
        subject = await PostgresSubjectRepository(factory).get_by_user_id(row.actor_id)
        assert subject is not None
        service = ActionService(UnitOfWork(factory))
        for concurrency in (1, 10, 25, 50):
            semaphore = asyncio.Semaphore(concurrency)
            results = []

            async def one(number):
                async with semaphore:
                    record = {"queries": 0, "sql_ms": 0., "pool_ms": 0., "checkouts": 0}
                    token = active.set(record)
                    started = time.perf_counter()
                    try:
                        await service.read_plan(subject, row.plan_id, request_id=f"read-probe-{number}")
                        record["elapsed_ms"] = (time.perf_counter() - started) * 1000
                        results.append(record)
                    finally:
                        active.reset(token)

            await asyncio.gather(*(one(n) for n in range(100)))
            print(json.dumps({"concurrency": concurrency, "samples": len(results),
                "query_counts": sorted({r["queries"] for r in results}),
                "checkouts": sorted({r["checkouts"] for r in results}),
                "p95_ms": {k: p95([r[k] for r in results])
                    for k in ("elapsed_ms", "sql_ms", "pool_ms")}}, sort_keys=True), flush=True)
        print(json.dumps({"top_selects": [{"sql": sql, "count": counts[sql], "sum_ms": ms}
            for sql, ms in times.most_common(12)]}, sort_keys=True), flush=True)
    finally:
        await engine.dispose()


asyncio.run(main())
