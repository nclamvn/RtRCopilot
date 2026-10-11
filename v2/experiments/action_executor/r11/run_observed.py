"""NEW outer extension; immutable R9/R2/phase/load work executes unchanged."""

import hashlib
import json
import runpy
import sys
from pathlib import Path

sys.path.insert(0, "/work/r")
sys.path.insert(0, "/work/r/r2")
sys.path.insert(0, "/work/r9")
sys.path.insert(0, "/work/r11")

import audit_tail_observer as audit_module  # noqa: E402
import phase_profiler as phase_module  # noqa: E402
from overhead_observer import ObserverExposure, decoded_records  # noqa: E402
from pool_boundary_observer import PoolBoundaryObserver  # noqa: E402


def seal():
    roots = (Path("/work/r11"), Path("/work/r9"), Path("/work/r/r2"))
    paths = {p for root in roots for p in root.glob("*.py")}
    paths.update(
        (
            Path("/work/r11/run-stage.sh"),
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
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_observed.py NEW-run-dir")
    output = Path(sys.argv[1])
    if not str(output).startswith("/evidence/") or output.exists():
        raise ValueError("NEW exclusive run required")
    before = seal()
    observer = ObserverExposure(output)
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
            added = sum(
                path.stat().st_size for path in output.glob("observer-exposure.json")
            ) + len(raw)
            if added > ObserverExposure.MAX_BYTES:
                raise ValueError("total NEW run output exceeds128MiB")
            if output.exists():
                with (output / "r11-source-seal.json").open("xb") as stream:
                    stream.write(raw)
            if before != after:
                raise ValueError("NEW/reference source bytes changed")
        except BaseException as error:
            faults.append(error)
        if faults:
            if primary is not None:
                for error in faults:
                    primary.add_note("R11 finalization/seal raised " + type(error).__name__)
            else:
                raise faults[0]


if __name__ == "__main__":
    main()
