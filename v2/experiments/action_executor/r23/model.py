"""Pure R23 wire/topology model, not an installed observer or runtime proof."""

import json
import re

SLOTS, PER_SLOT, EVENT_BYTES = 1600, 32, 32
MAX_US = 199999999
FIELDS = ("slot", "operation", "path", "phase", "generation", "context",
          "edge", "us", "outcome", "error")
WIDTHS = (4, 1, 1, 2, 1, 1, 1, 9, 1, 1)
MAXIMA = (1599, 3, 3, 15, 3, 4, 1, MAX_US, 4, 3)
MANIFEST = {"schema": "R23-ASCII32-v1", "slots": SLOTS, "events_per_slot": PER_SLOT,
            "event_bytes": EVENT_BYTES, "max_us": MAX_US,
            "outcomes": "begin_ok_error_cancel_incomplete", "capture_admission": "HOLD"}
HEADER = b"R23P1\n" + json.dumps(MANIFEST, sort_keys=True, separators=(",", ":")).encode() + b"\n"
# Phase0 service; phase2 acquisition; remaining named seams are path/context-specific.
# Cancel generation0 means ordinary context, NOT RequestConnection generation.
PLANS = {
    0: ((0, 0, 0), (1, 1, 1), (2, 1, 1), (3, 1, 1), (4, 2, 2),
        (2, 2, 2), (5, 2, 2), (6, 2, 2), (7, 2, 2), (8, 2, 2),
        (9, 2, 2), (10, 2, 2), (11, 3, 3), (7, 3, 3), (12, 3, 3), (13, 3, 3)),
    1: ((0, 0, 0), (1, 1, 1), (2, 1, 1), (3, 1, 1), (4, 2, 2),
        (2, 2, 2), (5, 2, 2), (6, 2, 2), (7, 2, 2), (8, 2, 2),
        (9, 2, 2), (10, 2, 2), (11, 3, 3), (12, 3, 3), (13, 3, 3)),
    2: ((0, 0, 0), (1, 1, 1), (2, 1, 1), (3, 1, 1)),
    3: ((0, 0, 0), (1, 0, 1), (2, 0, 1), (3, 0, 1),
        (1, 0, 2), (2, 0, 2), (3, 0, 2), (4, 0, 3), (2, 0, 3),
        (5, 0, 3), (9, 0, 3), (10, 0, 3), (11, 0, 4), (2, 0, 4), (12, 0, 4)),
}
ORIGIN_KEYS = {"policy_current_identity", "service_identity", "factory_identity",
               "factory_options", "sql_topology", "checkout_topology"}


def need(value, message):
    if not value:
        raise ValueError(message)


def encode(event):
    need(type(event) is dict and set(event) == set(FIELDS), "closed fields")
    values = [event[name] for name in FIELDS]
    need(all(type(v) is int and 0 <= v <= maximum for v, maximum in zip(values, MAXIMA)),
         "finite integer domains; no bool/free text")
    need(event["operation"] == event["path"] == event["slot"] % 4, "exact slot/path/op")
    need((event["phase"], event["generation"], event["context"]) in PLANS[event["path"]],
         "unsupported topology")
    if event["edge"] == 0:
        need(event["outcome"] == event["error"] == 0, "begin has no outcome")
    else:
        need(event["outcome"] > 0 and ((event["outcome"] == 2 and event["error"] > 0)
             or (event["outcome"] != 2 and event["error"] == 0)), "terminal outcome/error")
    wire = ("|".join(f"{v:0{w}d}" for v, w in zip(values, WIDTHS)) + "\n").encode()
    need(len(wire) == EVENT_BYTES, "fixed event framing")
    return wire


def decode(wire):
    pattern = "\\|".join("[0-9]{" + str(width) + "}" for width in WIDTHS) + "\n"
    need(type(wire) is bytes and len(wire) == EVENT_BYTES and re.fullmatch(pattern.encode(), wire),
         "canonical ASCII frame")
    event = dict(zip(FIELDS, map(int, wire[:-1].split(b"|"))))
    need(encode(event) == wire, "exact round trip")
    return event


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        need(type(start) is int and type(end) is int and 0 <= start <= end <= MAX_US, "interval")
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return sum(end - start for start, end in result)


def attribution(events):
    need(len(events) <= PER_SLOT, "per-slot capacity; reject whole retained packet")
    need(events and len({(e["slot"], e["operation"], e["path"]) for e in events}) == 1,
         "one exact request slot")
    opened, closed, previous = {}, {}, -1
    for event in events:
        encode(event)
        need(event["us"] >= previous, "per-slot timestamp order")
        previous = event["us"]
        key = event["phase"], event["generation"], event["context"]
        if event["edge"] == 0:
            need(key not in opened and key not in closed, "duplicate span/retry logging")
            opened[key] = event["us"]
        else:
            need(key in opened, "unpaired terminal")
            closed[key] = (opened.pop(key), event["us"], event["outcome"])
    service = closed.get((0, 0, 0))
    if opened or service is None or any(value[2] == 4 for value in closed.values()):
        return {"state": "I", "reason": "incomplete retained; no invented endpoint", "pairs": len(closed)}
    lo, hi, outcome = service
    need(all(lo <= start <= end <= hi for start, end, _ in closed.values()), "span outside service")
    expected = set(PLANS[events[0]["path"]])
    if set(closed) != expected or outcome != 1 or any(value[2] != 1 for value in closed.values()):
        return {"state": "F", "reason": "error/cancel/unvisited essential spans retained; HOLD", "pairs": len(closed)}
    children = [(start, end) for key, (start, end, _) in closed.items() if key != (0, 0, 0)]
    path = events[0]["path"]
    mains = ((1, 1, 1), (4, 2, 2), (11, 3, 3)) if path < 2 else (
        ((1, 1, 1),) if path == 2 else ((1, 0, 1), (1, 0, 2), (4, 0, 3), (11, 0, 4)))
    need(all(closed[a][1] <= closed[b][0] for a, b in zip(mains, mains[1:])),
         "initial/mutation/final must not share an overlapping TX interval")
    for key, (start, end, _) in closed.items():
        if key == (0, 0, 0) or key in mains:
            continue
        parent = next(main for main in mains if main[1:] == key[1:])
        need(closed[parent][0] <= start <= end <= closed[parent][1], "child outside context")
    for main in mains:
        sequence = [key for key in PLANS[path] if key[1:] == main[1:] and key != main]
        need(all(closed[a][1] <= closed[b][0] for a, b in zip(sequence, sequence[1:])),
             "source-ordered acquire/fence/checkpoint/append/commit/terminal")
    covered = union(children)
    return {"state": "C", "pairs": len(closed), "service_us": hi - lo,
            "child_union_us": covered, "unobserved_residual_us": hi - lo - covered}


def packet(events, dispositions, fault=(0, 0)):
    need(type(events) is list and len(events) <= SLOTS * PER_SLOT, "packet event capacity")
    need(type(dispositions) is str and len(dispositions) == SLOTS
         and set(dispositions) <= set("CFIN"), "fixed slot coverage vector")
    need(type(fault) is tuple and len(fault) == 2 and all(type(v) is int for v in fault)
         and 0 <= fault[0] < SLOTS and 0 <= fault[1] <= 99, "bounded fault frame")
    by_slot = {}
    wire = []
    for event in events:
        wire.append(encode(event))
        by_slot.setdefault(event["slot"], []).append(event)
    for slot, rows in by_slot.items():
        need(attribution(rows)["state"] == dispositions[slot], "honest paired slot coverage")
    need(all(flag == "N" for slot, flag in enumerate(dispositions) if slot not in by_slot),
         "missing slot not explicitly unlaunched")
    state = "C" if set(dispositions) == {"C"} and fault[1] == 0 else "I"
    result = HEADER + b"SLOTS|" + dispositions.encode() + b"\n" + b"".join(wire)
    result += f"FAULT|{fault[0]:04d}|{fault[1]:02d}\nEND|{len(events):05d}|{state}\n".encode()
    need(len(result) <= budget()["observer_wire_bytes"], "wire budget")
    return result


def parse_packet(wire):
    need(type(wire) is bytes and len(wire) <= budget()["observer_wire_bytes"], "bounded packet")
    lines = wire.splitlines(keepends=True)
    need(len(lines) >= 5 and b"".join(lines[:2]) == HEADER, "exact manifest/header")
    need(lines[2].startswith(b"SLOTS|") and lines[2].endswith(b"\n"), "slot framing")
    fault = re.fullmatch(rb"FAULT\|([0-9]{4})\|([0-9]{2})\n", lines[-2])
    need(fault is not None, "fault framing")
    events = [decode(line) for line in lines[3:-2]]
    dispositions = lines[2][6:-1].decode("ascii")
    need(packet(events, dispositions, tuple(map(int, fault.groups()))) == wire,
         "canonical count/trailer/coverage agreement")
    return events, dispositions


def budget(original_bounds=None):
    # Every span gets at most one enter and one terminal; error/incomplete never
    # adds another retry pair. All1600 nominal paths can attain these counts.
    max_events = (SLOTS // 4) * sum(2 * len(plan) for plan in PLANS.values())
    framing = len(HEADER) + 6 + SLOTS + 1 + 14 + 12
    observer = max_events * EVENT_BYTES + framing
    components = ("original_journal_final_json", "original_stderr_stdout",
                  "process_owner_supervisor", "source_contract_checks_and_closure")
    proved = type(original_bounds) is dict and set(original_bounds) == set(components)
    if proved:
        proved = all(type(v) is int and v >= 0 for v in original_bounds.values())
    total = observer + sum(original_bounds.values()) if proved else None
    return {"event_bytes": EVENT_BYTES, "capacity_events": SLOTS * PER_SLOT,
            "reachable_max_events": max_events,
            "framing_bytes": framing, "observer_wire_bytes": observer,
            "raw_cap_bytes": 10485760, "original_components": components,
            "original_bounds_proved": False,
            "hypothetical_declared_total_bytes": total,
            "capture_admission": "HOLD",
            "unresolved": "No source-proved maxima for original outputs; declarations/reserves and R21 actual sizes are not proofs. Polling cap can overshoot."}


def origin_model(flags):
    return type(flags) is dict and set(flags) == ORIGIN_KEYS and all(value is True for value in flags.values())


def call_model(original, args, kwargs, registry, *, enabled=False):
    """Synchronous in-memory stand-in. No installed hook/SQL/await runtime claim."""
    need(type(enabled) is bool, "exact OFF/ON model flag")
    if not enabled:
        return original(*args, **kwargs)
    key = "r23_model_observer"
    absent = object()
    before = registry.get(key, absent)
    registry[key] = True
    try:
        return original(*args, **kwargs)
    finally:
        if before is absent:
            registry.pop(key, None)
        else:
            registry[key] = before


if __name__ == "__main__":
    print(json.dumps(budget(), indent=2, sort_keys=True))
