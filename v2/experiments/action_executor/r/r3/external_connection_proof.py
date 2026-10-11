"""Isolated SA primitive proof; no product lease, authority or effect implementation."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from rtr_copilot.config import get_settings
from rtr_copilot.db.engine import async_dsn, runtime_engine
from rtr_copilot.db.uow import UnitOfWork


async def main(output: Path) -> None:
    dsn = str(get_settings().postgres_dsn)
    if not urlsplit(dsn).path.lstrip("/").startswith("rtr_tip054_"):
        raise RuntimeError("synthetic_database_required")
    if not str(output).startswith("/evidence/"):
        raise RuntimeError("host_evidence_required")
    output.parent.mkdir(parents=True, exist_ok=True)
    engine = runtime_engine()  # The unchanged serving 5+5/pre_ping engine.
    observer_engine = create_async_engine(async_dsn(dsn), poolclass=NullPool)
    owned_records: set[int] = set()
    pool_counts = {"checkout": 0, "checkin": 0, "max_held": 0}
    result: dict = {
        "status": "RUNNING",
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("SQLAlchemy", "asyncpg", "psycopg", "dbos")
        },
        "phases": [],
        "limits": (
            "One primary connection plus independent non-pooled app-role lock observer. "
            "Three sequential new Sessions/original UOW transactions; no product lease, "
            "Action permission/outcome, cancellation, lost acknowledgement or SDK proof. "
            "No domain writes/effects/audit append; real PG xact locks/ids/clocks only."
        ),
    }

    def checkout(_dbapi, record, _proxy) -> None:
        assert id(record) not in owned_records
        owned_records.add(id(record))
        pool_counts["checkout"] += 1
        pool_counts["max_held"] = max(pool_counts["max_held"], len(owned_records))

    def checkin(_dbapi, record) -> None:
        assert id(record) in owned_records
        owned_records.remove(id(record))
        pool_counts["checkin"] += 1

    event.listen(engine.sync_engine, "checkout", checkout)
    event.listen(engine.sync_engine, "checkin", checkin)
    driver = None
    retained_sessions: list[AsyncSession] = []
    primary = None
    try:
        async with asyncio.timeout(30):
            async with engine.connect() as primary, observer_engine.connect() as observer:
                raw = await primary.get_raw_connection()
                driver = raw.driver_connection
                assert not primary.in_transaction() and not driver.is_in_transaction()
                phase_factory = async_sessionmaker(primary, expire_on_commit=False)
                uow = UnitOfWork(phase_factory)

                async def probe() -> dict:
                    assert not observer.in_transaction()
                    async with observer.begin():
                        row = (
                            (
                                await observer.execute(
                                    text("""
                                SELECT current_user app_role, pg_backend_pid() pid,
                                  pg_try_advisory_xact_lock(827004) audit_available,
                                  pg_try_advisory_xact_lock(827005) maintenance_available
                                """)
                                )
                            )
                            .mappings()
                            .one()
                        )
                        assert row["app_role"] == "rtr_app"
                        answer = dict(row)
                    assert not observer.in_transaction()
                    return answer

                for phase in ("initial", "mutation", "postcommit_disclosure"):
                    assert not primary.in_transaction() and not driver.is_in_transaction()
                    async with uow.transaction() as session:
                        retained_sessions.append(session)
                        row = (
                            (
                                await session.execute(
                                    text("""
                                SELECT current_user app_role, pg_backend_pid() pid,
                                  txid_current() txid, transaction_timestamp() tx_clock,
                                  statement_timestamp() statement_clock
                                """)
                                )
                            )
                            .mappings()
                            .one()
                        )
                        assert row["app_role"] == "rtr_app"
                        await session.execute(text("SELECT pg_advisory_xact_lock(827004)"))
                        held = await probe()
                        assert held["pid"] != row["pid"]
                        assert not held["audit_available"] and not held["maintenance_available"]
                        assert primary.in_transaction() and driver.is_in_transaction()
                        evidence = {
                            "phase": phase,
                            "session_identity": id(session),
                            "pid": row["pid"],
                            "txid": row["txid"],
                            "transaction_timestamp": row["tx_clock"].isoformat(),
                            "statement_timestamp": row["statement_clock"].isoformat(),
                            "held_probe": held,
                        }
                    assert not session.in_transaction()
                    assert not primary.closed
                    assert not primary.in_transaction() and not driver.is_in_transaction()
                    released = await probe()
                    assert released["audit_available"] and released["maintenance_available"]
                    evidence["released_probe"] = released
                    evidence["sa_and_driver_active_transaction_after_phase"] = False
                    result["phases"].append(evidence)
                    output.write_text(json.dumps(result, indent=2))

                phases = result["phases"]
                assert len({id(s) for s in retained_sessions}) == 3
                assert len({p["pid"] for p in phases}) == 1
                assert len({p["txid"] for p in phases}) == 3
                clocks = [p["transaction_timestamp"] for p in phases]
                assert clocks[0] < clocks[1] < clocks[2]
                assert engine.pool.checkedout() == 1 and len(owned_records) == 1

            assert primary.closed
            assert driver is not None and not driver.is_in_transaction()
            assert engine.pool.checkedout() == 0 and not owned_records
            assert pool_counts == {"checkout": 1, "checkin": 1, "max_held": 1}
            result["cleanup"] = {
                "primary_sa_connection_closed": primary.closed,
                "driver_active_transaction_after_return": driver.is_in_transaction(),
                "pool_checked_out_after_return": engine.pool.checkedout(),
                "primary_pool_events": pool_counts,
                "listeners_removed": False,
            }
            result["status"] = "PASS"
    except BaseException as error:
        result["status"] = "FAIL"
        result["exception_type"] = type(error).__name__
        raise
    finally:
        try:
            async with asyncio.timeout(5):
                await observer_engine.dispose()
                await engine.dispose()
            result["driver_closed_after_engine_dispose"] = (
                driver.is_closed() if driver is not None else None
            )
            if driver is not None and not driver.is_closed():
                result["status"] = "FAIL"
                raise RuntimeError("driver_not_closed_after_dispose")
        except BaseException as error:
            result["status"] = "FAIL"
            result["cleanup_exception_type"] = type(error).__name__
            raise
        finally:
            event.remove(engine.sync_engine, "checkout", checkout)
            event.remove(engine.sync_engine, "checkin", checkin)
            if "cleanup" in result:
                result["cleanup"]["listeners_removed"] = True
            output.write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
