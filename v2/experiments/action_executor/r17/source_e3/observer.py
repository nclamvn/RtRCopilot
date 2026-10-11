"""Scoped diagnostic wrappers. Minimal mode installs ONLY the immutable R15 observer."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar

from diagnostic import Collector


class TerminalTasks:
    """Observe existing terminal tasks; never change their caller's result or timer."""

    def __init__(self):
        self.tasks = set()
        self.active = {}

    def observe(self):
        task = asyncio.current_task()
        if task is not None:
            self.tasks.add(task)
            self.active[task] = self.active.get(task, 0) + 1
        return task

    def finished(self, task):
        if task is not None:
            count = self.active[task] - 1
            if count:
                self.active[task] = count
            else:
                self.active.pop(task)

    async def drain(self, pool=None):
        owner = asyncio.current_task()
        close_code = None
        legacy_children = set()
        if pool is not None:
            from sqlalchemy.ext.asyncio import AsyncSession

            close_code = AsyncSession.close.__code__

        def known_legacy_children():
            if close_code is None:
                return
            for task in asyncio.all_tasks():
                coroutine = task.get_coro()
                if getattr(coroutine, "cr_code", None) is not close_code:
                    continue
                frame = coroutine.cr_frame
                session = frame.f_locals.get("self") if frame is not None else None
                if getattr(getattr(session, "bind", None), "pool", None) is pool:
                    self.tasks.add(task)
                    legacy_children.add(task)

        async def settle():
            # A shielded Session.close child may still be awaiting its first turn.
            await asyncio.sleep(0)
            known_legacy_children()
            while pending := [
                task
                for task in self.tasks
                if task is not owner
                and not task.done()
                and (task in legacy_children or task in self.active)
            ]:
                await asyncio.gather(*pending, return_exceptions=True)
                await asyncio.sleep(0)
                known_legacy_children()
            for task in self.tasks:
                if task is not owner and task.done() and not task.cancelled():
                    task.exception()  # Preserve the original task result; retrieve child faults.
            self.tasks.clear()
            self.active.clear()

        joined = asyncio.create_task(settle())
        cancellation = None
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError as error:
                cancellation = error
        joined.result()
        if cancellation is not None:
            raise cancellation


class Lifecycle:
    """Object identities stay internal; exported monotonic IDs are not addresses."""

    def __init__(self, collector, pool, tag):
        self.collector, self.pool, self.tag = collector, pool, tag
        self.records = {}
        self.physical = {}
        self.held = {}
        self.returning = {}
        self.generation = 0

    def record(self, record):
        if record not in self.records:
            self.records[record] = len(self.records) + 1
        return self.records[record]

    def snapshot(self):
        return dict(
            held_ledger=len(self.held),
            pool_checkedout=self.pool.checkedout(),
            pool_checkedin=self.pool.checkedin(),
            pool_overflow=self.pool.overflow(),
        )

    def created(self, record):
        self.generation += 1
        self.physical[record] = (self.generation, self.tag())
        self.collector.emit(
            self.tag(),
            "connect_observed",
            record=self.record(record),
            generation=self.generation,
            origin="created_during_observation",
        )

    def identity(self, record):
        generation, creator = self.physical.get(record, (None, None))
        return dict(
            record=self.record(record),
            generation=generation,
            origin="created_during_observation" if generation else "unknown_pre_observation",
            created_by=creator,
        )

    def checkout(self, dbapi, record, proxy):
        tag = self.tag()
        if tag is None:
            return
        if record in self.held:
            self.collector.fault("duplicate_checkout")
        self.held[record] = tag
        self.collector.emit(tag, "checkout", **self.identity(record), **self.snapshot())

    def checkin(self, dbapi, record):
        owned = self.held.pop(record, None)
        tag = owned or self.tag()
        self.returning[record] = tag
        self.collector.emit(
            tag,
            "checkin_callback",
            **self.identity(record),
            owned_checkout=owned is not None,
            availability="not_yet_pool_return",
            **self.snapshot(),
        )

    def invalidate(self, dbapi, record, exception):
        tag = self.held.get(record) or self.tag()
        self.collector.emit(tag, "invalidate", **self.identity(record))
        self.physical.pop(record, None)


class Observation:
    """R15 aggregate observer stays exactly same-source in both modes."""

    def __init__(self, engine, collector=None):
        # Runtime-only imports keep eight offline controls stdlib-only.
        from test_standard_status_comparator import TAG
        from test_standard_status_comparator import Observation as Aggregate

        self.aggregate = Aggregate(engine)
        self.engine = engine
        self.collector = collector or Collector()
        self.tag = TAG
        self.lifecycle = Lifecycle(self.collector, engine.pool, TAG.get)
        self.objects = {}
        self.query_spans = {}
        self.nesting = ContextVar("r17_terminal_nesting", default=frozenset())
        self.installed = []
        self.terminals = TerminalTasks()

    def resolve(self, obj):
        if obj in self.objects:
            return self.objects[obj]
        current = self.tag.get()
        if current is not None:
            self.objects[obj] = current
            return current
        return self.objects.get(obj)

    @contextmanager
    def watching(self, mode):
        if mode not in ("M", "D"):
            raise ValueError("mode")
        with self.aggregate.watching():
            if mode == "M":
                # Crucially no detailed monkeypatch or listener is installed here.
                yield self
            else:
                with self.detailed():
                    yield self

    @contextmanager
    def detailed(self):
        from sqlalchemy import event
        from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
        from sqlalchemy.pool.base import _ConnectionRecord

        from rtr_copilot.actions.request_connection import RequestConnection, _OwnerConnection

        collector, ledger, pool = self.collector, self.lifecycle, self.engine.pool
        # Creations/reconnects during intervening minimal exposure are not observed.
        ledger.physical.clear()
        original_connect = pool.connect
        original_return = pool._return_conn
        original_create = _ConnectionRecord._ConnectionRecord__connect
        local_attributes = {name: pool.__dict__.get(name) for name in ("connect", "_return_conn")}
        existed = {name: name in pool.__dict__ for name in local_attributes}
        patches = []
        listeners = []

        def connect(*args, **kwargs):
            tag = self.tag.get()
            span = collector.begin(tag, "acquisition", **ledger.snapshot())
            try:
                result = original_connect(*args, **kwargs)
            except BaseException as error:
                collector.end(tag, "acquisition", span, error, **ledger.snapshot())
                raise
            collector.end(
                tag,
                "acquisition",
                span,
                **ledger.identity(result._connection_record),
                **ledger.snapshot(),
            )
            return result

        def return_conn(record, *args, **kwargs):
            # checkin callback removed ledger already; tag is inherited by child cleanup.
            tag = ledger.returning.pop(record, None) or self.tag.get()
            result = original_return(record, *args, **kwargs)
            collector.emit(
                tag, "pool_return_complete", **ledger.identity(record), **ledger.snapshot()
            )
            return result

        def create(record, *args, **kwargs):
            if record._ConnectionRecord__pool is not pool:
                return original_create(record, *args, **kwargs)
            tag = self.tag.get()
            ledger.physical.pop(record, None)
            span = collector.begin(tag, "connect", record=ledger.record(record), generation=None)
            try:
                result = original_create(record, *args, **kwargs)
            except BaseException as error:
                collector.end(
                    tag, "connect", span, error, record=ledger.record(record), generation=None
                )
                raise
            # connect listener observes successful physical identity before checkout.
            collector.end(tag, "connect", span, **ledger.identity(record))
            return result

        def connected(dbapi, record):
            ledger.created(record)

        def before(connection, cursor, statement, parameters, context, executemany):
            tag = self.tag.get()
            if tag is None:
                return
            kind = (
                "row"
                if "SELECT e.*,r.plan_id" in statement
                else "receipt"
                if "FROM action_execution_receipts c" in statement
                else "authority"
                if "security_version" in statement
                else "other"
            )
            span = collector.begin(tag, "query", classification=kind)
            self.query_spans[context] = (tag, span, kind)

        def after(connection, cursor, statement, parameters, context, executemany):
            owned = self.query_spans.pop(context, None)
            if owned:
                tag, span, kind = owned
                collector.end(tag, "query", span, classification=kind)

        def error(context):
            owned = self.query_spans.pop(context.execution_context, None)
            if owned:
                tag, span, kind = owned
                collector.end(tag, "query", span, context.original_exception, classification=kind)
            # Returning None preserves SQLAlchemy's original handling/exception.

        def wrap(cls, name, boundary):
            original = getattr(cls, name)
            own = name in cls.__dict__

            async def terminal(obj, *args, **kwargs):
                key = (boundary, name)
                nesting = self.nesting.get()
                tag = self.resolve(obj)
                if tag is None or key in nesting:
                    return await original(obj, *args, **kwargs)
                terminal_task = self.terminals.observe()
                token = self.nesting.set(nesting | {key})
                span = collector.begin(tag, boundary + "_" + name)
                try:
                    result = await original(obj, *args, **kwargs)
                except BaseException as fault:
                    collector.end(tag, boundary + "_" + name, span, fault)
                    raise
                else:
                    collector.end(tag, boundary + "_" + name, span)
                    return result
                finally:
                    self.terminals.finished(terminal_task)
                    self.nesting.reset(token)

            setattr(cls, name, terminal)
            patches.append((cls, name, original, own))

        def listen(name, callback):
            event.listen(self.engine.sync_engine, name, callback)
            listeners.append((name, callback))

        try:
            pool.connect = connect
            pool._return_conn = return_conn
            _ConnectionRecord._ConnectionRecord__connect = create
            for name, callback in (
                ("connect", connected),
                ("checkout", ledger.checkout),
                ("checkin", ledger.checkin),
                ("invalidate", ledger.invalidate),
                ("before_cursor_execute", before),
                ("after_cursor_execute", after),
                ("handle_error", error),
            ):
                listen(name, callback)
            # Subclass and base are covered with one nested span per physical operation.
            for cls, boundary in (
                (AsyncSession, "session_terminal"),
                (AsyncConnection, "physical_terminal"),
                (_OwnerConnection, "physical_terminal"),
            ):
                for name in ("close", "invalidate"):
                    wrap(cls, name, boundary)
            wrap(AsyncConnection, "start", "physical_setup")
            wrap(AsyncSession, "__aexit__", "session_terminal")
            for name in ("join_terminal", "release_phase", "close_connection"):
                wrap(RequestConnection, name, "owner_terminal")
            self.installed = ["Pool.connect", "record.__connect", "terminal", "query", "lifecycle"]
            yield self
        finally:
            # Caller must join all service/terminal children before exiting scope.
            if any(not task.done() for task in self.terminals.active):
                collector.fault("terminal_pending_on_restore")
            for cls, name, original, own in reversed(patches):
                if own:
                    setattr(cls, name, original)
                else:
                    delattr(cls, name)
            for name, callback in reversed(listeners):
                event.remove(self.engine.sync_engine, name, callback)
            _ConnectionRecord._ConnectionRecord__connect = original_create
            for name in local_attributes:
                if existed[name]:
                    setattr(pool, name, local_attributes[name])
                else:
                    pool.__dict__.pop(name, None)
            self.installed = []
            if self.query_spans:
                collector.fault("query_terminal_missing")
            if ledger.held:
                collector.fault("ledger_leak")

    def row(self, tag, mode):
        row = dict(self.aggregate.row(tag))
        row["detail_mode"] = mode == "D"
        row["detail_events"] = self.collector.counts.get(tag, 0)
        return row

    async def drain(self, mode="D"):
        """Called after service tasks join, while detailed wrappers remain installed."""
        # M has no wrapper: only exact AsyncSession.close coroutine/code + same
        # bound pool identifies a legacy child in this dedicated synthetic fixture.
        await self.terminals.drain(self.engine.pool if mode == "M" else None)
