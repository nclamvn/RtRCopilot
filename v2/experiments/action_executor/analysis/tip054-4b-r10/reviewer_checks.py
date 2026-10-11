"""Eight independent stdlib-only R10 groups; no SDK or product imports.

Execution requires Contractor ACK. Synthetic expected values are hand-derived;
optional replay checks compare candidate artifacts with original frozen samples.
This is offline coverage/schema evidence, never database or timing acceptance.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


BASE = Path("v2/experiments/action_executor/analysis/tip054-4b-r10")
RAW = Path("v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1")
PIN = "d43b8628af2ccc0154e6ed58500795b117685e67ac976c39235ee8bfccc4ed85"
GROUPS = (
    "RC1_exact_half_open_masks",
    "RC2_scoped_identity_collisions",
    "RC3_censorship_and_invalid_clocks",
    "RC4_nearest_rank_and_original_oracle",
    "RC5_complete_failed_missing_populations",
    "RC6_ack_delivery_and_readiness_censoring",
    "RC7_partial_cost_and_outer_inner_limits",
    "RC8_fail_closed_paths_digests_and_determinism",
)


def rejected(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError("expected ValueError, not an accepted invalid premise")


def read_json(path):
    return json.loads(path.read_bytes())


def sample_key(row):
    return (row["profile"], row["case"], row["operation"])


def original_quantile(values, q):
    return sorted(values)[math.ceil(len(values) * q) - 1] if values else None


def replay_rows(replay):
    if replay is None:
        return None
    return [json.loads(line) for line in (replay / "requests.jsonl").read_bytes().splitlines()]


def rc1(api, _context):
    result = api.partition(10, 30, {"sql": [(12, 20), (12, 20)], "ping": [(18, 25)]})
    assert result["envelope_ns"] == 20
    assert result["segments"] == [
        [10, 12, "unclassified"], [12, 18, "sql"], [18, 20, "ping|sql"],
        [20, 25, "ping"], [25, 30, "unclassified"],
    ]
    assert result["mask_ns"] == {"unclassified": 7, "sql": 6, "ping|sql": 2, "ping": 5}
    assert result["counts"]["sql"]["closed"] == 2
    touching = api.partition(10, 30, {"closed_hold": [(10, 12), (12, 14)]})
    assert touching["segments"] == [[10, 14, "closed_hold"], [14, 30, "unclassified"]]
    crossing = api.partition(0, 8, {"a": [(0, 5)], "b": [(3, 8)]})
    assert crossing["mask_ns"] == {"a": 3, "a|b": 2, "b": 3}
    assert sum(crossing["mask_ns"].values()) == 8


def rc2(api, _context):
    keys = {
        api.namespace_key("R9/runA/task", 1),
        api.namespace_key("R9/runB/task", 1),
        api.namespace_key("PG/runA/pid", 1),
        api.namespace_key("phase/runA/requestA", 1),
        api.namespace_key("phase/runA/requestB", 1),
        api.namespace_key("audit/runA/transaction", 1),
    }
    assert len(keys) == 6
    assert api.namespace_key("phase/runA/requestA", 1) in keys
    rejected(lambda: api.namespace_key("", 1))
    # Equal profile/case/operation labels in separate ON/OFF runs do not pair clocks.
    assert api.namespace_key("ON", (50, 1, "submit")) != api.namespace_key("OFF", (50, 1, "submit"))
    phases = {"requestA": {"sql": [{"pid": 77, "start_ns": 10, "end_ns": 20,
                                    "static_sha256": "0" * 64}]}}
    no_match = [{"tick_ns": 1, "end_ns": 3, "activity": [{"pid": 77, "wait_event_type": "Lock"}]}]
    assert api.pg_candidates(no_match, phases)[1] == {}
    wrong_pid = [{"tick_ns": 12, "end_ns": 13, "activity": [{"pid": 78, "wait_event_type": "Lock"}]}]
    assert api.pg_candidates(wrong_pid, phases)[1] == {}
    observed = [{"tick_ns": 12, "end_ns": 13, "activity": [{"pid": 77, "wait_event_type": "Lock"}]}]
    per_request, total = api.pg_candidates(observed, phases)
    assert total == {"window_overlap_Lock": 1}
    assert dict(per_request["requestA"]) == {
        "window_overlap_Lock": 1, "tick_point_candidate_Lock": 1,
        "whole_snapshot_window_candidate_Lock": 1,
    }


def rc3(api, _context):
    result = api.partition(100, 110, {"sql": [
        (95, 105), (108, 112), (120, 125), (103, 103), (106, None), (None, 110),
    ]})
    assert result["mask_ns"] == {"sql": 7, "unclassified": 3}
    assert result["counts"]["sql"] == {
        "closed": 4, "zero": 1, "open": 2, "outside": 1, "clipped": 2,
    }
    assert api.partition(1, 3, {"sql": [(1, None)]})["mask_ns"] == {"unclassified": 2}
    for start, end in ((2, 1), (1, 1), (-1, 1), (True, 4), (1.0, 4)):
        rejected(lambda start=start, end=end: api.partition(start, end, {}))
    rejected(lambda: api.partition(1, 4, {"sql": [(3, 2)]}))
    rejected(lambda: api.partition(1, 4, {"sql": [(None, -1)]}))
    phase = {"phases": [
        {"phase_id": 0, "parent_ids": [], "start_ns": 1, "end_ns": 10},
        {"phase_id": 1, "parent_ids": [0], "start_ns": 2, "end_ns": 9},
    ], "sql": [{"phase_ids": [0, 1], "start_ns": 3, "end_ns": 8, "static_sha256": "0" * 64}],
        "pool": [], "holds": []}
    api.validate_local(phase)
    for target, field, value in (("phases", "phase_id", True), ("phases", "parent_ids", [99]),
                                 ("phases", "start_ns", 11), ("sql", "phase_ids", [99]),
                                 ("sql", "end_ns", 2), ("sql", "static_sha256", "invalid")):
        changed = copy.deepcopy(phase)
        changed[target][-1][field] = value
        rejected(lambda changed=changed: api.validate_local(changed))
    changed = copy.deepcopy(phase)
    changed["phases"][1]["end_ns"] = 11
    rejected(lambda: api.validate_local(changed))
    event = {"span_id": 0, "name": "adapter._async_ping", "request_id": "requestA",
             "task_id": 1, "resource_id": 77, "resource_kind": "driver", "parent_ids": [],
             "start_ns": 10, "end_ns": 11, "error_type": None}
    api.validate_events({"requestA": {"pool": []}}, [event])
    for field, value in (("span_id", True), ("parent_ids", [0]), ("task_id", True),
                         ("start_ns", -1), ("end_ns", 9), ("request_id", "other")):
        rejected(lambda field=field, value=value: api.validate_events(
            {"requestA": {"pool": []}}, [{**event, field: value}]))


def rc4(api, context):
    assert api.nearest_rank([]) is None
    tied = [1.0] * 94 + [5.0] * 6
    assert api.nearest_rank(tied) == 5.0
    assert sum(value >= 5.0 for value in tied) == 6
    for values in ([float("nan")], [float("inf")], [-1.0]):
        rejected(lambda values=values: api.nearest_rank(values))
    rejected(lambda: api.nearest_rank([1.0], 0))
    calculated = []
    for population in ("ON", "OFF"):
        samples = context["samples"][population]
        summary = read_json(context["root"] / RAW / f"r9m_{population.lower()}_r1/run/latency-summary.json")
        for old in summary["cells"]:
            profile, operation = old["concurrency"], old["operation"]
            rows = [r for r in samples if r["profile"] == profile and r["operation"] == operation]
            values = [r["elapsed_ms"] for r in rows]
            limit = 500 if operation == "admission" else 1000
            expected = {
                "n": len(rows), "errors": sum(not r["okay"] for r in rows),
                "p50_ms": original_quantile(values, .5),
                "p95_ms": original_quantile(values, .95),
                "p99_ms": original_quantile(values, .99), "limit_ms": limit,
                "passed": len(rows) == 100 and all(r["okay"] for r in rows)
                and original_quantile(values, .95) <= limit,
            }
            mapping = {"n": "samples", "errors": "failures", "passed": "pass", "limit_ms": "p95_limit_ms"}
            assert all(expected[k] == old[mapping.get(k, k)] for k in expected)
            assert api.cell(samples, profile, operation) == expected
            calculated.append((population, profile, operation, expected))
    assert len(calculated) == 32
    if context["replay"] is not None:
        actual = read_json(context["replay"] / "cohorts.json")["cells"]
        assert len(actual) == 32
        for pop, profile, operation, expected in calculated:
            matched = [r for r in actual if (r["population"], r["profile"], r["operation"]) == (pop, profile, operation)]
            assert len(matched) == 1
            assert all(matched[0][key] == value for key, value in expected.items())


def rc5(_api, context):
    expected = {"ON": (1384, 133, 216), "OFF": (1590, 14, 10)}
    for population, (n, errors, missing) in expected.items():
        rows = context["samples"][population]
        assert len(rows) == n and len({sample_key(r) for r in rows}) == n
        assert sum(not r["okay"] for r in rows) == errors and 1600 - n == missing
        failures = [r for r in rows if not r["okay"]]
        assert all(r["http_status"] == 503 and r["error_code"] == "action_operation_timeout" for r in failures)
        operations = Counter(r["operation"] for r in failures)
        assert operations == ({"submit": 108, "status": 15, "cancel": 10} if population == "ON"
                              else {"submit": 5, "status": 3, "cancel": 6})
    rows = context["replay_rows"]
    if rows is not None:
        assert len(rows) == 2974
        identities = {(r["population"], sample_key(r["sample"])) for r in rows}
        expected_ids = {(p, sample_key(r)) for p, samples in context["samples"].items() for r in samples}
        assert identities == expected_ids and len(identities) == len(rows)
        for row in rows:
            if row["population"] == "OFF":
                assert row["internal_coverage"] == "unobserved"
                assert "coverage" not in row and "terminal" not in row
        failed = [json.loads(line) for line in (context["replay"] / "failed.jsonl").read_bytes().splitlines()]
        assert {(r["population"], sample_key(r["sample"])) for r in failed} == {
            (p, sample_key(r)) for p, samples in context["samples"].items() for r in samples if not r["okay"]
        }


def rc6(api, _context):
    transactions = [
        {"start_ns": 1, "terminal_ns": 4, "terminal_kind": "commit_ack", "append_spans": [{"start_ns": 2, "end_ns": 3}]},
        {"start_ns": 5, "terminal_ns": None, "terminal_kind": "end_unknown", "append_spans": []},
        {"start_ns": 6, "terminal_ns": 8, "terminal_kind": "rollback_ack", "append_spans": []},
    ]
    assert api.terminal_flags(transactions) == {
        "transactions": 3, "commit_ack": 1, "rollback_ack": 1, "unknown": 1, "audited_commit_ack": 1,
    }
    rejected(lambda: api.terminal_flags([{**transactions[0], "terminal_ns": None}]))
    rejected(lambda: api.terminal_flags([{**transactions[0], "terminal_ns": 0}]))
    # Two distinct readiness Futures can associate with one eventual consumer.
    getter = {"span_id": 0, "name": "queue.get", "request_id": "getter", "task_id": 11,
              "start_ns": 10, "end_ns": 30, "error_type": None}
    consumer = {"span_id": 3, "name": "queue.get_nowait", "request_id": "getter", "task_id": 11,
                "parent_ids": [0], "start_ns": 25, "end_ns": 26, "error_type": None,
                "result_resource_id": 91}
    wakes = [{"span_id": i, "name": "queue.wake_ready", "request_id": "producer",
              "mapping": "unique", "getter_request_id": "getter", "getter_span_id": 0,
              "getter_task_id": 11, "future_id": 50 + i, "future_ready": True,
              "producer_request_id": "producer", "start_ns": t, "end_ns": t + 1}
             for i, t in ((1, 15), (2, 20))]
    cancelled = {**getter, "span_id": 4, "request_id": "cancelled", "task_id": 12,
                 "end_ns": 40, "error_type": "CancelledError"}
    last = {**wakes[0], "span_id": 5, "getter_request_id": "cancelled", "getter_span_id": 4,
            "getter_task_id": 12, "future_id": 60, "start_ns": 32, "end_ns": 33}
    result = api.wake_rows([getter, *wakes, consumer, cancelled, last],
                           {"getter": [getter, consumer], "cancelled": [cancelled]})
    paired = result["getter"]
    assert len(paired) == 2 and {r["consumer_span_id"] for r in paired} == {3}
    assert all(r["label"] == "scheduling_competition_envelope_not_reservation" for r in paired)
    assert result["cancelled"][0]["consumer_span_id"] is None
    assert result["cancelled"][0]["ready_to_consumer_ns"] is None
    assert result["cancelled"][0]["getter_error_type"] == "CancelledError"
    assert result["cancelled"][0]["censorship_reason"] == "getter_cancelled_without_observed_consumer"
    assert result["cancelled"][0]["consumer_outcome"] == "unobserved"
    assert all(r["consumer_outcome"] == "returned_attempt" for r in paired)
    errored = {**consumer, "error_type": "QueueEmpty", "result_resource_id": None}
    repeated = api.wake_rows([getter, *wakes, errored], {"getter": [getter, errored]})["getter"]
    assert all(r["consumer_outcome"] == "error" and r["consumer_error_type"] == "QueueEmpty" for r in repeated)
    assert {r["consumer_span_id"] for r in repeated} == {3}


def rc7(api, _context):
    assert api.partial_cost([2, 3, 7]) == {
        "n": 3, "sum_ns": 12, "p95_ns": 7, "allocation": "unkeyed_aggregate_only",
    }
    assert api.partial_cost([]) == {"n": 0, "sum_ns": 0, "p95_ns": None, "allocation": "unkeyed_aggregate_only"}
    rejected(lambda: api.partial_cost([-1]))
    rejected(lambda: api.partial_cost([True]))
    assert api.outer_inner(5.0, 1000000, 4000000) == {
        "outer_ms": 5.0, "inner_ms": 3.0, "residual_ms": 2.0, "label": "noncausal_scalar_gap",
    }
    rejected(lambda: api.outer_inner(float("nan"), 1, 2))
    rejected(lambda: api.outer_inner(1, 2, 1))
    # Nested category p95s/sums do not provide an SLA correction.
    coverage = api.partition(0, 10, {"pool": [(0, 10)], "ping": [(2, 6)]})
    assert sum(coverage["mask_ns"].values()) == 10
    assert coverage["mask_ns"] == {"pool": 6, "ping|pool": 4}


def rc8(api, context):
    root, output = context["root"], context["output"]
    assert api.MANIFEST_SHA == PIN
    rejected(lambda: api.validate_output(root, root / BASE))
    rejected(lambda: api.validate_output(root, root / "outside-r10"))
    rejected(lambda: api.safe_path(root, "../escape"))
    rejected(lambda: api.safe_path(root, "/absolute"))
    before = hashlib.sha256(Path(api.__file__).read_bytes()).hexdigest()
    raw = Path(api.__file__).read_bytes()
    assert api.bounded_read(Path(api.__file__), {"bytes": len(raw), "sha256": before}) == raw
    rejected(lambda: api.bounded_read(Path(api.__file__), {"bytes": len(raw), "sha256": "0" * 64}))
    class Oversize:
        def stat(self):
            return SimpleNamespace(st_size=api.MAX_FILE + 1)

        def read_bytes(self):
            raise AssertionError("cap must reject BEFORE content read")

    rejected(lambda: api.bounded_read(Oversize(), {"bytes": api.MAX_FILE + 1, "sha256": "0" * 64}))
    with tempfile.TemporaryDirectory(prefix="rc8-", dir=output) as directory:
        synthetic = Path(directory)
        folder = synthetic / BASE / "technical-freeze-e1"
        folder.mkdir(parents=True)
        (folder / "selected-inputs.json").write_bytes(b"not-json; wrong-pin")
        rejected(lambda: api.load_inputs(synthetic))
        target = synthetic / "target"
        target.write_bytes(b"x")
        (synthetic / "alias").symlink_to(target)
        rejected(lambda: api.safe_path(synthetic, "alias"))
    assert before == hashlib.sha256(Path(api.__file__).read_bytes()).hexdigest()
    assert api.canonical({"b": 1, "a": 2}) == '{"a":2,"b":1}\n'
    rejected(lambda: api.canonical({"bad": float("nan")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.absolute()
    if output.exists() or output.is_symlink() or not output.is_relative_to(root / BASE) or output.resolve() != output:
        raise ValueError("NEW R10 review-control directory required")
    candidate = root / BASE / "analyze.py"
    spec = importlib.util.spec_from_file_location("r10_candidate_for_review", candidate)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    # Manifest guard verifies actual selected bytes before original sample parsing.
    _manifest, inputs = api.load_inputs(root)
    samples = {p: json.loads(inputs[f"{RAW}/r9m_{p.lower()}_r1/run/samples.json"])
               for p in ("ON", "OFF")}
    output.mkdir()
    context = {"root": root, "output": output, "replay": args.replay,
               "replay_rows": replay_rows(args.replay), "samples": samples}
    results = []
    for group, operation in zip(GROUPS, (rc1, rc2, rc3, rc4, rc5, rc6, rc7, rc8), strict=True):
        operation(api, context)
        results.append({"id": group, "status": "PASS"})
    packet = {"groups": results, "group_count": 8, "scope": "offline math/schema/guard only",
              "actual_replay_artifacts_checked": args.replay is not None,
              "analyzer_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
              "review_checks_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (output / "summary.json").open("x") as stream:
        json.dump(packet, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(packet, sort_keys=True))


if __name__ == "__main__":
    main()
