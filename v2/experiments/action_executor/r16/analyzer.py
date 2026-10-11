"""Bounded offline R15 evidence analysis; imports only the Python standard library."""

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
R16 = Path("v2/experiments/action_executor/r16")
RAW = Path("v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1/r15/compare_e1")
SELECTED_SHA = "a84b17abfb73e911b8542e90ffaa9b7ee87a9fe2b1fe8dd623cbe24e4b8da3bd"
CAP = 2 * 1024 * 1024
METRICS = ("latency_ms", "hold_sum_ms", "unclassified_remainder_ms")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def bounded_path(root, relative):
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "unsafe relative path")
    resolved = (root / path).resolve()
    require(resolved.is_relative_to(root.resolve()), "path escapes root")
    return resolved


def load_inputs(root=ROOT):
    manifest_bytes = (root / R16 / "selected-inputs.json").read_bytes()
    require(sha(manifest_bytes) == SELECTED_SHA, "selected manifest binding changed")
    manifest = json.loads(manifest_bytes)
    entries = manifest["files"]
    require(manifest["input_file_count"] == len(entries) == 14, "input file count")
    require(len(entries) <= 20 and manifest["total_input_bytes"] <= CAP, "input cap")
    payloads = {}
    for entry in entries:
        relative = entry["path"]
        require(relative not in payloads, "duplicate input path")
        payload = bounded_path(root, relative).read_bytes()
        require(len(payload) == entry["bytes"] and sha(payload) == entry["sha256"],
                "input binding changed: " + relative)
        payloads[relative] = payload
    require(sum(map(len, payloads.values())) == manifest["total_input_bytes"], "input bytes")
    return manifest, payloads


def parse(payloads):
    def data(name):
        return payloads[str(RAW / name)]
    return (json.loads(data("schedule.json")),
            [json.loads(line) for line in data("started.jsonl").splitlines()],
            [json.loads(line) for line in data("outcomes.jsonl").splitlines()],
            json.loads(data("comparison-summary.json")))


def nearest(values):
    ordered = sorted(values)
    return {key: ordered[max(0, math.ceil(len(ordered) * q) - 1)] if ordered else None
            for key, q in (("p50_ms", .50), ("p95_ms", .95), ("p99_ms", .99), ("max_ms", 1))}


def finite(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, label)


def unique(rows, label):
    result = {}
    for row in rows:
        require(row["id"] not in result, "duplicate " + label + " id")
        result[row["id"]] = row
    return result


def expected_schedule():
    return [{"id": f"c{c}_{lane}_{ordinal:03d}", "concurrency": c, "lane": lane,
             "ordinal": ordinal, "receipt_count": (0, 2, 100)[ordinal % 3]}
            for c in (1, 10, 25, 50)
            for lane in (("legacy", "new") if c in (1, 25) else ("new", "legacy"))
            for ordinal in range(100)]


def validate(schedule, starts, outcomes, summary):
    require(schedule == expected_schedule(), "schedule differs from exact fixed population")
    scheduled, started, observed = (unique(rows, name) for rows, name in
                                   ((schedule, "schedule"), (starts, "start"), (outcomes, "outcome")))
    require(set(scheduled) == set(started) == set(observed) and len(observed) == 800,
            "missing or extra identities")
    require([row["id"] for row in starts] == [row["id"] for row in schedule], "start order")
    previous = -1
    rows = []
    keys = {"checkin", "checkout", "cleanup_equal", "concurrency", "equal", "hold_ms", "id",
            "lane", "latency_ms", "ordinal", "outcome", "receipt_count", "receipt_sql",
            "row_sql", "slot_wait_ms", "sql", "start_offset_ms"}
    for item in schedule:
        row, journal = observed[item["id"]], started[item["id"]]
        require(set(row) == keys and set(journal) == {"id", "launch_offset_ms"}, "row shape")
        require(all(row[key] == value and type(row[key]) is type(value)
                    for key, value in item.items()), "outcome schedule fields")
        require(row["outcome"] == "success" and row["equal"] is True
                and row["cleanup_equal"] is True, "non-success/equality/cleanup")
        leases, sql, row_sql = (3, 4, 2) if row["lane"] == "legacy" else (1, 3, 1)
        for key, expected in (("checkout", leases), ("checkin", leases), ("sql", sql),
                              ("row_sql", row_sql), ("receipt_sql", 1)):
            require(type(row[key]) is int and row[key] == expected, "count " + key)
        for key in ("latency_ms", "slot_wait_ms", "start_offset_ms"):
            finite(row[key], key)
        finite(journal["launch_offset_ms"], "launch offset")
        require(previous <= journal["launch_offset_ms"] <= row["start_offset_ms"], "timer order")
        previous = journal["launch_offset_ms"]
        require(type(row["hold_ms"]) is list and len(row["hold_ms"]) == leases, "hold shape")
        for hold in row["hold_ms"]:
            finite(hold, "hold finite")
        total = math.fsum(row["hold_ms"])
        require(total <= row["latency_ms"] + .00001, "hold exceeds elapsed")
        rows.append(dict(row, launch_offset_ms=journal["launch_offset_ms"],
                         hold_sum_ms=round(total, 6),
                         unclassified_remainder_ms=round(row["latency_ms"] - total, 6),
                         end_offset_ms=round(row["start_offset_ms"] + row["latency_ms"], 6),
                         ordinal_quartile=row["ordinal"] // 25,
                         launch_wave_proxy=row["ordinal"] // row["concurrency"]))
    for key in ("scheduled", "started", "retained"):
        require(type(summary[key]) is int and summary[key] == 800, "summary population")
    require(summary["not_started"] == summary["pool_checkedout"] == summary["held_records"] == 0
            and summary["started_missing_outcome"] == summary["stopped"] == summary["integrity"] == []
            and summary["metadata_unchanged"] is True, "summary integrity")
    cells = {}
    for cell in summary["cells"]:
        identity = (cell["concurrency"], cell["lane"])
        require(identity not in cells, "duplicate summary cell")
        cells[identity] = cell
    require(set(cells) == {(c, lane) for c in (1, 10, 25, 50) for lane in ("legacy", "new")},
            "summary cells")
    for identity, cell in cells.items():
        selected = [row for row in rows if (row["concurrency"], row["lane"]) == identity]
        expected = dict(concurrency=identity[0], lane=identity[1], scheduled=100, observed=100,
                        missing=0, errors=0, timeouts=0,
                        receipt_population={str(n): sum(row["receipt_count"] == n for row in selected)
                                            for n in (0, 2, 100)},
                        **nearest([row["latency_ms"] for row in selected]))
        require(cell == expected, "summary cell mismatch")
    require(len(summary["relative_fixture_observations"]) == 4, "relative summary shape")
    for index, c in enumerate((1, 10, 25, 50)):
        expected = (cells[c, "new"]["p95_ms"] / cells[c, "legacy"]["p95_ms"] - 1) * 100
        require(summary["relative_fixture_observations"][index] ==
                {"concurrency": c, "new_minus_legacy_p95_percent": expected}, "relative mismatch")
    require(sum(len(row["hold_ms"]) for row in rows) == 1600, "hold population")
    return rows


def time_bin(value, minimum, maximum):
    if maximum == minimum:
        return 0
    return min(3, int(4 * (value - minimum) / (maximum - minimum)))


def stats(rows):
    return {"count": len(rows), "hold_samples": sum(len(row["hold_ms"]) for row in rows),
            "metrics": {key: nearest([row[key] for row in rows]) for key in METRICS},
            "hold_positions": [nearest([row["hold_ms"][position] for row in rows])
                               for position in range(len(rows[0]["hold_ms"]) if rows else 0)]}


def cohorts(rows):
    result = []
    for c in (1, 10, 25, 50):
        for lane in ("legacy", "new"):
            selected = [row for row in rows if row["concurrency"] == c and row["lane"] == lane]
            minimum = min(row["start_offset_ms"] for row in selected)
            maximum = max(row["start_offset_ms"] for row in selected)
            for row in selected:
                row["service_start_bin"] = time_bin(row["start_offset_ms"], minimum, maximum)
            cell = dict(concurrency=c, lane=lane, full=stats(selected),
                        service_start_range_ms=[minimum, maximum])
            for field, values in (("receipt_count", (0, 2, 100)), ("ordinal_quartile", range(4)),
                                  ("launch_wave_proxy", range(math.ceil(100 / c))),
                                  ("service_start_bin", range(4))):
                groups = [{"value": value, **stats([row for row in selected if row[field] == value])}
                          for value in values]
                require(sum(group["count"] for group in groups) == 100, "cohort conservation")
                cell[field] = groups
            result.append(cell)
    return result


def pairs(rows):
    lookup = {(row["concurrency"], row["lane"], row["ordinal"]): row for row in rows}
    result = []
    for c in (1, 10, 25, 50):
        for ordinal in range(100):
            old, new = lookup[c, "legacy", ordinal], lookup[c, "new", ordinal]
            require(old["receipt_count"] == new["receipt_count"], "pair receipt")
            row = dict(concurrency=c, ordinal=ordinal, receipt_count=old["receipt_count"])
            for key in METRICS:
                row["legacy_" + key], row["new_" + key] = old[key], new[key]
                row["new_minus_legacy_" + key] = round(new[key] - old[key], 6)
            result.append(row)
    return result


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def outputs(rows):
    cells = cohorts(rows)
    matched = pairs(rows)
    tail = []
    for lane in ("legacy", "new"):
        selected = sorted((row for row in rows if row["concurrency"] == 25 and row["lane"] == lane),
                          key=lambda row: (-row["latency_ms"], row["ordinal"]))[:15]
        for rank, row in enumerate(selected, 1):
            tail.append({"lane": lane, "tail_rank": rank, **{key: row[key] for key in
                         ("id", "ordinal", "receipt_count", "ordinal_quartile", "launch_wave_proxy",
                          "service_start_bin", "launch_offset_ms", "start_offset_ms", "end_offset_ms",
                          "latency_ms", "hold_sum_ms", "unclassified_remainder_ms")},
                         "hold_ms": json.dumps(row["hold_ms"], separators=(",", ":"))})
    summary = dict(scope="offline single retained fixture; no causal or readiness estimate",
                   arithmetic="per-attempt sums/remainders and matched ordinal differences, rounded6 decimals; "
                              "unclassified remainder is not queue/CPU/overhead/corrected latency",
                   quantiles="nearest rank; empty cohorts=null; full800 outcomes/no filtering",
                   wave="ordinal//concurrency workload launch proxy, not physical acquisition wave",
                   time_bins="four cell-local equal-width service-start-offset bins; max=>3; zero-width=>0",
                   hold_positions="observed checkin-list positions; no individual timestamps/query labels",
                   matched_pairs="concurrency+ordinal/receipt, not simultaneous or causal paired trials",
                   population=dict(requests=800, holds=1600, ordinal_pairs=400, c25_tail_rows=30),
                   cells=cells)
    return {"cohort-summary.json": json_bytes(summary), "c25-tail.csv": csv_bytes(tail),
            "ordinal-pairs.csv": csv_bytes(matched)}


def binding(root, path):
    payload = bounded_path(root, path).read_bytes()
    entries = payload.decode().splitlines()
    require(len(entries) == 4, "source binding entries")
    expected_paths = {str(R16 / "analyzer.py"), str(R16 / "test_analyzer.py"),
                      str(R16 / "selected-inputs.json"),
                      "vibecode_v2/TIP-054.4b-R16_OFFLINE_STATUS_TAIL_ANALYSIS.md"}
    seen = set()
    for line in entries:
        digest, relative = line.split("  ", 1)
        require(relative not in seen and relative in expected_paths, "source binding paths")
        require(sha(bounded_path(root, relative).read_bytes()) == digest, "source binding changed")
        seen.add(relative)
    require(seen == expected_paths, "source binding coverage")
    return sha(payload)


def run(destination, binding_path, actor):
    require(destination.parent.resolve() == (ROOT / R16).resolve()
            and not destination.exists(), "fresh bounded destination required")
    destination.mkdir()
    try:
        code_digest = binding(ROOT, binding_path)
        manifest, payloads = load_inputs()
        generated = outputs(validate(*parse(payloads)))
        require(sum(map(len, generated.values())) <= CAP, "data output cap")
        after_manifest, after_payloads = load_inputs()
        require(manifest == after_manifest and payloads == after_payloads, "inputs changed during analysis")
        require(binding(ROOT, binding_path) == code_digest, "code changed during analysis")
        provenance = dict(actor=actor, destination=str(destination.relative_to(ROOT)),
                          source_binding_path=str(binding_path), source_binding_sha256=code_digest,
                          selected_inputs_sha256=SELECTED_SHA, input_files=14, input_bytes=564033,
                          before_after_identical=True, product_sha256_attributed_to_main=manifest["product_content_sha256"],
                          outputs=[dict(path=name, bytes=len(payload), sha256=sha(payload))
                                   for name, payload in generated.items()])
        generated["provenance.json"] = json_bytes(provenance)
        require(sum(map(len, generated.values())) <= CAP, "all output cap")
        for name, payload in generated.items():
            with (destination / name).open("xb") as stream:
                stream.write(payload)
        print(json.dumps(provenance, sort_keys=True))
    except Exception as error:
        with (destination / "failure.json").open("xb") as stream:
            stream.write(json_bytes(dict(error_type=type(error).__name__, message=str(error))))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--actor", required=True)
    arguments = parser.parse_args()
    run(bounded_path(ROOT, arguments.output), arguments.binding, arguments.actor)
