"""Four independent structural controls; fakes are not SQL/runtime evidence."""

import asyncio
import copy
import gc
import inspect
import io
import json
import weakref
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

import pytest
from overhead_observer import FIELDS, ObserverExposure, decoded_records
from pool_boundary_observer import PoolBoundaryObserver


class Resource:
    pass


def reference_boundary() -> Any:
    adapter = SimpleNamespace()
    pool = SimpleNamespace(_pool=adapter)
    return PoolBoundaryObserver(SimpleNamespace(sync_engine=SimpleNamespace(pool=pool)))


def reject(packet: Any) -> None:
    with pytest.raises(ValueError):
        decoded_records(packet)


@pytest.mark.asyncio
async def test_preparation_boundaries_exclude_original_await_and_conserve_nested_masks() -> None:
    boundary, exposure = reference_boundary(), ObserverExposure()
    exposure.attach_boundary(boundary)
    entered, release = asyncio.Event(), asyncio.Event()
    token, resource = Resource(), Resource()
    calls: list[Any] = []

    async def delegate(instance: Any, value: Any, *, option: Any) -> Any:
        calls.append((instance, value, option))
        entered.set()
        await release.wait()  # Structural controlled delegate wait, NOT SQL.
        return value

    wrapped = boundary.asynchronous(delegate, "control.original_wait")
    task = None

    async def invoke() -> Any:
        with boundary.scope("r11-structural-await"), exposure.scope("r11-structural-await"):
            return await wrapped(resource, token, option=token)

    try:
        task = asyncio.create_task(invoke())
        await asyncio.wait_for(entered.wait(), 2)
        partial = exposure.snapshot()
        records = decoded_records(partial)
        assert records and all(row["end_ns"] is not None for row in records)
        assert all(row["label"].startswith("R9.") for row in records)
        assert not any(row["label"] == "control.original_wait" for row in records)
        original = next(
            row for row in boundary.snapshot()["events"] if row["name"] == "control.original_wait"
        )
        assert original["end_ns"] is None and not task.done()
        release.set()
        assert await task is token
        assert calls == [(resource, token, token)]
        nested: list[Any] = []
        with exposure.scope("r11-structural-masks"):

            def outer() -> None:
                exposure.measure(lambda: nested.append(True), "control.child")

            exposure.measure(outer, "control.outer")
        decoded = decoded_records(exposure.snapshot())
        parent = next(row for row in decoded if row["label"] == "control.outer")
        child = next(row for row in decoded if row["label"] == "control.child")
        assert child["parent_ids"] == [parent["span_id"]]
        assert parent["start_ns"] <= child["start_ns"] <= child["end_ns"] <= parent["end_ns"]
        inclusive = parent["end_ns"] - parent["start_ns"]
        child_wall = child["end_ns"] - child["start_ns"]
        exclusive = (child["start_ns"] - parent["start_ns"]) + (parent["end_ns"] - child["end_ns"])
        assert exclusive + child_wall == inclusive and nested == [True]
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        exposure.close()
        boundary.close()


@pytest.mark.asyncio
async def test_recording_faults_preserve_original_arguments_errors_and_binding(
    monkeypatch: Any,
) -> None:
    exposure = ObserverExposure()
    argument, option, result = Resource(), Resource(), Resource()
    marker, cancellation = ValueError("original-marker"), asyncio.CancelledError("original-cancel")
    seen: list[Any] = []

    def delegate(value: Any, *, original_kwarg: Any) -> Any:
        seen.append((value, original_kwarg))
        if isinstance(value, BaseException):
            raise value
        return result

    def recording_fault(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("new-recorder-only-fault")

    monkeypatch.setattr(exposure, "begin", recording_fault)
    with exposure.scope("r11-structural-recorder-fault"):
        assert (
            exposure.measure(delegate, "control.delegate", (argument,), {"original_kwarg": option})
            is result
        )
        with pytest.raises(ValueError) as caught:
            exposure.measure(delegate, "control.delegate", (marker,), {"original_kwarg": option})
        assert caught.value is marker
        with pytest.raises(asyncio.CancelledError) as cancelled:
            exposure.measure(
                delegate, "control.delegate", (cancellation,), {"original_kwarg": option}
            )
        assert cancelled.value is cancellation
    assert seen == [(argument, option), (marker, option), (cancellation, option)]
    assert exposure.snapshot()["integrity"]["callback_errors"] >= 3
    exposure.close()

    after = ObserverExposure()
    monkeypatch.setattr(after, "finish", recording_fault)
    final_calls: list[Any] = []

    def original_keywords(*, context: Any, source_line: Any) -> Any:
        final_calls.append((context, source_line))
        return result

    with after.scope("r11-structural-finish-fault"):
        assert (
            after.measure(
                original_keywords,
                "control.finish-fault",
                kwargs={
                    "context": argument,
                    "source_line": option,
                },
            )
            is result
        )
    assert final_calls == [(argument, option)]
    assert after.snapshot()["integrity"]["callback_errors"] == 1
    assert after.snapshot()["integrity"]["open"] == 1
    after.close()

    restored = ObserverExposure()
    bindings: list[Any] = []

    class Parent:
        @classmethod
        def route(cls: Any, value: Any, *, option: Any) -> Any:
            bindings.append((cls, value, option))
            return result

    class Child(Parent):
        pass

    raw = inspect.getattr_static(Parent, "route")

    def route(cls: Any, *args: Any, **kwargs: Any) -> Any:
        return restored.measure(raw.__func__, "control.classmethod", (cls, *args), kwargs)

    restored.patch(Child, "route", classmethod(route))
    with restored.scope("r11-structural-binding"):
        assert Child.route(argument, option=option) is result
    assert bindings == [(Child, argument, option)]
    restored.close()
    assert "route" not in vars(Child)
    assert inspect.getattr_static(Child, "route") is raw
    assert inspect.getattr_static(Parent, "route") is raw

    line_probe = ObserverExposure()
    source_calls: list[Any] = []
    module = SimpleNamespace(active=ContextVar("r11-line-fault", default=None), json=json)

    class Phase:
        stream = io.StringIO()

        @staticmethod
        def finish_phase(value: Any, request: Any) -> Any:
            source_calls.append((value, request))
            return result

    class Audit:
        stream = io.StringIO()

        def emit(self, record: Any) -> Any:
            source_calls.append(record)
            return result

    phase, audit = Phase(), Audit()
    audit_module = SimpleNamespace(json=json)
    line_probe.attach_phase(phase, module)
    line_probe.attach_audit(audit, audit_module)
    monkeypatch.setattr(line_probe, "line", recording_fault)
    record = {"request_id": "tip054-latency-1-4-submit", "closed": False}
    try:
        with line_probe.scope("r11-structural-source-line-fault"):
            assert phase.finish_phase(argument, record) is result
            assert audit.emit(record) is result
        assert source_calls == [(argument, record), record]
        assert line_probe.snapshot()["integrity"]["callback_errors"] == 2
    finally:
        line_probe.close()


@pytest.mark.asyncio
async def test_post_http_child_identity_is_captured_without_facade_retention() -> None:
    active = ContextVar("r11-structural-reference", default=None)
    module = SimpleNamespace(active=active, json=json)

    class Reference:
        @staticmethod
        def finish_phase(_phase: Any, _request: Any) -> None:
            return None

        def __init__(self) -> None:
            self.stream = io.StringIO()

    exposure = ObserverExposure()
    reference = Reference()
    exposure.attach_phase(reference, module)
    original_json = json.dumps
    original = {"request_id": "tip054-latency-1-0-submit", "closed": True}
    replacement = {"request_id": "tip054-latency-1-1-submit", "closed": False}
    token = active.set(original)
    child = None
    try:

        def change_latest(resource: Any) -> None:
            assert isinstance(resource, Resource)
            active.set(replacement)

        facade = Resource()
        facade_ref = weakref.ref(facade)
        exposure.measure(change_latest, "phase.captured_context", (facade,))
        del facade
        gc.collect()
        assert facade_ref() is None
        row = next(
            row
            for row in decoded_records(exposure.snapshot())
            if row["label"] == "phase.captured_context"
        )
        assert row["request_id"] == original["request_id"] and row["reference_closed"] is True
        assert row["origin"] == "post_http_reference"
        assert row["task_id"] == exposure.ids.get(asyncio.current_task())

        active.set(original)

        async def work() -> None:
            exposure.measure(lambda: None, "phase.child_context")

        child = asyncio.create_task(work())
        active.set(replacement)
        await child
        child_row = next(
            row
            for row in decoded_records(exposure.snapshot())
            if row["label"] == "phase.child_context"
        )
        assert (
            child_row["request_id"] == original["request_id"]
            and child_row["reference_closed"] is True
        )
        assert child_row["task_id"] != row["task_id"]
        child_ref = weakref.ref(child)
        del child
        child = None
        await asyncio.sleep(0)
        gc.collect()
        assert child_ref() is None
        assert json.dumps is original_json
        timer_done = asyncio.Event()

        def timer() -> None:
            exposure.measure(lambda: None, "phase.inherited_timer")
            timer_done.set()

        with exposure.scope("r11-structural-inherited-timer"):
            asyncio.get_running_loop().call_soon(timer)
        await asyncio.wait_for(timer_done.wait(), 2)
        timer_row = next(
            row
            for row in decoded_records(exposure.snapshot())
            if row["label"] == "phase.inherited_timer"
        )
        assert timer_row["task_id"] is None and timer_row["request_id"] is None
        assert timer_row["origin"] == "timer_inherited_unassigned"
        assert all(
            not isinstance(value, Resource | asyncio.Task)
            for values in exposure.snapshot().values()
            for value in (values if isinstance(values, list) else [values])
        )
    finally:
        active.reset(token)
        exposure.close()
        if child is not None and not child.done():
            await asyncio.gather(child, return_exceptions=True)


@pytest.mark.asyncio
async def test_reference_finalize_serialize_flush_order_and_rejection_accounting() -> None:
    trace: list[str] = []
    active = ContextVar("r11-structural-order", default=None)

    def dumps(value: Any, **kwargs: Any) -> str:
        trace.append("serialize")
        return json.dumps(value, **kwargs)

    module = SimpleNamespace(active=active, json=SimpleNamespace(dumps=dumps))

    class Stream(io.StringIO):
        def write(self, value: str) -> int:
            trace.append("write")
            return super().write(value)

        def flush(self) -> None:
            trace.append("flush")
            return super().flush()

    class Reference:
        @staticmethod
        def finish_phase(_phase: Any, _request: Any) -> None:
            trace.append("finalize")

        def __init__(self) -> None:
            self.stream = Stream()

    reference, exposure = Reference(), ObserverExposure()
    original_descriptor = inspect.getattr_static(Reference, "finish_phase")
    original_stream, original_json, global_dumps = reference.stream, module.json, json.dumps
    exposure.attach_phase(reference, module)
    request = {"request_id": "tip054-latency-1-2-admission", "closed": True}
    token = active.set(request)
    try:
        reference.finish_phase({}, request)
        line = module.json.dumps({"request_id": request["request_id"]})
        assert reference.stream.write(line) == len(line)
        assert reference.stream.flush() is None
        trace.append("return")
        assert trace == ["finalize", "serialize", "write", "flush", "return"]

        def nested() -> None:
            exposure.measure(lambda: None, "phase.child")

        exposure.measure(nested, "phase.parent")
        packet = exposure.snapshot()
        records = decoded_records(packet)
        assert all(
            r["origin"] == "post_http_reference" and r["reference_closed"] is True for r in records
        )
        child = next(r for r in records if r["label"] == "phase.child")
        assert child["parent_ids"]
        for field, value in (
            ("start_ns", True),
            ("parent_ids", [True]),
            ("label_id", None),
            ("origin_id", True),
            ("source_line", True),
        ):
            bad = copy.deepcopy(packet)
            bad["records"][-1][FIELDS.index(field)] = value
            reject(bad)
        for counter in (True, -1):
            bad = copy.deepcopy(packet)
            bad["integrity"]["callback_errors"] = counter
            reject(bad)
        bad = copy.deepcopy(packet)
        bad["records"][-1][FIELDS.index("finish_end_ns")] = child["finish_start_ns"] - 1
        reject(bad)
        bad = copy.deepcopy(packet)
        bad["requests"].append("tip054-latency-1-3-admission")
        bad["records"][-1][FIELDS.index("request_index")] = len(bad["requests"]) - 1
        reject(bad)
        bad = copy.deepcopy(packet)
        bad["records"][-1][FIELDS.index("task_id")] = None
        reject(bad)
        bad = copy.deepcopy(packet)
        bad["labels"].append(bad["labels"][0])
        reject(bad)
        exposure.MAX_RECORDS = len(packet["records"])
        sentinel = Resource()
        assert exposure.measure(lambda: sentinel, "phase.cap-control") is sentinel
        assert exposure.snapshot()["integrity"]["dropped"] == 1
    finally:
        active.reset(token)
        exposure.close()
    assert inspect.getattr_static(Reference, "finish_phase") is original_descriptor
    assert reference.stream is original_stream and module.json is original_json
    assert json.dumps is global_dumps
