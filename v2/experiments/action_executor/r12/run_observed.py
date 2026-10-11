"""NEW outer extension; immutable R9/R2/phase/load work executes unchanged."""

import ast
import hashlib
import json
import re
import runpy
import sys
from collections import Counter, defaultdict
from pathlib import Path

from minimal_observer import REFERENCE_ANALYSIS, MinimalObserver, decoded_records


def seal():
    roots = (Path("/work/r12"), Path("/work/r11"), Path("/work/r9"), Path("/work/r/r2"))
    paths = {p for root in roots for p in root.glob("*.py")}
    paths.update(
        (
            Path("/work/r12/run-stage.sh"),
            Path("/work/r/phase_profiler.py"),
            Path("/work/r/run_phase_baseline.py"),
            Path("/work/latency_probe.py"),
        )
    )
    if len(paths) > 40:
        raise ValueError("bounded NEW/reference source list")
    result, total = {}, 0
    for path in sorted(paths):
        size = path.stat().st_size
        total += size
        if size > 4 * 1024**2 or total > 16 * 1024**2:
            raise ValueError("source byte cap")
        result[str(path)] = {"bytes": size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def main():
    # SDK/reference driver imports occur only in the explicitly authorized run.
    # The host-only selected validator/analyzer imports remain stdlib-only.
    for path in ("/work/r", "/work/r/r2", "/work/r9", "/work/r12"):
        sys.path.insert(0, path)
    import audit_tail_observer as audit_module
    import phase_profiler as phase_module
    from pool_boundary_observer import PoolBoundaryObserver

    if len(sys.argv) != 2:
        raise SystemExit("usage: run_observed.py NEW-run-dir")
    output = Path(sys.argv[1])
    if not str(output).startswith("/evidence/") or output.exists():
        raise ValueError("NEW exclusive run required")
    before = seal()
    observer = MinimalObserver(output)
    saved = []

    def patch(cls, name, value):
        saved.append((cls, name, vars(cls)[name]))
        setattr(cls, name, value)

    phase_install = phase_module.PhaseProfiler.install
    boundary_install = PoolBoundaryObserver.install
    audit_install = audit_module.AuditTailObserver.install

    def install_phase(profiler):
        result = phase_install(profiler)
        observer.attach_phase(profiler, phase_module)
        return result

    def install_boundary(boundary):
        result = boundary_install(boundary)
        observer.attach_boundary(boundary)
        return result

    def install_audit(tail):
        result = audit_install(tail)
        observer.attach_audit(tail, audit_module)
        return result

    patch(phase_module.PhaseProfiler, "install", install_phase)
    patch(PoolBoundaryObserver, "install", install_boundary)
    patch(audit_module.AuditTailObserver, "install", install_audit)
    primary = None
    faults = []
    try:
        runpy.run_path("/work/r9/run_observed.py", run_name="__main__")
    except BaseException as error:
        primary = error
        raise
    finally:
        # Original R9/R2 has finalized reference emit/phase streams already.
        try:
            observer.close()
            packet = observer.snapshot()
            records = decoded_records(packet)
            if not records or any(packet["integrity"].values()):
                raise ValueError("NEW observer measurement incomplete")
        except BaseException as error:
            faults.append(error)
        for cls, name, old in reversed(saved):
            try:
                setattr(cls, name, old)
            except BaseException as error:
                faults.append(error)
        try:
            after = seal()
            packet = {
                "before": before,
                "after": after,
                "unchanged": before == after,
                "delegate_error_type": type(primary).__name__ if primary else None,
                "diagnostic_faults": [type(error).__name__ for error in faults],
                "scope": (
                    "NEW/reference seal; immutable outer400/current8/history gate remains required"
                ),
            }
            raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
            added = sum(path.stat().st_size for path in output.glob("minimal-exposure.json")) + len(
                raw
            )
            if added > MinimalObserver.MAX_BYTES:
                raise ValueError("total NEW run output exceeds128MiB")
            if output.exists():
                with (output / "r12-source-seal.json").open("xb") as stream:
                    stream.write(raw)
            if before != after:
                raise ValueError("NEW/reference source bytes changed")
        except BaseException as error:
            faults.append(error)
        if faults:
            if primary is not None:
                for error in faults:
                    primary.add_note("R12 finalization/seal raised " + type(error).__name__)
            else:
                raise faults[0]


def validate_run(root):
    """Read-only selected-population gate. Original R9/chain gates stay separate."""
    root = Path(root).resolve()
    names = (
        "minimal-exposure.json",
        "r12-source-seal.json",
        "phase-requests.jsonl",
        "pool-boundaries.json",
        "samples.json",
        "samples.jsonl",
        "audit-transactions.jsonl",
    )
    data, total = {}, 0
    for name in names:
        path = root / name
        size = path.stat().st_size
        total += size
        if (
            path.is_symlink()
            or path.resolve() != path
            or size > MinimalObserver.MAX_BYTES
            or total > 256 * 1024**2
        ):
            raise ValueError("validation input cap/path")
        raw = path.read_bytes()
        data[name] = (
            [json.loads(line) for line in raw.splitlines() if line]
            if name.endswith(".jsonl")
            else json.loads(raw)
        )
    packet = data["minimal-exposure.json"]
    rows = decoded_records(packet)
    if (
        not rows
        or any(packet["integrity"].values())
        or packet["limits"] != {"records": 800000, "bytes": 134217728, "seconds": 180}
    ):
        raise ValueError("selected measurement incomplete/bounds")
    source_seal = data["r12-source-seal.json"]
    if (
        not source_seal["unchanged"]
        or source_seal["before"] != source_seal["after"]
        or source_seal["diagnostic_faults"]
    ):
        raise ValueError("source/closing integrity")
    samples = data["samples.json"]
    if not samples or samples != data["samples.jsonl"] or len(samples) > 1600:
        raise ValueError("sample representations/count")
    reference = REFERENCE_ANALYSIS
    keys = [reference.identity(sample) for sample in samples]
    phases = data["phase-requests.jsonl"]
    phase_by_key = {phase["request_id"]: phase for phase in phases}
    if (
        len(set(keys)) != len(keys)
        or len(phase_by_key) != len(phases)
        or set(keys) != set(phase_by_key)
    ):
        raise ValueError("sample/phase exact identity population")
    grouped = defaultdict(list)
    for row in rows:
        if row["request_id"] is not None:
            grouped[row["request_id"]].append(row)
    if set(grouped) != set(keys):
        raise ValueError("selected captured request population")
    expected_boundaries = Counter(
        event["request_id"] for event in data["pool-boundaries.json"]["events"]
    )
    if (
        not expected_boundaries
        or any(data["pool-boundaries.json"]["integrity"].values())
        or set(expected_boundaries) != set(keys)
    ):
        raise ValueError("original R9 graph integrity/population")
    # Pinned R9 callback sites: sync/async/queue-get/wake begin and finish.
    # Counts are not event-ID or physical-resource identity bridges.
    begin_labels = {"R9.recording@193", "R9.recording@234", "R9.recording@356", "R9.recording@412"}
    finish_labels = {"R9.recording@209", "R9.recording@248", "R9.recording@372", "R9.recording@426"}
    for key in keys:
        if (
            sum(row["label"] in begin_labels for row in grouped[key]) != expected_boundaries[key]
            or sum(row["label"] in finish_labels for row in grouped[key])
            != expected_boundaries[key]
        ):
            raise ValueError("R9 selected callback population not complete")
    callback_source = Path(__file__).resolve().parent.parent / "r9/pool_boundary_observer.py"
    if callback_source.is_symlink() or callback_source.stat().st_size > 524288:
        raise ValueError("callback source path/cap")
    callback_bytes = callback_source.read_bytes()
    if (
        hashlib.sha256(callback_bytes).hexdigest()
        != "1029c26e9ec2b50002835435e67262becfc0c6b320fcb183945e931ede8fd914"
    ):
        raise ValueError("pinned R9 callback source changed")
    tree = ast.parse(callback_bytes)
    callback_lines = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Attribute)
            or node.func.attr != "recording"
            or not isinstance(node.func.value, ast.Name)
            or node.func.value.id != "self"
        ):
            continue
        if not node.args:
            raise ValueError("unknown pinned recording call shape")
        callback = node.args[0]
        if isinstance(callback, ast.Lambda):
            callback_lines.add(callback.lineno)
        elif isinstance(callback, ast.Name) and callback.id in {"captured", "details", "ready"}:
            definitions = [
                item
                for item in ast.walk(tree)
                if isinstance(item, ast.FunctionDef) and item.name == callback.id
            ]
            if len(definitions) != 1:
                raise ValueError("ambiguous named recording callback")
            callback_lines.add(definitions[0].lineno)
        else:
            raise ValueError("unsupported pinned recording callback")
    reference_labels = {
        "phase.finish_phase",
        "phase.serialize",
        "phase.write",
        "phase.flush",
        "audit.emit",
        "audit.serialize",
        "audit.write",
        "audit.flush",
    }
    for row in rows:
        label = row["label"]
        match = re.fullmatch(r"R9.recording@([1-9][0-9]*)", label)
        if label not in reference_labels and not (
            match and int(match[1]) in callback_lines and row["source_line"] == int(match[1])
        ):
            raise ValueError("unselected/unknown callback label")
    for key, phase in phase_by_key.items():
        if (
            type(phase["start_ns"]) is not int
            or type(phase["end_ns"]) is not int
            or phase["start_ns"] < 0
            or phase["end_ns"] < phase["start_ns"]
            or phase["closed"] is not True
        ):
            raise ValueError("closed HTTP clock/identity envelope")
        reference.phase_witnesses(grouped[key], phase)
    transactions = data["audit-transactions.jsonl"]
    expected_audits = Counter(tx["request_id"] for tx in transactions)
    if not transactions or set(expected_audits) - set(keys):
        raise ValueError("audit transaction orphan")
    for key in keys:
        actual = grouped[key]
        emitted = [row for row in actual if row["label"] == "audit.emit"]
        if len(emitted) != expected_audits[key]:
            raise ValueError("audit emit transaction cardinality")
        for label in ("audit.serialize", "audit.write", "audit.flush"):
            children = [row for row in actual if row["label"] == label]
            if len(children) != len(emitted):
                raise ValueError("audit child family cardinality")
        for parent in emitted:
            children = {
                label: [
                    row
                    for row in actual
                    if row["label"] == label and parent["span_id"] in row["parent_ids"]
                ]
                for label in ("audit.serialize", "audit.write", "audit.flush")
            }
            if any(len(values) != 1 for values in children.values()):
                raise ValueError("audit per-emit child association")
            serial, write, flush = (children[label][0] for label in children)
            if any(
                row["start_ns"] is None or row["end_ns"] is None or row["error_type"] is not None
                for row in (parent, serial, write, flush)
            ):
                raise ValueError("audit child clock/outcome")
            if (
                not parent["start_ns"]
                <= serial["start_ns"]
                <= serial["end_ns"]
                <= write["start_ns"]
                <= write["end_ns"]
                <= flush["start_ns"]
                <= flush["end_ns"]
                <= parent["end_ns"]
            ):
                raise ValueError("audit emit reference order")
    return {
        "status": "SELECTED_POPULATION_PASS_NOT_SLA",
        "samples": len(keys),
        "records": len(rows),
        "phase_finish": sum(len(p["phases"]) for p in phases),
        "audit_emit": len(transactions),
        "R9_recording_rows": sum(row["label"].startswith("R9.recording@") for row in rows),
        "R9_event_reference_n": sum(expected_boundaries.values()),
        "unassigned_origins": dict(
            Counter(row["origin"] for row in rows if row["request_id"] is None)
        ),
        "omitted_helpers": "UNMEASURED_NOT_ZERO",
        "integrity": packet["integrity"],
        "censorship": packet["censorship"],
    }


if __name__ == "__main__":
    main()
