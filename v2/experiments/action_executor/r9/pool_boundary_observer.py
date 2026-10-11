"""Numeric experiment-only boundaries; all original delegates remain authoritative."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import json
import time
import weakref
from pathlib import Path


class WeakIds:
    def __init__(self):
        self.items = {}
        self.next_id = 1

    def get(self, value):
        if value is None:
            return None
        key = id(value)
        previous = self.items.get(key)
        if previous is not None and previous[0]() is value:
            return previous[1]
        try:
            ref = weakref.ref(value, lambda departed, key=key: self.remove(key, departed))
        except TypeError:
            return None
        number = self.next_id
        self.next_id += 1
        self.items[key] = (ref, number)
        return number

    def remove(self, key, departed):
        previous = self.items.get(key)
        if previous is not None and previous[0] is departed:
            self.items.pop(key, None)


class PoolBoundaryObserver:
    MAX_EVENTS = 250_000
    MAX_COSTS = 510_000
    MAX_TICKS = 9_000
    MAX_SECONDS = 180
    TICK_SECONDS = 0.020

    def __init__(self, engine, output=None):
        self.engine = engine
        self.pool = engine.sync_engine.pool
        self.adapter_queue = self.pool._pool
        self.output = Path(output) if output is not None else None
        self.ids = WeakIds()
        self.events = []
        self.costs = []
        self.ticks = []
        self.restore = []
        self.listeners = []
        self.pending = weakref.WeakKeyDictionary()
        self.drivers = weakref.WeakSet()
        self.control = contextvars.ContextVar("r9_control", default=None)
        self.stack = contextvars.ContextVar("r9_stack", default=())
        self.external_request = lambda: None
        self.installed = False
        self.closed = False
        self.timer = None
        self.timer_loop = None
        self.sampler_start = None
        self.integrity = {
            "dropped": 0,
            "late": 0,
            "callback_errors": 0,
            "unmapped_wake": 0,
            "unweak_resource": 0,
            "sampler_limit": False,
            "costs_dropped": 0,
        }

    @contextlib.contextmanager
    def scope(self, label):
        if not isinstance(label, str) or not 0 < len(label) <= 128:
            raise ValueError("bounded synthetic control label required")
        token = self.control.set(label)
        try:
            yield self
        finally:
            self.control.reset(token)

    def request(self):
        control = self.control.get()
        if control is not None:
            return control, False
        current = self.external_request()
        if current is None:
            return None, False
        return current["request_id"], bool(current["closed"])

    def resource(self, value):
        number = self.ids.get(value)
        if number is not None or value is None:
            return number, "object"
        # Some installed DBAPI adapter facades have slots without weakref.
        # Alias only to their genuine weak driver, and label that identity.
        driver = getattr(value, "_connection", None)
        if driver is not None:
            return self.ids.get(driver), "driver"
        return None, "unknown"

    def begin(self, name, resource=None, request_override=None, **extra):
        cost_start = time.perf_counter_ns()
        try:
            request, late = self.request()
            request_origin = "current"
            if request is None and request_override is not None:
                request = request_override
                request_origin = "getter"
            if request is None:
                return None
            if self.closed or late:
                self.integrity["late"] += 1
            if len(self.events) >= self.MAX_EVENTS:
                self.integrity["dropped"] += 1
                return None
            task = asyncio.current_task()
            resource_id, resource_kind = self.resource(resource)
            if resource is not None and resource_id is None:
                self.integrity["unweak_resource"] += 1
            record = {
                "span_id": len(self.events),
                "name": name,
                "request_id": request,
                "request_origin": request_origin,
                "task_id": self.ids.get(task),
                "resource_id": resource_id,
                "resource_kind": resource_kind,
                "parent_ids": list(self.stack.get()),
                "start_ns": time.perf_counter_ns(),
                "end_ns": None,
                "error_type": None,
                "late": self.closed or late,
                **extra,
            }
            self.events.append(record)
            self.start_sampler()
            return record
        except Exception:
            self.integrity["callback_errors"] += 1
            return None
        finally:
            self.record_cost(time.perf_counter_ns() - cost_start)

    def record_cost(self, duration):
        if len(self.costs) < self.MAX_COSTS:
            self.costs.append(duration)
        else:
            self.integrity["costs_dropped"] += 1

    def recording(self, operation, default=None):
        try:
            return operation()
        except BaseException:
            # Only synchronous observer work enters here. NEVER the original
            # delegate or its await; original cancellation remains authoritative.
            self.integrity["callback_errors"] += 1
            return default

    def finish(self, record, error=None, result=None):
        cost_start = time.perf_counter_ns()
        try:
            if record is not None:
                record["end_ns"] = time.perf_counter_ns()
                record["error_type"] = type(error).__name__ if error is not None else None
                record["result_resource_id"], record["result_resource_kind"] = self.resource(result)
                request, late = self.request()
                if (
                    self.closed
                    or late
                    or (record["request_origin"] == "current" and request != record["request_id"])
                ):
                    record["late"] = True
                    self.integrity["late"] += 1
        except Exception:
            self.integrity["callback_errors"] += 1
        finally:
            self.record_cost(time.perf_counter_ns() - cost_start)

    def sync(self, original, name, accepts=lambda instance: True, result_hook=None):
        @functools.wraps(original)
        def wrapped(instance, *args, **kwargs):
            if not self.recording(lambda: accepts(instance), False):
                return original(instance, *args, **kwargs)
            record = self.recording(lambda: self.begin(name, instance))
            token = (
                self.recording(lambda: self.stack.set((*self.stack.get(), record["span_id"])))
                if record
                else None
            )
            error, result = None, None
            try:
                result = original(instance, *args, **kwargs)
                if result_hook is not None:
                    self.recording(lambda: result_hook(result))
                return result
            except BaseException as caught:
                error = caught
                raise
            finally:
                self.recording(lambda: self.finish(record, error, result))
                if token is not None:
                    self.recording(lambda: self.stack.reset(token))

        return wrapped

    def asynchronous(self, original, name, accepts=lambda instance: True):
        @functools.wraps(original)
        async def wrapped(instance, *args, **kwargs):
            if not self.recording(lambda: accepts(instance), False):
                return await original(instance, *args, **kwargs)

            def captured():
                owner = getattr(instance, "request_owner", None)
                if owner is None and hasattr(instance, "terminal_task"):
                    owner = instance
                if owner is None:
                    return {}
                return {
                    "owner_task_id": self.ids.get(owner.task),
                    "terminal_task_id": self.ids.get(owner.terminal_task),
                    "captured_resource_id": self.ids.get(args[0]) if args else None,
                }

            extra = self.recording(captured, {})
            record = self.recording(lambda: self.begin(name, instance, **extra))
            token = (
                self.recording(lambda: self.stack.set((*self.stack.get(), record["span_id"])))
                if record
                else None
            )
            error, result = None, None
            try:
                result = await original(instance, *args, **kwargs)
                return result
            except BaseException as caught:
                error = caught
                raise
            finally:
                self.recording(lambda: self.finish(record, error, result))
                if token is not None:
                    self.recording(lambda: self.stack.reset(token))

        return wrapped

    def patch(self, target, name, replacement):
        """Store raw descriptors, including absence on an inherited attribute."""
        original = vars(target).get(name)
        present = name in vars(target)
        self.restore.append((target, name, present, original))
        setattr(target, name, replacement)

    def target_queue(self, queue):
        # Do not evaluate the memoized property during installation.
        return vars(self.adapter_queue).get("_queue") is queue

    def target_connection(self, connection):
        return connection.engine.sync_engine is self.engine.sync_engine

    def target_session(self, session):
        bind = session.sync_session.bind
        return (
            bind is self.engine.sync_engine
            or getattr(bind, "engine", None) is self.engine.sync_engine
        )

    def remember_record(self, record):
        dbapi = getattr(record, "dbapi_connection", None)
        self.remember_adapter(dbapi)

    def remember_adapter(self, adapter):
        driver = getattr(adapter, "_connection", None)
        if driver is not None:
            self.drivers.add(driver)

    def target_adapter(self, adapter):
        return getattr(adapter, "_connection", None) in self.drivers

    def start_sampler(self):
        if self.timer_loop is not None or self.closed:
            return
        self.timer_loop = asyncio.get_running_loop()
        self.sampler_start = time.perf_counter_ns()
        self.schedule_tick()

    def schedule_tick(self):
        expected = time.perf_counter_ns() + int(self.TICK_SECONDS * 1e9)
        self.timer = self.timer_loop.call_later(self.TICK_SECONDS, self.tick, expected)

    def tick(self, expected):
        self.recording(lambda: self.record_tick(expected))

    def record_tick(self, expected):
        cost_start = time.perf_counter_ns()
        self.timer = None
        if self.closed:
            return
        actual = time.perf_counter_ns()
        self.ticks.append({"scheduled_ns": expected, "actual_ns": actual})
        elapsed = (actual - self.sampler_start) / 1e9
        if len(self.ticks) >= self.MAX_TICKS or elapsed >= self.MAX_SECONDS:
            self.integrity["sampler_limit"] = True
        else:
            self.schedule_tick()
        self.record_cost(time.perf_counter_ns() - cost_start)

    def install(self):
        from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection
        from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
        from sqlalchemy.pool.base import _ConnectionRecord
        from sqlalchemy.util.queue import AsyncAdaptedQueue

        from rtr_copilot.actions.request_connection import RequestConnection

        if self.installed or self.closed:
            raise RuntimeError("observer lifecycle is once-only")
        try:
            from phase_profiler import active
        except ImportError:
            pass
        else:
            self.external_request = active.get
        self.installed = True
        for name in ("connect", "_do_get", "_create_connection"):
            bound = getattr(self.pool, name)

            def delegate(instance, *args, _original=bound, **kwargs):
                return _original(*args, **kwargs)

            wrapped = self.sync(delegate, "pool." + name, result_hook=self.remember_record)
            self.patch(self.pool, name, functools.partial(wrapped, self.pool))
        for name in ("get", "get_nowait", "put_nowait"):
            original = getattr(AsyncAdaptedQueue, name)
            self.patch(
                AsyncAdaptedQueue,
                name,
                self.sync(
                    original, "adapter_queue." + name, lambda item: item is self.adapter_queue
                ),
            )
        original_get = asyncio.Queue.get

        @functools.wraps(original_get)
        async def queue_get(queue, *args, **kwargs):
            if not self.recording(lambda: self.target_queue(queue), False):
                return await original_get(queue, *args, **kwargs)
            task = asyncio.current_task()
            record = self.recording(lambda: self.begin("queue.get", queue))
            self.recording(lambda: self.pending.__setitem__(task, record))
            token = (
                self.recording(lambda: self.stack.set((*self.stack.get(), record["span_id"])))
                if record
                else None
            )
            error, result = None, None
            try:
                result = await original_get(queue, *args, **kwargs)
                return result
            except BaseException as caught:
                error = caught
                raise
            finally:
                self.recording(lambda: self.pending.pop(task, None))
                self.recording(lambda: self.finish(record, error, result))
                if token is not None:
                    self.recording(lambda: self.stack.reset(token))

        self.patch(asyncio.Queue, "get", queue_get)
        self.patch(
            asyncio.Queue,
            "get_nowait",
            self.sync(asyncio.Queue.get_nowait, "queue.get_nowait", self.target_queue),
        )
        original_wake = asyncio.Queue._wakeup_next

        @functools.wraps(original_wake)
        def wake(queue, waiters):
            if not self.recording(
                lambda: self.target_queue(queue) and waiters is queue._getters, False
            ):
                return original_wake(queue, waiters)

            def details():
                future = next((item for item in waiters if not item.done()), None)
                matches = [
                    (task, record)
                    for task, record in list(self.pending.items())
                    if future is not None and getattr(task, "_fut_waiter", None) is future
                ]
                getter, pending = matches[0] if len(matches) == 1 else (None, None)
                if future is not None and len(matches) != 1:
                    self.integrity["unmapped_wake"] += 1
                return future, {
                    "request_override": pending["request_id"] if pending is not None else None,
                    "producer_request_id": self.request()[0],
                    "future_id": self.ids.get(future),
                    "getter_task_id": self.ids.get(getter),
                    "getter_span_id": pending["span_id"] if pending is not None else None,
                    "getter_request_id": pending["request_id"] if pending is not None else None,
                    "mapping": "unique" if len(matches) == 1 else "unknown",
                }

            future, metadata = self.recording(details, (None, {"mapping": "unknown"}))
            record = self.recording(lambda: self.begin("queue.wake_ready", queue, **metadata))
            error = None
            try:
                return original_wake(queue, waiters)
            except BaseException as caught:
                error = caught
                raise
            finally:

                def ready():
                    if record is not None:
                        record["future_ready"] = future.done() if future is not None else None

                self.recording(ready)
                self.recording(lambda: self.finish(record, error))

        self.patch(asyncio.Queue, "_wakeup_next", wake)
        self.patch(
            _ConnectionRecord,
            "get_connection",
            self.sync(
                _ConnectionRecord.get_connection,
                "record.get_connection",
                lambda item: item._ConnectionRecord__pool is self.pool,
                self.remember_adapter,
            ),
        )
        for name in ("_async_ping", "_commit_and_discard", "_rollback_and_discard"):
            self.patch(
                AsyncAdapt_asyncpg_connection,
                name,
                self.asynchronous(
                    getattr(AsyncAdapt_asyncpg_connection, name),
                    "adapter." + name,
                    self.target_adapter,
                ),
            )
        for cls, predicate in (
            (AsyncSession, self.target_session),
            (AsyncConnection, self.target_connection),
        ):
            for name in ("close", "invalidate"):
                self.patch(
                    cls,
                    name,
                    self.asynchronous(getattr(cls, name), cls.__name__ + "." + name, predicate),
                )
        for name in (
            "join_terminal",
            "close_connection",
            "_close_retained",
            "release_phase",
            "_release_retained",
        ):
            self.patch(
                RequestConnection,
                name,
                self.asynchronous(
                    getattr(RequestConnection, name),
                    "owner." + name,
                    lambda owner: owner.engine is self.engine,
                ),
            )

    def snapshot(self):
        # Detached JSON-shaped copy, no Task/Future/Connection references.
        return json.loads(
            json.dumps(
                {
                    "events": self.events,
                    "costs": self.costs,
                    "ticks": self.ticks,
                    "integrity": {
                        **self.integrity,
                        "late_events": sum(item["late"] for item in self.events),
                        "open_events": sum(item["end_ns"] is None for item in self.events),
                        "pending_getters": len(self.pending),
                        "timer_active": self.timer is not None,
                    },
                }
            )
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        for target, name, present, original in reversed(self.restore):
            if present:
                setattr(target, name, original)
            else:
                delattr(target, name)
        self.restore.clear()
        if self.output is not None:
            payload = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":")).encode()
            if len(payload) > 128 * 1024 * 1024:
                raise ValueError("bounded observer output exceeded")
            with (self.output / "pool-boundaries.json").open("xb") as stream:
                stream.write(payload)
