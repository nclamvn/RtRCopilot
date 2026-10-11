"""Four independent structural observer controls, not physical SQL proofs."""

import asyncio
import inspect
from collections import deque
from types import SimpleNamespace
from typing import Any

import pytest
from pool_boundary_observer import PoolBoundaryObserver


class Resource:
    pass


def observer() -> Any:
    adapter = SimpleNamespace()
    pool = SimpleNamespace(_pool=adapter)
    return PoolBoundaryObserver(SimpleNamespace(sync_engine=SimpleNamespace(pool=pool)))


@pytest.mark.asyncio
async def test_raw_descriptors_preserve_binding_and_exact_restore() -> None:
    seen: list[Any] = []
    result = Resource()

    class Parent:
        @classmethod
        def checkout(cls: Any, value: Any, *, option: Any) -> Any:
            seen.append((cls, value, option))
            return result

        @staticmethod
        def bridge(value: Any) -> Any:
            seen.append(value)
            return result

    class Child(Parent):
        pass

    probe = observer()
    raw_class = inspect.getattr_static(Parent, "checkout")
    raw_static = inspect.getattr_static(Parent, "bridge")
    probe.patch(Child, "checkout", classmethod(probe.sync(raw_class.__func__, "control.checkout")))
    probe.patch(Parent, "bridge", staticmethod(probe.sync(raw_static.__func__, "control.bridge")))
    argument, option = Resource(), Resource()
    try:
        with probe.scope("descriptor-control"):
            assert Child.checkout(argument, option=option) is result
            assert Parent.bridge(argument) is result
        assert seen == [(Child, argument, option), argument]
        assert "checkout" in vars(Child)
        assert inspect.getattr_static(Parent, "bridge").__func__.__wrapped__ is raw_static.__func__
    finally:
        probe.close()
    assert "checkout" not in vars(Child)
    assert inspect.getattr_static(Child, "checkout") is raw_class
    assert inspect.getattr_static(Parent, "bridge") is raw_static
    assert Child.checkout(argument, option=option) is result


@pytest.mark.asyncio
async def test_original_error_and_cancellation_survive_observer_failures(
    monkeypatch: Any,
) -> None:
    probe = observer()
    owner = SimpleNamespace(task=asyncio.current_task(), terminal_task=None)
    resource = Resource()
    resource.request_owner = owner
    actual_calls: list[Any] = []
    marker, cancellation = ValueError("delegate-marker"), asyncio.CancelledError("delegate-cancel")

    async def original(instance: Any, outcome: Any, *, option: Any) -> Any:
        actual_calls.append((instance, outcome, option))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def broken_ids(value: Any) -> Any:
        raise RuntimeError("recorder-only-fault")

    monkeypatch.setattr(probe.ids, "get", broken_ids)
    wrapped = probe.asynchronous(original, "control.original")
    value, option = Resource(), Resource()
    try:
        with probe.scope("original-outcome-control"):
            assert await wrapped(resource, value, option=option) is value
            with pytest.raises(ValueError) as caught:
                await wrapped(resource, marker, option=option)
            assert caught.value is marker
            with pytest.raises(asyncio.CancelledError) as cancelled:
                await wrapped(resource, cancellation, option=option)
            assert cancelled.value is cancellation
        assert actual_calls == [
            (resource, value, option),
            (resource, marker, option),
            (resource, cancellation, option),
        ]
        assert probe.snapshot()["integrity"]["callback_errors"] >= 3
    finally:
        probe.close()


@pytest.mark.asyncio
async def test_wakeup_requires_exact_future_getter_mapping() -> None:
    """Actual asyncio waiter; no database, record reservation or HTTP inference."""
    probe = observer()
    queue = asyncio.Queue()
    probe.adapter_queue._queue = queue
    pool = probe.pool
    pool.connect = lambda: None
    pool._do_get = lambda: None
    pool._create_connection = lambda: None
    probe.install()
    waiter = None
    token = Resource()

    async def get() -> Any:
        with probe.scope("consumer-control"):
            return await queue.get()

    try:
        waiter = asyncio.create_task(get())
        async with asyncio.timeout(2):
            while not queue._getters:
                await asyncio.sleep(0)
        future = queue._getters[0]
        assert getattr(waiter, "_fut_waiter", None) is future
        with probe.scope("producer-control"):
            queue.put_nowait(token)
        assert await waiter is token
        wakes = [item for item in probe.snapshot()["events"] if item["name"] == "queue.wake_ready"]
        mapped = next(item for item in wakes if item["future_id"] == probe.ids.get(future))
        assert mapped["mapping"] == "unique" and mapped["future_ready"]
        assert mapped["getter_task_id"] == probe.ids.get(waiter)
        assert mapped["task_id"] == probe.ids.get(asyncio.current_task())
        assert mapped["task_id"] != mapped["getter_task_id"]
        assert mapped["getter_request_id"] == "consumer-control"
        assert mapped["request_id"] == "producer-control"
        assert "reserved_record_id" not in mapped

        unknown = asyncio.get_running_loop().create_future()
        waiters = deque([unknown])
        queue._getters = waiters
        with probe.scope("unknown-producer-control"):
            queue._wakeup_next(waiters)
        assert unknown.done() and not waiters
        unmapped = probe.snapshot()["events"][-1]
        assert unmapped["mapping"] == "unknown"
        assert unmapped["getter_task_id"] is None and unmapped["getter_request_id"] is None
        assert probe.snapshot()["integrity"]["unmapped_wake"] == 1
    finally:
        if waiter is not None and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        probe.close()


@pytest.mark.asyncio
async def test_captured_terminal_mapping_and_late_events_do_not_rebind() -> None:
    probe = observer()
    captured, replacement = Resource(), Resource()
    owner = Resource()
    owner.task = asyncio.current_task()
    owner.terminal_task = None
    owner.connection = captured
    ready, release = asyncio.Event(), asyncio.Event()
    delegated: list[Any] = []

    async def original(instance: Any, resource: Any) -> Any:
        delegated.append(resource)
        instance.connection = replacement
        ready.set()
        await release.wait()
        return resource

    wrapped = probe.asynchronous(original, "control.captured_close")
    child = None
    try:
        with probe.scope("captured-control"):
            child = asyncio.create_task(wrapped(owner, captured))
            await ready.wait()
            owner.terminal_task = child
            owner.connection = replacement
            record = probe.snapshot()["events"][0]
            assert record["captured_resource_id"] == probe.ids.get(captured)
            assert record["captured_resource_id"] != probe.ids.get(owner.connection)
            assert record["owner_task_id"] == probe.ids.get(owner.task)
            assert record["task_id"] == probe.ids.get(child)
            release.set()
            assert await child is captured
        assert delegated == [captured]
        ended = probe.snapshot()["events"][0]
        assert ended["end_ns"] >= ended["start_ns"] and ended["error_type"] is None
        assert ended["result_resource_id"] == probe.ids.get(captured)
        probe.close()
        with probe.scope("late-control"):
            late = probe.begin("control.late", replacement)
            probe.finish(late)
        assert probe.snapshot()["integrity"]["late"] >= 1 and late["late"]
        probe.MAX_EVENTS = len(probe.events)
        with probe.scope("dropped-control"):
            assert probe.begin("control.dropped", captured) is None
        assert probe.snapshot()["integrity"]["dropped"] == 1
    finally:
        release.set()
        if child is not None and not child.done():
            await asyncio.gather(child, return_exceptions=True)
        probe.close()
