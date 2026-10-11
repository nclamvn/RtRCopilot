"""NEW bounded observer; execute the original R2/phase/load helpers unchanged."""

import hashlib
import json
import runpy
import sys
from pathlib import Path

sys.path.insert(0, "/work/r")
sys.path.insert(0, "/work/r/r2")
sys.path.insert(0, "/work/r9")
from phase_profiler import PhaseProfiler  # noqa: E402
from pool_boundary_observer import PoolBoundaryObserver  # noqa: E402


def seal():
    backend = Path("/workspace/v2/apps/backend")
    paths = [
        *sorted((backend / "src").rglob("*.py")),
        *sorted((backend / "migrations").rglob("*.py")),
        *sorted(Path("/work/r9").glob("*.py")),
        Path("/work/latency_probe.py"),
        Path("/work/r/phase_profiler.py"),
        Path("/work/r/run_phase_baseline.py"),
        Path("/work/r/pg_monitor.py"),
        Path("/work/r/r2/run_observed.py"),
        Path("/work/r/r2/audit_tail_observer.py"),
        backend / "pyproject.toml",
        backend / "uv.lock",
    ]
    paths = sorted(set(paths))
    if len(paths) > 600:
        raise ValueError("bounded source inventory exceeded")
    result, total = {}, 0
    for path in paths:
        size = path.stat().st_size
        total += size
        if size > 8 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise ValueError("bounded source bytes exceeded")
        result[str(path)] = {"bytes": size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_observed.py NEW-evidence-directory")
    output = Path(sys.argv[1])
    if not str(output).startswith("/evidence/") or output.exists():
        raise ValueError("new evidence output required")
    before = seal()
    original_install, original_close = PhaseProfiler.install, PhaseProfiler.close

    def install(profiler):
        original_install(profiler)
        profiler.r9_boundary = PoolBoundaryObserver(profiler.engine, profiler.output)
        profiler.r9_boundary.install()

    def close(profiler):
        primary = sys.exception()
        failures = []
        try:
            boundary = getattr(profiler, "r9_boundary", None)
            if boundary is not None:
                boundary.close()
        except BaseException as caught:
            failures.append(caught)
        try:
            original_close(profiler)
        except BaseException as caught:
            failures.append(caught)
        if failures:
            if primary is not None:
                for fault in failures:
                    primary.add_note("observer finalization raised " + type(fault).__name__)
            else:
                raise failures[0]

    PhaseProfiler.install, PhaseProfiler.close = install, close
    error = None
    try:
        # ORIGINAL R2 installs its original audit observer around our extension.
        runpy.run_path("/work/r/r2/run_observed.py", run_name="__main__")
    except BaseException as caught:
        error = caught
        raise
    finally:
        PhaseProfiler.install, PhaseProfiler.close = original_install, original_close
        try:
            after = seal()
            packet = {
                "before": before,
                "after": after,
                "unchanged": before == after,
                "seal_scope": "selected sources; original outer400 gate remains required",
                "delegate_error_type": type(error).__name__ if error else None,
            }
            if output.exists():
                with (output / "r9-source-seal.json").open("x") as stream:
                    json.dump(packet, stream, sort_keys=True, indent=2)
            if before != after:
                raise RuntimeError("source integrity failed")
        except BaseException as fault:
            if error is not None:
                error.add_note("source sealing raised " + type(fault).__name__)
            else:
                raise


if __name__ == "__main__":
    main()
