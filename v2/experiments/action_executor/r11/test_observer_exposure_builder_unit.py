"""Four structural groups; labelled fakes prove observer plumbing, not SQL."""

import asyncio
import contextvars
import copy
import gc
import io
import json
import types
import weakref

import pytest
from analyze import mask_accounting, phase_witnesses, quantile, union_ns
from overhead_observer import FAULT_KEYS, ObserverExposure, TaskIds, decoded_records


@pytest.mark.asyncio
async def test_original_arguments_results_and_failures_survive_new_recording_faults(monkeypatch):
    observer = ObserverExposure()
    calls, result, argument = [], object(), object()

    def original(value, *, request_override):
        calls.append((value, request_override))
        return result

    with observer.scope("RB-S1"):
        assert (
            observer.measure(original, "delegate", (argument,), {"request_override": argument})
            is result
        )
        failure = ValueError("original")
        cancel = asyncio.CancelledError("original cancellation")

        def failed(error):
            calls.append(error)
            raise error

        def broken(*args):
            raise RuntimeError("NEW-only registry fault")

        monkeypatch.setattr(observer.ids, "get", broken)
        assert (
            observer.measure(original, "faulted", (argument,), {"request_override": argument})
            is result
        )
        for error in (failure, cancel):
            with pytest.raises(type(error)) as caught:
                observer.measure(failed, "faulted-original", (error,))
            assert caught.value is error
        monkeypatch.undo()
        monkeypatch.setattr(observer, "finish", broken)
        with pytest.raises(ValueError) as caught:
            observer.measure(failed, "finish-fault", (failure,))
        assert caught.value is failure
    assert len(calls) == 5 and calls[:2] == [(argument, argument)] * 2
    observer.close()
    assert observer.snapshot()["integrity"]["callback_errors"] >= 4
    assert observer.snapshot()["integrity"]["open"] == 1


@pytest.mark.asyncio
async def test_raw_static_descriptor_local_json_and_immediate_stream_order_restore(monkeypatch):
    operations = []

    class Stream(io.StringIO):
        def write(self, value):
            operations.append(("write", value))
            return super().write(value)

        def flush(self):
            operations.append(("flush", None))
            return super().flush()

    active = contextvars.ContextVar("fake-phase-reference", default=None)
    phase_module = types.SimpleNamespace(json=json, active=active)
    audit_module = types.SimpleNamespace(json=json)

    class Phase:
        def __init__(self):
            self.stream = Stream()

        @staticmethod
        def finish_phase(item, request):
            operations.append(("finish", item))
            return item

    class Tail:
        def __init__(self):
            self.stream = Stream()

        def emit(self, record):
            self.stream.write(audit_module.json.dumps(record, sort_keys=True) + "\n")
            self.stream.flush()
            return record

    phase, tail, observer = Phase(), Tail(), ObserverExposure()
    raw, original_phase_stream, original_audit_stream = (
        vars(Phase)["finish_phase"],
        phase.stream,
        tail.stream,
    )
    observer.attach_phase(phase, phase_module)
    observer.attach_audit(tail, audit_module)
    record = {"request_id": "tip054-latency-1-0-admission", "closed": True}
    token = active.set(record)
    try:
        marker = object()
        assert phase.finish_phase(marker, record) is marker
        encoded = phase_module.json.dumps({"n": 7}, sort_keys=True)
        assert phase.stream.write(encoded) == len(encoded)
        phase.stream.flush()
        assert tail.emit(record) is record
        assert operations == [
            ("finish", marker),
            ("write", encoded),
            ("flush", None),
            ("write", json.dumps(record, sort_keys=True) + "\n"),
            ("flush", None),
        ]
        monkeypatch.setattr(
            observer, "line", lambda original: (_ for _ in ()).throw(ValueError("metadata"))
        )
        # Source-line lookup faults cannot skip original static/emit work.
        assert phase.finish_phase(marker, record) is marker
        assert tail.emit(record) is record
    finally:
        observer.close()
        active.reset(token)
    assert vars(Phase)["finish_phase"] is raw
    assert phase_module.json is audit_module.json is json
    assert phase.stream is original_phase_stream and tail.stream is original_audit_stream
    rows = decoded_records(observer.snapshot())
    assert {
        "phase.finish_phase",
        "phase.serialize",
        "phase.write",
        "phase.flush",
        "audit.emit",
        "audit.serialize",
        "audit.write",
        "audit.flush",
    } <= {r["label"] for r in rows}
    assert any(r["origin"] == "post_http_reference" for r in rows)
    assert observer.snapshot()["integrity"]["callback_errors"] == 2


@pytest.mark.asyncio
async def test_weak_registry_timer_nesting_caps_and_last_finish_window():
    class WeakObject:
        pass

    registry, value = TaskIds(), WeakObject()
    pointer = weakref.ref(value)
    assert registry.get(value) == registry.get(value)
    del value
    gc.collect()
    assert pointer() is None and registry.items == {}
    observer, finished = ObserverExposure(), asyncio.Event()
    with observer.scope("RB-S3"):
        observer.measure(lambda: observer.measure(lambda: 11, "inner"), "outer")

        def timer():
            observer.measure(lambda: 13, "timer")
            finished.set()

        asyncio.get_running_loop().call_soon(timer)
        await finished.wait()
    rows = decoded_records(observer.snapshot())
    assert len(rows) == 3 and rows[1]["parent_ids"] == [0]
    assert rows[2]["request_id"] is rows[2]["task_id"] is None
    assert rows[2]["origin"] == "timer_inherited_unassigned"
    assert observer.snapshot()["censorship"]["timer_unassigned"] == 1
    capped = ObserverExposure()
    capped.MAX_RECORDS = 1  # Structural cap premise only; production constant unchanged.
    with capped.scope("RB-S3-cap"):
        assert capped.measure(lambda: 17, "first") == 17
        assert capped.measure(lambda: 19, "dropped") == 19
    assert capped.snapshot()["integrity"]["dropped"] == 1
    window = ObserverExposure()

    def overrun():
        window.started_ns -= 181 * 10**9
        return 23

    with window.scope("RB-S3-window"):
        assert window.measure(overrun, "last-finish") == 23
    packet = window.snapshot()
    assert packet["integrity"]["window_exceeded"] == 1
    assert len(decoded_records(packet)) == 1
    for item in (observer, capped, window):
        item.close()


@pytest.mark.asyncio
async def test_strict_compact_decoder_and_nonadditive_envelope_conservation():
    observer = ObserverExposure()
    with observer.scope("RB-S4"):
        observer.measure(lambda: observer.measure(lambda: None, "child"), "parent")
    observer.close()
    packet = observer.snapshot()
    assert set(packet["integrity"]) == set(FAULT_KEYS)
    assert not any(packet["integrity"].values()) and len(decoded_records(packet)) == 2
    assert json.dumps(packet, sort_keys=True) == json.dumps(copy.deepcopy(packet), sort_keys=True)
    invalid = []
    bad = copy.deepcopy(packet)
    bad["integrity"]["dropped"] = True
    invalid.append(bad)
    bad = copy.deepcopy(packet)
    bad["records"][1][5] = -1
    invalid.append(bad)
    bad = copy.deepcopy(packet)
    bad["records"][1][11] = bad["records"][1][5] + 1
    invalid.append(bad)
    bad = copy.deepcopy(packet)
    bad["requests"].append("different-request")
    bad["records"][1][2] = 1
    invalid.append(bad)
    bad = copy.deepcopy(packet)
    bad["records"][1][4] = [99]
    invalid.append(bad)
    bad = copy.deepcopy(packet)
    bad["records"][1][1] = None
    invalid.append(bad)
    for malformed in invalid:
        with pytest.raises(ValueError):
            decoded_records(malformed)
    spans = [(1, 7), (2, 5), (7, 9), (None, None)]
    assert union_ns(spans) == 8 and union_ns(spans, 20, 30) == 0
    assert union_ns([(None, None)]) is None
    assert mask_accounting(spans, 0, 10) == {
        "covered_ns": 8,
        "unclassified_residual_ns": 2,
        "envelope_ns": 10,
        "conservation": True,
    }
    assert mask_accounting([(None, None)], 0, 10)["covered_ns"] is None
    with pytest.raises(ValueError):
        union_ns([(8, 3)])
    assert quantile([1, 2, 3, 4, 5, 6]) == 6 and quantile([]) is None
    witness = {
        "origin": "post_http_reference",
        "reference_closed": True,
        "error_type": None,
        "start_ns": 12,
        "end_ns": 13,
    }
    phase = {"end_ns": 10, "phases": []}
    rows = [
        {**witness, "label": name, "start_ns": 12 + i * 2, "end_ns": 13 + i * 2}
        for i, name in enumerate(("phase.serialize", "phase.write", "phase.flush"))
    ]
    assert phase_witnesses(rows, phase)["phase.serialize"] == 1
    with pytest.raises(ValueError):
        phase_witnesses(rows[:-1], phase)
