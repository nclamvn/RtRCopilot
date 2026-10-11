"""Finite, stdlib-only evidence core. Never imports or configures application code."""

import asyncio
import json
import math
import time
from pathlib import Path

EVENTS_PER_ATTEMPT = 128
CAMPAIGN_EVENTS = 100000
LAG_SAMPLES = 18000
OUTPUT_CAP = 10 * 1024 * 1024
RESERVE = 1024 * 1024
ORDER = ("D-legacy", "D-new", "M-new", "M-legacy", "M-legacy", "M-new", "D-new", "D-legacy")


def schedule():
    return [
        dict(id=f"cell{cell:02d}_{mode}_{lane}_{ordinal:03d}", cell=cell,
             mode=mode, lane=lane, ordinal=ordinal, concurrency=25,
             receipt_count=(0, 2, 100)[ordinal % 3])
        for cell, label in enumerate(ORDER, 1)
        for mode, lane in [label.split("-")]
        for ordinal in range(100)
    ]


def encode(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


class Collector:
    """Callback-safe failures: stop launches, do not replace application exceptions."""

    def __init__(self, clock=time.perf_counter_ns):
        self.clock = clock
        self.origin = clock()
        self.events = []
        self.counts = {}
        self.lag = []
        self.faults = []
        self.last_ns = 0
        self.span_sequence = 0

    def fault(self, code):
        if code not in self.faults and len(self.faults) < 24:
            self.faults.append(code)

    def stamp(self):
        value = self.clock() - self.origin
        if not isinstance(value, int) or value < self.last_ns:
            self.fault("clock_integrity")
            return None
        self.last_ns = value
        return value

    def emit(self, tag, kind, **fields):
        # Only bounded symbolic fields are accepted at call sites; no SQL/errors repr.
        if tag is None:
            return
        if self.counts.get(tag, 0) >= EVENTS_PER_ATTEMPT:
            self.fault("attempt_event_cap")
            return
        if len(self.events) >= CAMPAIGN_EVENTS:
            self.fault("campaign_event_cap")
            return
        stamp = self.stamp()
        if stamp is None:
            return
        self.events.append(dict(attempt=tag, kind=kind, ns=stamp, seq=len(self.events), **fields))
        self.counts[tag] = self.counts.get(tag, 0) + 1

    def begin(self, tag, kind, **fields):
        self.span_sequence += 1
        span = self.span_sequence
        self.emit(tag, kind + "_begin", span=span, **fields)
        return span

    def end(self, tag, kind, span, error=None, **fields):
        self.emit(tag, kind + ("_error" if error is not None else "_end"),
                  span=span, error_type=type(error).__name__[:80] if error else None, **fields)

    def lag_sample(self, cell, target, observed):
        if len(self.lag) >= LAG_SAMPLES:
            self.fault("lag_cap")
            return
        if not (math.isfinite(target) and math.isfinite(observed) and observed >= target):
            self.fault("lag_integrity")
            return
        self.lag.append(dict(cell=cell, ns=self.stamp(), lag_ms=(observed - target) * 1000))


async def sample_lag(collector, cell, done, clock=time.monotonic, sleep=asyncio.sleep):
    while not done.is_set() and not collector.faults:
        target = clock() + 0.010
        await sleep(0.010)
        if not done.is_set():
            collector.lag_sample(cell, target, clock())
        # Next target is based on current time: never catch up missed ticks.


class Output:
    """One campaign budget, exclusive fresh files; summary/missing get reserved space."""

    def __init__(self, destination):
        self.destination = Path(destination)
        self.used = 0
        self.handles = {}

    def append(self, name, value, reserve=False):
        payload = encode(value)
        ceiling = OUTPUT_CAP if reserve else OUTPUT_CAP - RESERVE
        if self.used + len(payload) > ceiling:
            return False
        if name not in self.handles:
            self.handles[name] = (self.destination / name).open("xb")
        self.handles[name].write(payload)
        self.handles[name].flush()
        self.used += len(payload)
        return True

    def close(self):
        for handle in self.handles.values():
            handle.close()


def percentiles(values):
    ordered = sorted(values)
    if any(not math.isfinite(v) or v < 0 for v in ordered):
        raise ValueError("nonfinite_or_negative")
    return {key: ordered[max(0, math.ceil(len(ordered) * q) - 1)] if ordered else None
            for key, q in (("p50_ms", .5), ("p95_ms", .95), ("p99_ms", .99), ("max_ms", 1))}


def analyze(planned, rows, started, events, lag):
    """Deterministic reconstruction, all observed errors included; no span addition."""
    expected = schedule()
    if planned != expected:
        raise ValueError("schedule_corruption")
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != {item["id"] for item in planned}:
        raise ValueError("outcome_conservation")
    start_ids = [row["id"] for row in started]
    if len(set(start_ids)) != len(start_ids) or not set(start_ids) <= set(by_id):
        raise ValueError("journal_corruption")
    for item in planned:
        row = by_id[item["id"]]
        if any(row.get(key) != value for key, value in item.items()):
            raise ValueError("identity_corruption")
        elapsed = row.get("latency_ms")
        if row["outcome"] == "missing":
            if elapsed is not None:
                raise ValueError("invented_missing_latency")
        elif item["id"] not in start_ids or elapsed is None:
            raise ValueError("missing_journal_or_latency")
        elif not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("latency_corruption")
    spans = {}
    measured = {identity: {} for identity in by_id}
    previous = -1
    if len(events) > CAMPAIGN_EVENTS or len(lag) > LAG_SAMPLES:
        raise ValueError("evidence_cap")
    event_counts = {}
    for sequence, row in enumerate(events):
        tag = row["attempt"]
        if tag not in by_id or by_id[tag]["mode"] != "D":
            raise ValueError("event_scope")
        event_counts[tag] = event_counts.get(tag, 0) + 1
        if event_counts[tag] > EVENTS_PER_ATTEMPT:
            raise ValueError("attempt_cap")
        stamp = row["ns"]
        if row["seq"] != sequence or not isinstance(stamp, int) or stamp < previous:
            raise ValueError("event_order")
        previous = stamp
        kind = row["kind"]
        if "span" in row:
            base, terminal = kind.rsplit("_", 1)
            key = (tag, base, row["span"])
            if terminal == "begin":
                if key in spans:
                    raise ValueError("duplicate_span")
                spans[key] = stamp
            elif terminal in ("end", "error"):
                if key not in spans or stamp < spans[key]:
                    raise ValueError("unpaired_span")
                measured[tag].setdefault(base, []).append((stamp - spans.pop(key)) / 1e6)
    for row in lag:
        if row["cell"] not in (1, 2, 7, 8) or row["ns"] is None:
            raise ValueError("lag_scope")
        if not math.isfinite(row["lag_ms"]) or row["lag_ms"] < 0:
            raise ValueError("lag_value")

    def distribution(selected):
        observed = [row for row in selected if row.get("latency_ms") is not None]
        detailed = [row for row in selected if row["mode"] == "D"]
        intervals = sorted({kind for row in detailed for kind in measured[row["id"]]})
        return dict(scheduled=len(selected), observed=len(observed),
                    errors=sum(row["outcome"] != "success" for row in observed),
                    timeouts=sum(row["outcome"] == "timeout" for row in observed),
                    missing=len(selected) - len(observed),
                    receipt_population={str(n): sum(row["receipt_count"] == n for row in selected)
                                        for n in (0, 2, 100)},
                    latency=percentiles([row["latency_ms"] for row in observed]),
                    success_only=percentiles([row["latency_ms"] for row in observed
                                              if row["outcome"] == "success"]),
                    intervals={kind: percentiles([v for row in detailed
                                                  for v in measured[row["id"]].get(kind, [])])
                               for kind in intervals},
                    events=sum(event_counts.get(row["id"], 0) for row in selected))
    groups = []
    for cell in range(1, 9):
        selected = [row for row in rows if row["cell"] == cell]
        groups.append(dict(cell=cell, label=ORDER[cell-1], **distribution(selected),
                           lag=percentiles([row["lag_ms"] for row in lag if row["cell"] == cell])))
    cohorts = [dict(mode=mode, lane=lane, receipt_count=n,
                    **distribution([row for row in rows if row["mode"] == mode
                                    and row["lane"] == lane and (n is None or row["receipt_count"] == n)]))
               for mode in ("D", "M") for lane in ("legacy", "new") for n in (None, 0, 2, 100)]
    return dict(scheduled=800, retained=len(rows), started=len(start_ids), cells=groups,
                cohorts=cohorts, not_started=sorted(set(by_id) - set(start_ids)),
                started_missing=[tag for tag in start_ids if by_id[tag]["outcome"] == "missing"],
                unmatched_spans=[dict(attempt=k[0], kind=k[1], span=k[2]) for k in sorted(spans)],
                gate=all(g["missing"] == g["errors"] == 0 and
                         g["latency"]["p95_ms"] is not None and g["latency"]["p95_ms"] <= 1000
                         for g in groups),
                semantics={"acquisition": "Pool.connect composite; excludes subsequent Engine setup",
                           "query": "cursor composite; excludes receipt mappings/all and DTO",
                           "intervals": "overlap, never add or percentile-subtract",
                           "lag": "sampled scheduling, not CPU causality",
                           "minimal": "R15 aggregates/journal remain; incremental exposure only"})


def reconstruct(destination):
    root = Path(destination)
    read = lambda name: [json.loads(line) for line in (root / name).read_text().splitlines()]
    return analyze(read("schedule.jsonl"), read("outcomes.jsonl"), read("started.jsonl"),
                   read("events.jsonl") if (root / "events.jsonl").exists() else [],
                   read("lag.jsonl") if (root / "lag.jsonl").exists() else [])


if __name__ == "__main__":
    import sys
    print(json.dumps(reconstruct(sys.argv[1]), sort_keys=True, allow_nan=False))
