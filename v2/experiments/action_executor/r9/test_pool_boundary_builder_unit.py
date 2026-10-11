"""Twelve structural control groups, not database or HTTP acceptance."""

import asyncio
import gc
import weakref
from types import SimpleNamespace

import pytest
from analyze import validate_boundaries
from pool_boundary_observer import PoolBoundaryObserver, WeakIds


class Pool:
    def __init__(self):
        self._pool = SimpleNamespace()

    def connect(self):
        return self

    def _do_get(self):
        return self

    def _create_connection(self):
        return self


def observer():
    return PoolBoundaryObserver(SimpleNamespace(sync_engine=SimpleNamespace(pool=Pool())))


@pytest.mark.asyncio
async def test_sync_arguments_and_exact_result():
    probe, result, calls = observer(), object(), []

    def original(instance, *args, **kwargs):
        calls.append((instance, args, kwargs))
        return result

    owner = SimpleNamespace()
    with probe.scope("B01"):
        assert probe.sync(original, "sync")(owner, 3, flag=7) is result
    assert calls == [(owner, (3,), {"flag": 7})]
    assert probe.events[0]["end_ns"] is not None
    probe.close()


@pytest.mark.asyncio
async def test_async_exact_delegate_once():
    probe, result, calls = observer(), object(), []

    async def original(instance, value):
        calls.append(value)
        return result

    with probe.scope("B02"):
        assert await probe.asynchronous(original, "async")(object(), 5) is result
    assert calls == [5]
    probe.close()


@pytest.mark.asyncio
async def test_original_exception_survives_recording_fault():
    probe, failure = observer(), ValueError("original")

    def broken(value):
        raise RuntimeError("recording only")

    def original(instance):
        raise failure

    probe.ids.get = broken
    with probe.scope("B03"), pytest.raises(ValueError) as caught:
        probe.sync(original, "error")(object())
    assert caught.value is failure and probe.integrity["callback_errors"] > 0
    probe.close()


@pytest.mark.asyncio
async def test_original_cancellation_survives_preparation_fault():
    probe, failure, calls = observer(), asyncio.CancelledError("original"), []

    async def original(instance):
        calls.append(1)
        raise failure

    def broken():
        raise RuntimeError("request recording only")

    probe.request = broken
    with pytest.raises(asyncio.CancelledError) as caught:
        await probe.asynchronous(original, "cancel")(object())
    assert caught.value is failure and calls == [1]
    probe.close()


def test_raw_descriptor_and_inherited_absence_restoration():
    probe = observer()

    class Parent:
        @classmethod
        def inherited(cls):
            return cls

    class Child(Parent):
        @staticmethod
        def direct():
            return 11

    descriptor = vars(Child)["direct"]
    probe.patch(Child, "direct", staticmethod(lambda: 13))
    probe.patch(Child, "inherited", classmethod(lambda cls: (cls, 17)))
    assert Child.direct() == 13 and Child.inherited() == (Child, 17)
    probe.close()
    assert vars(Child)["direct"] is descriptor and "inherited" not in vars(Child)
    assert Child.direct() == 11 and Child.inherited() is Child


@pytest.mark.asyncio
async def test_foreign_target_has_no_observation_but_delegates():
    probe, calls = observer(), []

    def original(instance):
        calls.append(instance)
        return 19

    with probe.scope("B06"):
        assert probe.sync(original, "foreign", lambda item: False)(object()) == 19
    assert len(calls) == 1 and probe.events == []
    probe.close()


def test_install_does_not_force_lazy_queue():
    probe = observer()
    assert "_queue" not in vars(probe.adapter_queue)
    probe.install()
    try:
        assert "_queue" not in vars(probe.adapter_queue)
    finally:
        probe.close()


def test_weak_id_has_no_strong_lifetime_or_reactivation():
    ids = WeakIds()

    class Resource:
        pass

    resource = Resource()
    first = ids.get(resource)
    reference = weakref.ref(resource)
    assert ids.get(resource) == first
    del resource
    gc.collect()
    assert reference() is None and not ids.items
    replacement = Resource()
    assert ids.get(replacement) > first


@pytest.mark.asyncio
async def test_nested_spans_and_tasks_not_summed_or_collapsed():
    probe = observer()

    async def inner(instance):
        return 23

    delegated = probe.asynchronous(inner, "inner")

    async def outer(instance):
        return await asyncio.create_task(delegated(instance))

    with probe.scope("B09"):
        assert await probe.asynchronous(outer, "outer")(object()) == 23
    parent, child = probe.events
    assert child["parent_ids"] == [parent["span_id"]]
    assert child["task_id"] != parent["task_id"]
    assert parent["start_ns"] <= child["start_ns"] <= child["end_ns"] <= parent["end_ns"]
    probe.close()


@pytest.mark.asyncio
async def test_wake_without_pending_match_is_unknown_not_assignment():
    probe = observer()
    queue = asyncio.Queue()
    probe.adapter_queue._queue = queue
    probe.install()
    try:
        future = asyncio.get_running_loop().create_future()
        queue._getters.append(future)
        with probe.scope("B10"):
            queue.put_nowait(object())
        wake = next(item for item in probe.events if item["name"] == "queue.wake_ready")
        assert future.done() and wake["mapping"] == "unknown"
        assert wake["getter_task_id"] is None and "reserved_record_id" not in wake
        assert probe.integrity["unmapped_wake"] == 1
    finally:
        probe.close()


@pytest.mark.asyncio
async def test_open_late_drop_and_cost_bounds_are_explicit():
    probe = observer()
    probe.MAX_EVENTS, probe.MAX_COSTS = 1, 1
    with probe.scope("B11"):
        opened = probe.begin("open")
        assert probe.begin("dropped") is None
    snapshot = probe.snapshot()
    assert opened["end_ns"] is None and snapshot["integrity"]["open_events"] == 1
    assert snapshot["integrity"]["dropped"] == 1
    probe.close()
    with probe.scope("B11"):
        probe.finish(opened)
    assert probe.integrity["late"] > 0 and probe.integrity["costs_dropped"] > 0
    # Same declared B11 group: an unwired observer cannot call absence a pass.
    expected = [
        {
            "request_id": "B11",
            "pool": [
                {
                    "kind": "connect",
                    "end_ns": 5,
                    "error_type": None,
                }
            ],
        }
    ]
    with pytest.raises(ValueError, match="completeness"):
        validate_boundaries(expected, [])


@pytest.mark.asyncio
async def test_sampler_exact_handle_is_cancelled_and_bounded():
    probe = observer()
    with probe.scope("B12"):
        probe.begin("sampler")
    handle = probe.timer
    assert handle is not None and not handle.cancelled()
    probe.MAX_TICKS = 1
    probe.tick(probe.sampler_start)
    assert probe.integrity["sampler_limit"] and len(probe.ticks) == 1
    # Explicit tick simulates the scheduled callback; keep its original handle
    # owned until cancellation, rather than leave this structural fixture live.
    handle.cancel()
    probe.close()
    assert handle.cancelled() and probe.snapshot()["integrity"]["timer_active"] is False
