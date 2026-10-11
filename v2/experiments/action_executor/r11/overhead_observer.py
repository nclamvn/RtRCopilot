"""R11 numeric observer-only exposure. Reference delegation stays authoritative."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import json
import re
import time
import weakref
from pathlib import Path

FIELDS = (
    "span_id",
    "label_id",
    "request_index",
    "task_id",
    "parent_ids",
    "start_ns",
    "end_ns",
    "error_id",
    "origin_id",
    "reference_closed",
    "source_line",
    "prepare_start_ns",
    "prepare_end_ns",
    "finish_start_ns",
    "finish_end_ns",
)
ORIGINS = (
    "http",
    "post_http_reference",
    "audit_record",
    "control",
    "timer_inherited_unassigned",
    "outside_loop_unassigned",
    "late_reference",
)
FAULT_KEYS = (
    "callback_errors",
    "dropped",
    "window_exceeded",
    "open",
    "late_unexpected",
    "restore_errors",
)
CENSOR_KEYS = (
    "unscoped_skipped",
    "inherited_parents_excluded",
    "timer_unassigned",
    "outside_loop_unassigned",
)
REQUEST = re.compile(r"tip054-latency-(1|10|25|50)-([0-9]{1,2})-(admission|submit|status|cancel)")


class TaskIds:
    def __init__(self):
        self.items = {}
        self.next_id = 1

    def get(self, task):
        if task is None:
            return None
        key = id(task)
        old = self.items.get(key)
        if old is not None and old[0]() is task:
            return old[1]

        def departed(ref):
            previous = self.items.get(key)
            if previous is not None and previous[0] is ref:
                self.items.pop(key, None)

        ref = weakref.ref(task, departed)
        number = self.next_id
        self.next_id += 1
        self.items[key] = (ref, number)
        return number


class ObserverExposure:
    MAX_RECORDS = 800_000
    MAX_BYTES = 128 * 1024**2
    MAX_SECONDS = 180
    MAX_TABLE = 4096

    def __init__(self, output=None):
        self.output = Path(output) if output is not None else None
        self.rows, self.labels, self.requests, self.errors = [], [], [], []
        self.indexes = ({}, {}, {})
        self.ids = TaskIds()  # Separate from the target R9 registry.
        self.stack = contextvars.ContextVar("r11_local_parents", default=())
        self.control = contextvars.ContextVar("r11_control", default=None)
        self.override = contextvars.ContextVar("r11_reference_scope", default=None)
        self.restore = []
        self.phase_module = None
        self.boundary = None
        self.started_ns = None
        self.closed = False
        self.integrity = {key: 0 for key in FAULT_KEYS}
        self.censorship = {key: 0 for key in CENSOR_KEYS}

    def safe(self, operation, default=None):
        try:
            return operation()
        except BaseException:
            with contextlib.suppress(BaseException):
                self.integrity["callback_errors"] += 1
            return default

    @contextlib.contextmanager
    def scope(self, label):
        if not isinstance(label, str) or not 0 < len(label) <= 128 or REQUEST.fullmatch(label):
            raise ValueError("explicit bounded non-HTTP control label required")
        token = self.control.set(label)
        try:
            yield self
        finally:
            self.control.reset(token)

    def current(self):
        if self.phase_module is not None:
            return self.phase_module.active.get()
        if self.boundary is not None:
            return self.boundary.external_request()
        return None

    def metadata(self, label, context=None):
        outside_loop = False
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
            outside_loop = True
        control = self.control.get()
        record = context() if callable(context) else context
        if record is None:
            record = self.override.get() or self.current()
        if task is None and (record is not None or control is not None):
            origin = "outside_loop_unassigned" if outside_loop else "timer_inherited_unassigned"
            counter = "outside_loop_unassigned" if outside_loop else "timer_unassigned"
            self.censorship[counter] += 1
            return None, None, origin, record.get("closed") if record else None
        if control is not None:
            return control, self.ids.get(task), "control", None
        if record is None:
            self.censorship["unscoped_skipped"] += 1
            return None
        request = record.get("request_id")
        if not isinstance(request, str) or REQUEST.fullmatch(request) is None:
            raise ValueError("unexpected reference scope")
        closed = record.get("closed")
        if closed is not None and type(closed) is not bool:
            raise ValueError("closed scope type")
        if record.get("r11_origin") == "audit_record":
            origin = "audit_record"
        elif closed and label.startswith(("phase.", "audit.")):
            origin = "post_http_reference"
        elif closed:
            origin = "late_reference"
            self.integrity["late_unexpected"] += 1
        else:
            origin = "http"
        return request, self.ids.get(task), origin, closed

    def intern(self, value, table, index):
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 160:
            raise ValueError("bounded string table entry")
        if value not in index:
            if len(table) >= self.MAX_TABLE:
                raise ValueError("lookup table cap")
            index[value] = len(table)
            table.append(value)
        return index[value]

    def begin(self, label, context, source_line, prepared):
        meta = self.metadata(label, context)
        if meta is None:
            return None, None
        request, task, origin, closed = meta
        now = time.perf_counter_ns()
        if self.started_ns is None:
            self.started_ns = now
        if now - self.started_ns > self.MAX_SECONDS * 1e9:
            self.integrity["window_exceeded"] += 1
            return None, None
        if self.closed or len(self.rows) >= self.MAX_RECORDS:
            self.integrity["dropped"] += 1
            return None, None
        request_index = self.intern(request, self.requests, self.indexes[1])
        parents = []
        for parent in self.stack.get():
            row = self.rows[parent]
            if (
                row[5] is not None
                and row[6] is None
                and row[3] == task
                and task is not None
                and row[2] == request_index
            ):
                parents.append(parent)
            else:
                self.censorship["inherited_parents_excluded"] += 1
        row = [
            len(self.rows),
            self.intern(label, self.labels, self.indexes[0]),
            request_index,
            task,
            parents,
            None,
            None,
            None,
            ORIGINS.index(origin),
            closed,
            source_line,
            prepared,
            None,
            None,
            None,
        ]
        self.rows.append(row)
        token = self.stack.set((*parents, row[0]))
        try:
            row[5] = row[12] = time.perf_counter_ns()
        except BaseException:
            self.safe(lambda: self.stack.reset(token))
            raise
        return row, token

    def finish(self, row, token, end, error):
        try:
            if row is not None:
                row[6] = row[13] = end
                row[7] = self.intern(
                    type(error).__name__ if error is not None else None,
                    self.errors,
                    self.indexes[2],
                )
        finally:
            if token is not None:
                self.stack.reset(token)
            if row is not None:
                row[14] = time.perf_counter_ns()

    def measure(self, original, label, args=(), kwargs=None, context=None, source_line=None):
        """Only NEW preparation/finalization is contained, never original work."""
        prepared = self.safe(time.perf_counter_ns)
        row, token = self.safe(
            lambda: self.begin(label, context, source_line, prepared), (None, None)
        )
        error = None
        try:
            return original(*args, **({} if kwargs is None else kwargs))
        except BaseException as caught:
            error = caught
            raise
        finally:
            end = self.safe(time.perf_counter_ns)
            self.safe(lambda: self.finish(row, token, end, error))

    def patch(self, target, name, value):
        present, old = name in vars(target), vars(target).get(name)
        self.restore.append((target, name, present, old))
        setattr(target, name, value)

    @staticmethod
    def line(original):
        function = getattr(original, "__func__", original)
        code = getattr(function, "__code__", None)
        return code.co_firstlineno if code is not None else None

    def sync_hook(self, target, name, label, context=None):
        original = getattr(target, name)

        @functools.wraps(original)
        def wrapped(*args, **kwargs):
            return self.measure(
                original, label, args, kwargs, context, self.safe(lambda: self.line(original))
            )

        self.patch(target, name, wrapped)

    def attach_boundary(self, boundary):
        if self.boundary is not None:
            raise RuntimeError("one reference boundary required")
        self.boundary = boundary
        original = boundary.recording

        def recording(*args, **kwargs):
            operation = args[0] if args else kwargs.get("operation")
            source = self.safe(lambda: self.line(operation))
            label = "R9.recording@" + str(source) if source is not None else "R9.recording.unknown"
            return self.measure(original, label, args, kwargs, source_line=source)

        self.patch(boundary, "recording", recording)
        for name in ("begin", "finish", "request", "resource"):
            self.sync_hook(boundary, name, "R9." + name)
        self.sync_hook(boundary.ids, "get", "R9.WeakIds.get")

    def attach_phase(self, profiler, phase_module):
        if self.phase_module is not None:
            raise RuntimeError("one reference phase profiler required")
        self.phase_module = phase_module
        cls = type(profiler)
        descriptor = vars(cls)["finish_phase"]
        if not isinstance(descriptor, staticmethod):
            raise TypeError("expected exact staticmethod")
        original = descriptor.__func__

        def finish_phase(*args, **kwargs):
            record = args[1] if len(args) > 1 else kwargs.get("request")
            return self.measure(
                original,
                "phase.finish_phase",
                args,
                kwargs,
                lambda: record,
                self.safe(lambda: self.line(original)),
            )

        self.patch(cls, "finish_phase", staticmethod(finish_phase))
        self.patch(phase_module, "json", JsonFacade(self, phase_module.json, "phase"))
        self.patch(profiler, "stream", StreamFacade(self, profiler.stream, "phase"))

    def audit_context(self, record):
        active = self.current()
        return {
            "request_id": record["request_id"],
            "r11_origin": "audit_record",
            "closed": active.get("closed")
            if active is not None and active.get("request_id") == record["request_id"]
            else None,
        }

    def attach_audit(self, tail, audit_module):
        original = tail.emit

        def emit(*args, **kwargs):
            record = args[0] if args else kwargs.get("record")
            context = self.safe(lambda: self.audit_context(record))
            token = self.safe(lambda: self.override.set(context))
            try:
                return self.measure(
                    original,
                    "audit.emit",
                    args,
                    kwargs,
                    context,
                    self.safe(lambda: self.line(original)),
                )
            finally:
                if token is not None:
                    self.safe(lambda: self.override.reset(token))

        self.patch(tail, "emit", emit)
        self.patch(audit_module, "json", JsonFacade(self, audit_module.json, "audit"))
        self.patch(tail, "stream", StreamFacade(self, tail.stream, "audit"))

    def snapshot(self):
        finished = [r[14] if r[14] is not None else r[6] for r in self.rows]
        last = max((value for value in finished if value is not None), default=None)
        exceeded = (
            last is not None
            and self.started_ns is not None
            and last - self.started_ns > self.MAX_SECONDS * 1e9
        )
        payload = {
            "schema": list(FIELDS),
            "records": self.rows,
            "labels": self.labels,
            "requests": self.requests,
            "errors": self.errors,
            "origins": list(ORIGINS),
            "integrity": {
                **self.integrity,
                "window_exceeded": max(self.integrity["window_exceeded"], int(exceeded)),
                "open": sum(r[5] is None or r[6] is None for r in self.rows),
            },
            "window_start_ns": self.started_ns,
            "window_last_ns": last,
            "censorship": self.censorship,
            "partial_recorder_costs": (
                "prepare/finish absolute fields omit outer dispatch, clocks and final assignment; "
                "nested/nonadditive"
            ),
            "namespace": "R11-only weak task and local span IDs",
            "limits": {
                "records": self.MAX_RECORDS,
                "bytes": self.MAX_BYTES,
                "seconds": self.MAX_SECONDS,
            },
        }
        return json.loads(json.dumps(payload, separators=(",", ":")))

    def close(self):
        if self.closed:
            return
        self.closed = True
        faults = []
        for target, name, present, old in reversed(self.restore):
            try:
                if present:
                    setattr(target, name, old)
                else:
                    delattr(target, name)
            except BaseException as error:
                self.integrity["restore_errors"] += 1
                faults.append(error)
        self.restore.clear()
        if self.output is not None:
            raw = json.dumps(self.snapshot(), separators=(",", ":"), sort_keys=True).encode()
            if len(raw) > self.MAX_BYTES:
                raise ValueError("NEW exposure output cap")
            with (self.output / "observer-exposure.json").open("xb") as stream:
                stream.write(raw)
        if faults:
            raise faults[0]


class JsonFacade:
    def __init__(self, observer, original, label):
        self.observer, self.original, self.label = observer, original, label

    def dumps(self, *args, **kwargs):
        return self.observer.measure(self.original.dumps, self.label + ".serialize", args, kwargs)

    def __getattr__(self, name):
        return getattr(self.original, name)


class StreamFacade:
    def __init__(self, observer, original, label):
        self.observer, self.original, self.label = observer, original, label

    def write(self, *args, **kwargs):
        return self.observer.measure(self.original.write, self.label + ".write", args, kwargs)

    def flush(self, *args, **kwargs):
        return self.observer.measure(self.original.flush, self.label + ".flush", args, kwargs)

    def close(self, *args, **kwargs):
        return self.original.close(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.original, name)


def decoded_records(packet):
    """Strict compact-schema decoder; IDs never bridge any other namespace."""
    if packet["schema"] != list(FIELDS) or packet["origins"] != list(ORIGINS):
        raise ValueError("exposure schema changed")
    rows = packet["records"]
    if type(rows) is not list or any(type(r) is not list or len(r) != len(FIELDS) for r in rows):
        raise ValueError("compact row shape")
    if len(rows) > ObserverExposure.MAX_RECORDS or set(packet["integrity"]) != set(FAULT_KEYS):
        raise ValueError("record count/integrity schema")
    if set(packet["censorship"]) != set(CENSOR_KEYS):
        raise ValueError("censorship schema")
    for counters in (packet["integrity"], packet["censorship"]):
        if any(type(value) is not int or value < 0 for value in counters.values()):
            raise ValueError("counter type")
    first, last = packet["window_start_ns"], packet["window_last_ns"]
    if any(v is not None and (type(v) is not int or v < 0) for v in (first, last)):
        raise ValueError("window clock type")
    if last is not None and (first is None or last < first):
        raise ValueError("window clock ordering")
    if (
        first is not None
        and last is not None
        and last - first > ObserverExposure.MAX_SECONDS * 1e9
        and not packet["integrity"]["window_exceeded"]
    ):
        raise ValueError("unreported finished-window overrun")
    if packet["integrity"]["open"] != sum(r[5] is None or r[6] is None for r in rows):
        raise ValueError("open accounting")
    for table in ("labels", "requests", "errors"):
        entries = packet[table]
        if (
            type(entries) is not list
            or any(not isinstance(v, str) or len(v) > 160 for v in entries)
            or len(entries) > ObserverExposure.MAX_TABLE
            or len(entries) != len(set(entries))
        ):
            raise ValueError("lookup table schema/cap")
    result = []
    for index, row in enumerate(rows):
        if len(row) != len(FIELDS) or type(row[0]) is not int or row[0] != index:
            raise ValueError("span identity/schema")
        record = dict(zip(FIELDS, row, strict=True))
        for field in ("task_id", "source_line"):
            if record[field] is not None and (type(record[field]) is not int or record[field] <= 0):
                raise ValueError("numeric identity type")
        if record["reference_closed"] is not None and type(record["reference_closed"]) is not bool:
            raise ValueError("reference closed type")
        for field in (
            "start_ns",
            "end_ns",
            "prepare_start_ns",
            "prepare_end_ns",
            "finish_start_ns",
            "finish_end_ns",
        ):
            if record[field] is not None and (type(record[field]) is not int or record[field] < 0):
                raise ValueError("clock type")
        start, end = record["start_ns"], record["end_ns"]
        if start is not None and end is not None and end < start:
            raise ValueError("reversed clock")
        for a, b in (
            ("prepare_start_ns", "prepare_end_ns"),
            ("prepare_end_ns", "start_ns"),
            ("end_ns", "finish_start_ns"),
            ("finish_start_ns", "finish_end_ns"),
        ):
            if record[a] is not None and record[b] is not None and record[a] > record[b]:
                raise ValueError("preparation/finalization clock ordering")
        parents = record["parent_ids"]
        if type(parents) is not list or len(parents) > 64 or len(set(parents)) != len(parents):
            raise ValueError("parent schema")
        for parent in parents:
            if type(parent) is not int or not 0 <= parent < index:
                raise ValueError("unknown/nonpreceding parent")
            p = rows[parent]
            if (
                p[3] != row[3]
                or p[2] != row[2]
                or p[5] is None
                or start is None
                or p[5] > start
                or (p[6] is not None and end is not None and p[6] < end)
            ):
                raise ValueError("parent task/request/clock containment")
        for source, table, target in (
            ("label_id", "labels", "label"),
            ("request_index", "requests", "request_id"),
            ("error_id", "errors", "error_type"),
            ("origin_id", "origins", "origin"),
        ):
            value = record[source]
            if value is None and source in {"label_id", "origin_id"}:
                raise ValueError("missing mandatory label/origin")
            if value is not None and (
                type(value) is not int or not 0 <= value < len(packet[table])
            ):
                raise ValueError("lookup index")
            record[target] = packet[table][value] if value is not None else None
        taskless = {"timer_inherited_unassigned", "outside_loop_unassigned"}
        if record["origin"] in taskless and (
            record["task_id"] is not None or record["request_id"] is not None
        ):
            raise ValueError("taskless inherited association")
        if record["origin"] not in taskless and (
            record["request_id"] is None or record["task_id"] is None
        ):
            raise ValueError("missing assigned scope identity")
        result.append(record)
    return result
