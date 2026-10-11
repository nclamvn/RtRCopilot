"""Add approved observations to original profiler/load; never change the oracle."""

import runpy
import sys

sys.path.insert(0, "/work/r")
from audit_tail_observer import AuditTailObserver  # noqa: E402
from phase_profiler import PhaseProfiler  # noqa: E402

original_install, original_close = PhaseProfiler.install, PhaseProfiler.close


def install(profiler):
    original_install(profiler)
    profiler.r2_tail = AuditTailObserver(profiler.engine, profiler.output)
    profiler.r2_tail.install()


def close(profiler):
    try:
        tail = getattr(profiler, "r2_tail", None)
        if tail is not None:
            tail.close()
    finally:
        original_close(profiler)


PhaseProfiler.install, PhaseProfiler.close = install, close
sys.argv = ["/work/r/run_phase_baseline.py", sys.argv[1], "on"]
try:
    runpy.run_path("/work/r/run_phase_baseline.py", run_name="__main__")
finally:
    PhaseProfiler.install, PhaseProfiler.close = original_install, original_close
