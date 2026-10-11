"""R-only observations. Original call arguments, returns and exceptions survive.

No SQL text/parameters, source content or HTTP payload is retained. All clocks
are monotonic nanoseconds. Nested phase wall spans are inclusive; exclusive
wall time subtracts direct-child interval unions, not separately ranked p95s.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from sqlalchemy import event

active = ContextVar("r_request_metrics", default=None)
stack = ContextVar("r_phase_stack", default=())


class PhaseProfiler:
    def __init__(self, engine, output: Path):
        self.engine = engine
        self.pool = engine.sync_engine.pool
        self.output = output
        self.stream = (output / "phase-requests.jsonl").open("x")
        self.records = []
        self.restore = []
        self.listeners = []
        self.statements = {}
        self.late_events = 0
        self.recorder_cost = []

    def add(self, key, record):
        current = active.get()
        if current is not None:
            if current["closed"]:
                self.late_events += 1
            elif len(current[key]) < 4096:
                current[key].append(record)
            else:
                current["dropped_events"] += 1

    def occupancy(self):
        return {
            "size": self.pool.size(),
            "checked_out": self.pool.checkedout(),
            "checked_in": self.pool.checkedin(),
            "overflow": self.pool.overflow(),
        }

    def classification(self, statement):
        # Cache STATIC statement classifications only, never bound parameters.
        if statement not in self.statements:
            normalized = " ".join(statement.split())
            lower = normalized.lower()
            kind = lower.partition(" ")[0]
            kind = kind if kind in {"select", "insert", "update", "delete"} else "other"
            if "pg_advisory_xact_lock_shared(" in lower:
                kind = "advisory_shared"
            elif "pg_advisory_xact_lock(" in lower:
                kind = "advisory_exclusive"
            elif "for share" in lower:
                kind = "row_share"
            elif "for update" in lower:
                kind = "row_update"
            if len(self.statements) == 512:
                self.statements.pop(next(iter(self.statements)))
            self.statements[statement] = (kind, hashlib.sha256(normalized.encode()).hexdigest())
        return self.statements[statement]

    @staticmethod
    def pid(connection):
        try:
            return connection.connection.driver_connection.get_server_pid()
        except (AttributeError, TypeError):
            return None

    def install(self):
        from httpx import AsyncClient

        from rtr_copilot.actions.execution import ExecutionService
        from rtr_copilot.actions.policy import ActionPolicy
        from rtr_copilot.actions.service import ActionService
        from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
        from rtr_copilot.repositories.resources import ResourceRepository

        specs = {
            ActionService: (
                "create_plan",
                "_payload",
                "_contract",
                "_snapshot",
                "_source_snapshot",
                "_insert_plan",
                "_metadata_plan",
                "_revalidate",
                "read_plan",
                "_audit",
            ),
            ActionPolicy: (
                "current",
                "session_current",
                "scope",
                "sources",
                "step",
                "resource",
                "session_resource",
            ),
            ExecutionService: ("submit", "status", "cancel", "_owner", "_view", "_row", "_event"),
            PostgresSubjectRepository: ("get_by_user_id", "_entitlements"),
            ResourceRepository: ("effective_policy_attributes",),
        }
        for cls, names in specs.items():
            for name in names:
                original = getattr(cls, name)
                label = cls.__name__ + "." + name
                self.restore.append((cls, name, original))
                setattr(cls, name, self.phase(original, label))

        def listen(target, name, callback):
            event.listen(target, name, callback)
            self.listeners.append((target, name, callback))

        def before(conn, cursor, statement, parameters, context, executemany):
            if active.get() is None:
                return
            kind, sha = self.classification(statement)
            record = {
                "start_ns": time.perf_counter_ns(),
                "end_ns": None,
                "phase_ids": list(stack.get()),
                "pid": self.pid(conn),
                "statement_class": kind,
                "static_sha256": sha,
                "error_type": None,
            }
            context.r_observation = record
            self.add("sql", record)

        def after(conn, cursor, statement, parameters, context, executemany):
            record = getattr(context, "r_observation", None)
            if record is not None:
                record["end_ns"] = time.perf_counter_ns()

        def error(context):
            execution = context.execution_context
            record = getattr(execution, "r_observation", None)
            if record is not None:
                record["end_ns"] = time.perf_counter_ns()
                record["error_type"] = type(context.original_exception).__name__

        listen(self.engine.sync_engine, "before_cursor_execute", before)
        listen(self.engine.sync_engine, "after_cursor_execute", after)
        listen(self.engine.sync_engine, "handle_error", error)

        def checkout(dbapi_connection, connection_record, connection_proxy):
            if active.get() is not None:
                connection_record.info["r_hold"] = (
                    active.get(),
                    stack.get(),
                    time.perf_counter_ns(),
                )

        def checkin(dbapi_connection, connection_record):
            held = connection_record.info.pop("r_hold", None)
            if held is not None:
                request, phases, start = held
                record = {
                    "start_ns": start,
                    "end_ns": time.perf_counter_ns(),
                    "phase_ids": list(phases),
                }
                if not request["closed"]:
                    request["holds"].append(record)
                else:
                    self.late_events += 1

        listen(self.pool, "checkout", checkout)
        listen(self.pool, "checkin", checkin)
        for name in ("connect", "_do_get", "_create_connection"):
            original = getattr(self.pool, name)
            self.restore.append((self.pool, name, original))
            setattr(self.pool, name, self.pool_call(original, name))

        original_request = AsyncClient.request
        self.restore.append((AsyncClient, "request", original_request))

        @wraps(original_request)
        async def request(client, *args, **kwargs):
            request_id = kwargs.get("headers", {}).get("X-Request-ID", "")
            match = re.fullmatch(
                r"tip054-latency-(1|10|25|50)-(\d+)-(admission|submit|status|cancel)", request_id
            )
            if match is None:
                return await original_request(client, *args, **kwargs)
            record = {
                "request_id": request_id,
                "profile": int(match[1]),
                "case": int(match[2]),
                "operation": match[3],
                "start_ns": time.perf_counter_ns(),
                "end_ns": None,
                "phases": [],
                "sql": [],
                "pool": [],
                "holds": [],
                "closed": False,
                "dropped_events": 0,
                "error_type": None,
            }
            token, phase_token = active.set(record), stack.set(())
            try:
                response = await original_request(client, *args, **kwargs)
                record["http_status"] = response.status_code
                return response
            except BaseException as exc:
                record["error_type"] = type(exc).__name__
                raise
            finally:
                record["end_ns"] = time.perf_counter_ns()
                record["closed"] = True
                record["request_inclusive_ms"] = (record["end_ns"] - record["start_ns"]) / 1e6
                for phase in record["phases"]:
                    self.finish_phase(phase, record)
                serialize_start = time.perf_counter_ns()
                line = json.dumps(record, separators=(",", ":")) + "\n"
                write_start = time.perf_counter_ns()
                self.stream.write(line)
                self.stream.flush()
                write_end = time.perf_counter_ns()
                self.recorder_cost.append(
                    {
                        "request_id": request_id,
                        "bytes": len(line.encode()),
                        "serialize_ms": (write_start - serialize_start) / 1e6,
                        "append_flush_ms": (write_end - write_start) / 1e6,
                    }
                )
                self.records.append(record)
                active.reset(token)
                stack.reset(phase_token)

        AsyncClient.request = request

    def phase(self, original, label):
        @wraps(original)
        async def wrapped(*args, **kwargs):
            request = active.get()
            if request is None:
                return await original(*args, **kwargs)
            phase_id = len(request["phases"])
            record = {
                "phase_id": phase_id,
                "name": label,
                "parent_ids": list(stack.get()),
                "start_ns": time.perf_counter_ns(),
                "end_ns": None,
                "error_type": None,
            }
            self.add("phases", record)
            token = stack.set((*stack.get(), phase_id))
            try:
                return await original(*args, **kwargs)
            except BaseException as exc:
                record["error_type"] = type(exc).__name__
                raise
            finally:
                record["end_ns"] = time.perf_counter_ns()
                stack.reset(token)

        return wrapped

    def pool_call(self, original, label):
        @wraps(original)
        def wrapped(*args, **kwargs):
            if active.get() is None:
                return original(*args, **kwargs)
            record = {
                "kind": label,
                "start_ns": time.perf_counter_ns(),
                "end_ns": None,
                "phase_ids": list(stack.get()),
                "before": self.occupancy(),
                "error_type": None,
            }
            self.add("pool", record)
            try:
                return original(*args, **kwargs)
            except BaseException as exc:
                record["error_type"] = type(exc).__name__
                raise
            finally:
                record["end_ns"] = time.perf_counter_ns()
                record["after"] = self.occupancy()

        return wrapped

    @staticmethod
    def finish_phase(phase, request):
        end = phase["end_ns"]
        if end is None:
            return
        phase_id = phase["phase_id"]
        intervals = sorted(
            (max(phase["start_ns"], c["start_ns"]), min(end, c["end_ns"]))
            for c in request["phases"]
            if c["end_ns"] is not None and c["parent_ids"] and c["parent_ids"][-1] == phase_id
        )
        covered, last = 0, phase["start_ns"]
        for start, stop in intervals:
            if stop > max(last, start):
                covered += stop - max(last, start)
                last = stop
        phase["inclusive_ms"] = (end - phase["start_ns"]) / 1e6
        phase["exclusive_ms"] = max(0, end - phase["start_ns"] - covered) / 1e6
        for inclusive in (True, False):
            sql = [
                s
                for s in request["sql"]
                if s["phase_ids"]
                and (phase_id in s["phase_ids"] if inclusive else s["phase_ids"][-1] == phase_id)
            ]
            prefix = "inclusive" if inclusive else "exclusive"
            phase[prefix + "_sql_started"] = len(sql)
            phase[prefix + "_sql_finished"] = sum(s["end_ns"] is not None for s in sql)
            phase[prefix + "_sql_ms"] = sum(
                (s["end_ns"] - s["start_ns"]) / 1e6 for s in sql if s["end_ns"] is not None
            )

    def close(self):
        for target, name, original in reversed(self.restore):
            setattr(target, name, original)
        for target, name, callback in self.listeners:
            event.remove(target, name, callback)
        self.stream.close()
        summary = {
            "requests": len(self.records),
            "dropped_events": sum(r["dropped_events"] for r in self.records),
            "late_events": self.late_events,
            "sql_started": sum(len(r["sql"]) for r in self.records),
            "sql_without_end": sum(s["end_ns"] is None for r in self.records for s in r["sql"]),
            "pool_failed_types": dict(
                Counter(p["error_type"] for r in self.records for p in r["pool"] if p["error_type"])
            ),
            "limits": (
                "Transparent diagnostic wrappers only. pool.connect includes pre-ping; "
                "_do_get includes queue plus creation; creation is separately measured, "
                "not pure queue. SQL cancellation/open spans retained; lock statement "
                "envelope is not continuous lock-wait duration."
            ),
        }
        (self.output / "phase-observer-summary.json").write_text(json.dumps(summary, indent=2))
        (self.output / "phase-recorder-cost.json").write_text(
            json.dumps(self.recorder_cost, indent=2)
        )
