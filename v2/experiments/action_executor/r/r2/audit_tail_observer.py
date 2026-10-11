"""Bounded numeric observations only; no authority, extra SQL or changed effects."""

import hashlib
import json
import time
from collections import Counter
from functools import wraps
from weakref import WeakKeyDictionary

from phase_profiler import active, stack
from sqlalchemy import event
from sqlalchemy.orm import Session

AUDIT_SHA = "2cf9705ca791be7b1767b6ddbf200944255cebc5f5702b5b7c9776d1f3ba6597"


class AuditTailObserver:
    def __init__(self, engine, output):
        self.engine = engine.sync_engine
        self.output = output
        self.sessions = WeakKeyDictionary()
        self.connections = WeakKeyDictionary()
        self.request_counts = Counter()
        self.records = []
        self.listeners = []
        self.cost = []
        self.callback_errors = Counter()
        self.dropped = 0
        self.unobserved_appends = 0
        self.stream = (output / "audit-transactions.jsonl").open("x")
        self.original_append = None

    def safe(self, callback):
        @wraps(callback)
        def guarded(*args, **kwargs):
            try:
                return callback(*args, **kwargs)
            except Exception as exc:
                # Observation failure must not replace a product result/error.
                self.callback_errors[type(exc).__name__] += 1

        return guarded

    def listen(self, target, name, callback):
        callback = self.safe(callback)
        event.listen(target, name, callback)
        self.listeners.append((target, name, callback))

    def install(self):
        from rtr_copilot.repositories.audit import AuditRepository

        def began(session, transaction, connection):
            request = active.get()
            if (
                transaction.parent is not None
                or connection.engine is not self.engine
                or request is None
                or request["closed"]
            ):
                return
            key = request["request_id"]
            if (
                key not in self.request_counts and len(self.request_counts) >= 1600
            ) or self.request_counts[key] >= 64:
                self.dropped += 1
                return
            self.request_counts[key] += 1
            record = {
                "transaction_number": len(self.records),
                "request_id": key,
                "profile": request["profile"],
                "operation": request["operation"],
                "start_ns": time.perf_counter_ns(),
                "terminal_ns": None,
                "terminal_kind": None,
                "emitted": False,
                "pid": connection.connection.driver_connection.get_server_pid(),
                "first_audit_grant_ns": None,
                "audit_attempts": [],
                "append_spans": [],
                "postgrant_sql_started": 0,
                "postgrant_sql_finished": 0,
                "postgrant_sql_errors": 0,
                "cross_request_events": 0,
            }
            self.records.append(record)
            self.sessions[session] = record
            self.connections[connection] = record

        def before(connection, cursor, statement, parameters, context, executemany):
            record = self.connections.get(connection)
            request = active.get()
            if record is None or record["emitted"]:
                return
            if request is not None and request["request_id"] != record["request_id"]:
                record["cross_request_events"] += 1
            context.r2_tail = record
            context.r2_postgrant = record["first_audit_grant_ns"] is not None
            if context.r2_postgrant:
                record["postgrant_sql_started"] += 1
            digest = hashlib.sha256(" ".join(statement.split()).encode()).hexdigest()
            if digest == AUDIT_SHA:
                if len(record["audit_attempts"]) >= 64:
                    self.dropped += 1
                    return
                attempt = {
                    "start_ns": time.perf_counter_ns(),
                    "end_ns": None,
                    "error_type": None,
                    "phase_ids": list(stack.get()),
                    "static_sha256": digest,
                }
                record["audit_attempts"].append(attempt)
                context.r2_attempt = attempt

        def after(connection, cursor, statement, parameters, context, executemany):
            record = getattr(context, "r2_tail", None)
            if record is None:
                return
            if getattr(context, "r2_postgrant", False):
                record["postgrant_sql_finished"] += 1
            attempt = getattr(context, "r2_attempt", None)
            if attempt is not None:
                attempt["end_ns"] = time.perf_counter_ns()
                if record["first_audit_grant_ns"] is None:
                    record["first_audit_grant_ns"] = attempt["end_ns"]

        def error(context):
            execution = context.execution_context
            record = getattr(execution, "r2_tail", None)
            if record is None:
                return
            if getattr(execution, "r2_postgrant", False):
                record["postgrant_sql_finished"] += 1
                record["postgrant_sql_errors"] += 1
            attempt = getattr(execution, "r2_attempt", None)
            if attempt is not None:
                attempt["end_ns"] = time.perf_counter_ns()
                attempt["error_type"] = type(context.original_exception).__name__

        def terminal(session, kind):
            record = self.sessions.get(session)
            if record is not None and not session.in_nested_transaction():
                record["terminal_ns"] = time.perf_counter_ns()
                record["terminal_kind"] = kind

        def ended(session, transaction):
            if transaction.parent is not None:
                return
            record = self.sessions.pop(session, None)
            if record is not None:
                if record["terminal_kind"] is None:
                    record["terminal_kind"] = "end_unknown"
                self.emit(record)

        self.listen(Session, "after_begin", began)
        self.listen(Session, "after_commit", lambda session: terminal(session, "commit_ack"))
        self.listen(Session, "after_rollback", lambda session: terminal(session, "rollback_ack"))
        self.listen(Session, "after_transaction_end", ended)
        self.listen(self.engine, "before_cursor_execute", before)
        self.listen(self.engine, "after_cursor_execute", after)
        self.listen(self.engine, "handle_error", error)
        original = AuditRepository.append
        self.original_append = original

        @wraps(original)
        async def append(repository, session, *args, **kwargs):
            start = time.perf_counter_ns()
            error_type = None
            try:
                return await original(repository, session, *args, **kwargs)
            except BaseException as exc:
                error_type = type(exc).__name__
                raise
            finally:
                try:
                    record = self.sessions.get(session.sync_session)
                    if record is not None and not record["emitted"]:
                        if len(record["append_spans"]) < 64:
                            record["append_spans"].append(
                                {
                                    "start_ns": start,
                                    "end_ns": time.perf_counter_ns(),
                                    "error_type": error_type,
                                }
                            )
                        else:
                            self.dropped += 1
                    elif active.get() is not None and not active.get()["closed"]:
                        self.unobserved_appends += 1
                except Exception as exc:
                    self.callback_errors[type(exc).__name__] += 1

        AuditRepository.append = append

    def emit(self, record):
        if record["emitted"]:
            return
        record["emitted"] = True
        grants = [
            a
            for a in record["audit_attempts"]
            if a["end_ns"] is not None and a["error_type"] is None
        ]
        record["completed_grants"] = len(grants)
        record["reentrant_grants"] = max(0, len(grants) - 1)
        start, end = record["first_audit_grant_ns"], record["terminal_ns"]
        record["grant_to_terminal_ms"] = (
            (end - start) / 1e6 if start is not None and end is not None else None
        )
        record["limits"] = "Client-observed grant completion to outer terminal acknowledgement"
        begin = time.perf_counter_ns()
        line = json.dumps(record, separators=(",", ":")) + "\n"
        written = time.perf_counter_ns()
        self.stream.write(line)
        self.stream.flush()
        finished = time.perf_counter_ns()
        self.cost.append(
            {
                "transaction_number": record["transaction_number"],
                "serialize_ms": (written - begin) / 1e6,
                "append_flush_ms": (finished - written) / 1e6,
            }
        )

    def close(self):
        from rtr_copilot.repositories.audit import AuditRepository

        for target, name, callback in reversed(self.listeners):
            event.remove(target, name, callback)
        if self.original_append is not None:
            AuditRepository.append = self.original_append
        for record in self.records:
            if not record["emitted"]:
                record["terminal_kind"] = "open_at_observer_close"
                self.emit(record)
        self.stream.close()
        unknown_granted = sum(
            r["first_audit_grant_ns"] is not None and r["terminal_ns"] is None for r in self.records
        )
        summary = {
            "transactions": len(self.records),
            "requests": len(self.request_counts),
            "audit_granted_transactions": sum(
                r["first_audit_grant_ns"] is not None for r in self.records
            ),
            "terminal_kinds": dict(Counter(r["terminal_kind"] for r in self.records)),
            "unknown_granted_transactions": unknown_granted,
            "dropped": self.dropped,
            "unobserved_appends": self.unobserved_appends,
            "callback_errors": dict(self.callback_errors),
            "cross_request_events": sum(r["cross_request_events"] for r in self.records),
            "unfinished_audit_attempts": sum(
                a["end_ns"] is None for r in self.records for a in r["audit_attempts"]
            ),
            "limits": (
                "Not exact server release, pure wait, or latency acceptance; ON costs included"
            ),
        }
        summary["metrics_complete"] = not any(
            (
                self.dropped,
                self.unobserved_appends,
                self.callback_errors,
                unknown_granted,
                summary["cross_request_events"],
                summary["unfinished_audit_attempts"],
            )
        )
        (self.output / "audit-observer-summary.json").write_text(json.dumps(summary, indent=2))
        (self.output / "audit-recorder-cost.json").write_text(json.dumps(self.cost, indent=2))
