"""Declared B01-B12 offline groups; execution requires Contractor ACK."""

import ast
import hashlib
import json
import tempfile
from pathlib import Path

import analyze as a

GROUPS = (
    "B01_nested", "B02_duplicate_touching", "B03_crossing",
    "B04_censorship", "B05_invalid_clocks", "B06_quantiles",
    "B07_cell_oracle", "B08_namespaces", "B09_terminals",
    "B10_partial_cost_gap", "B11_file_guards", "B12_determinism_shape",
)


def rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def run():
    checks = []
    nested = a.partition(0, 10, {"x": [(0, 10)], "y": [(2, 6)]})
    assert nested["mask_ns"] == {"x": 6, "x|y": 4}
    assert sum(nested["mask_ns"].values()) == 10
    checks.append(GROUPS[0])

    touching = a.partition(0, 10, {"x": [(0, 5), (5, 10), (0, 5)]})
    assert touching["segments"] == [[0, 10, "x"]]
    assert touching["counts"]["x"]["closed"] == 3
    checks.append(GROUPS[1])

    crossing = a.partition(0, 10, {"b": [(4, 9)], "a": [(1, 6)]})
    assert crossing["mask_ns"] == {"a": 3, "a|b": 2, "b": 3, "unclassified": 2}
    assert crossing["segments"] == [[0, 1, "unclassified"], [1, 4, "a"], [4, 6, "a|b"], [6, 9, "b"], [9, 10, "unclassified"]]
    checks.append(GROUPS[2])

    censored = a.partition(10, 20, {"a": [(5, 15), (20, 25), (12, 12), (None, 18), (17, None)]})
    assert censored["mask_ns"] == {"a": 5, "unclassified": 5}
    assert censored["counts"]["a"] == {"closed": 3, "zero": 1, "open": 2, "outside": 1, "clipped": 1}
    assert a.marginals(a.partition(0, 10, {"a": [(1, None)]}))["a"] is None
    checks.append(GROUPS[3])

    for call in (
        lambda: a.partition(-1, 10, {}), lambda: a.partition(0, 0, {}),
        lambda: a.partition(0, 10, {"a": [(7, 6)]}),
        lambda: a.partition(False, 10, {}),
    ):
        rejects(call)
    local = {"phases": [{"phase_id": 0, "parent_ids": [], "start_ns": 1, "end_ns": 8}, {"phase_id": 1, "parent_ids": [0], "start_ns": 2, "end_ns": 7}], "sql": [], "pool": [], "holds": []}
    a.validate_local(local)
    rejects(lambda: a.validate_local({**local, "phases": [local["phases"][0], {**local["phases"][1], "end_ns": 9}]}))
    rejects(lambda: a.validate_local({**local, "phases": [{**local["phases"][0], "start_ns": -1}]}))
    rejects(lambda: a.validate_local({**local, "phases": [{**local["phases"][0], "phase_id": False}]}))
    checks.append(GROUPS[4])

    assert a.nearest_rank([]) is None
    assert a.nearest_rank([3, 1, 2, 2], .5) == 2
    assert a.nearest_rank(list(range(1, 101))) == 95
    assert len([v for v in [1, 2, 2] if v >= a.nearest_rank([1, 2, 2])]) == 2
    rejects(lambda: a.nearest_rank([float("nan")]))
    checks.append(GROUPS[5])

    samples = [{"profile": 1, "operation": "admission", "elapsed_ms": 500, "okay": True} for _ in range(100)]
    assert a.cell(samples, 1, "admission")["passed"]
    assert not a.cell(samples[:-1], 1, "admission")["passed"]
    samples[0]["okay"] = False
    assert a.cell(samples, 1, "admission")["errors"] == 1
    assert a.cell([], 50, "cancel")["p95_ms"] is None
    checks.append(GROUPS[6])

    assert a.namespace_key("ON_R9_object", 7) != a.namespace_key("ON_PG_pid", 7)
    assert a.namespace_key("ON_requestA_phase", 1) != a.namespace_key("ON_requestB_phase", 1)
    assert a.namespace_key("ON_request", "x") != a.namespace_key("OFF_request", "x")
    assert a.aggregate([{"population": "OFF", "request_id": "x", "sample": {"okay": False}}])["commit_ack_requests"] is None
    checks.append(GROUPS[7])

    tx = [{"start_ns": 1, "terminal_ns": 4, "terminal_kind": "commit_ack", "append_spans": [{}]},
          {"start_ns": 5, "terminal_ns": None, "terminal_kind": "end_unknown", "append_spans": []}]
    assert a.terminal_flags(tx) == {"transactions": 2, "commit_ack": 1, "rollback_ack": 0, "unknown": 1, "audited_commit_ack": 1}
    rejects(lambda: a.terminal_flags([{**tx[0], "terminal_ns": None}]))
    checks.append(GROUPS[8])

    assert a.partial_cost([1, 3, 2]) == {"n": 3, "sum_ns": 6, "p95_ns": 3, "allocation": "unkeyed_aggregate_only"}
    assert a.outer_inner(2, 0, 1_000_000)["residual_ms"] == 1
    assert a.outer_inner(.5, 0, 1_000_000)["residual_ms"] == -.5
    assert a.partial_cost([])["p95_ns"] is None
    checks.append(GROUPS[9])

    with tempfile.TemporaryDirectory(prefix="r10-pure-") as tmp:
        root = Path(tmp).resolve()
        base = root / a.BASE
        base.mkdir(parents=True)
        fresh = base / "fresh"
        assert a.validate_output(root, fresh) == fresh
        rejects(lambda: a.validate_output(root, base))
        rejects(lambda: a.validate_output(root, root / "escape"))
        fresh.mkdir()
        rejects(lambda: a.validate_output(root, fresh))
        p = base / "input"
        p.write_bytes(b"abc")  # New disposable pure fixture, never selected evidence.
        expected = {"bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
        assert a.bounded_read(p, expected) == b"abc"
        rejects(lambda: a.bounded_read(p, {**expected, "sha256": "0" * 64}))
        rejects(lambda: a.bounded_read(p, {**expected, "bytes": a.MAX_FILE + 1}))
        rejects(lambda: a.safe_path(root, "../escape"))
    checks.append(GROUPS[10])

    assert a.canonical({"b": 1, "a": [2]}) == a.canonical({"a": [2], "b": 1})
    assert len(a.CATEGORIES) == len(set(a.CATEGORIES)) == 12
    source = ast.parse(Path(a.__file__).read_text())
    imports = {n.module for n in ast.walk(source) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"collections", "pathlib"}
    assert len(GROUPS) == len(set(GROUPS)) == 12
    checks.append(GROUPS[11])
    return {"declared_groups": 12, "passed_groups": checks,
            "scope": "offline structural/math/schema fixtures; NOT SDK/SQL/runtime"}


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
