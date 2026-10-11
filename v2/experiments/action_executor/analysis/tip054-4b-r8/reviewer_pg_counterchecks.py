"""Independent sampled temporal matches, not server lock identity/duration."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("existing output refused")
    raw = args.repo / "v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1"
    selected, result = {}, {}

    def read(path):
        data = path.read_bytes()
        assert len(data) <= 64 * 1024 * 1024
        selected[str(path.relative_to(args.repo))] = hashlib.sha256(data).hexdigest()
        rows = [json.loads(line) for line in data.splitlines()]
        assert len(rows) <= 20000
        return rows

    for epoch in ("baseline_624", "candidate_56f"):
        gate = raw / ("r7_" + epoch + "_on_r1")
        requests = read(gate / "phase-requests.jsonl")
        ticks = read(gate / "pg-waits.jsonl")
        sql_by_pid = {}
        for request in requests:
            for index, sql in enumerate(request["sql"]):
                if sql["pid"] is not None and sql["end_ns"] is not None:
                    assert request["start_ns"] <= sql["start_ns"] <= sql["end_ns"] <= request["end_ns"]
                    sql_by_pid.setdefault(sql["pid"], []).append((request, index, sql))
        matches = []
        for index, tick in enumerate(ticks):
            assert tick["tick_ns"] <= tick["end_ns"]
            for activity in tick.get("activity", []):
                for request, sql_index, sql in sql_by_pid.get(activity["pid"], []):
                    if sql["start_ns"] <= tick["tick_ns"] <= sql["end_ns"]:
                        matches.append({
                            "request_id": request["request_id"], "sql_index": sql_index,
                            "pid": sql["pid"], "tick_index": index,
                            "whole_envelope_contained": tick["end_ns"] <= sql["end_ns"],
                            "wait_event_type": activity["wait_event_type"],
                            "wait_event": activity["wait_event"],
                            "blockers": activity["blockers"],
                            "statement_class": sql["statement_class"],
                            "static_sha256": sql["static_sha256"],
                            "http_status": request.get("http_status"),
                            "locks": [lock for lock in tick.get("locks", [])
                                      if lock["pid"] == sql["pid"]],
                        })
        contained = [m for m in matches if m["whole_envelope_contained"]]
        result[epoch] = {
            "requests": len(requests), "ticks": len(ticks),
            "error_ticks": sum("error_type" in tick for tick in ticks),
            "tick_point_matches": len(matches), "whole_envelope_matches": len(contained),
            "point_wait_types": dict(Counter(str(m["wait_event_type"]) for m in matches)),
            "envelope_wait_types": dict(Counter(str(m["wait_event_type"]) for m in contained)),
            "failed_matches": [m for m in matches if m["http_status"] == 503],
            "all_temporal_matches": matches,
        }
    selected[str(Path(__file__).resolve().relative_to(args.repo))] = hashlib.sha256(
        Path(__file__).read_bytes()).hexdigest()
    assert all(hashlib.sha256((args.repo / path).read_bytes()).hexdigest() == digest
               for path, digest in selected.items())
    args.output.mkdir(parents=True)
    (args.output / "pg-counterchecks.json").write_text(json.dumps({
        "selected_inputs": selected, "inputs_unchanged": True, "epochs": result,
        "limits": "Two non-atomic sampled queries; no continuous wait, exact advisory object, causal or zero-wait inference.",
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({epoch: {k: v for k, v in values.items()
                             if k not in {"failed_matches", "all_temporal_matches"}}
                      for epoch, values in result.items()}, indent=2))


if __name__ == "__main__":
    main()
