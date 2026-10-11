"""Run the ORIGINAL unchanged load; observer OFF/ON are new R-only wrappers."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

from rtr_copilot.config import get_settings
from rtr_copilot.db.engine import runtime_engine

root = Path(sys.argv[1])
assert str(root).startswith("/evidence/")
mode = sys.argv[2]
assert mode in {"off", "on"}
root.mkdir(exist_ok=True)
engine = runtime_engine()
settings = get_settings()
assert engine.sync_engine.pool.size() == 5
assert engine.sync_engine.pool._max_overflow == 5
assert engine.sync_engine.pool._pre_ping is True
assert settings.action_executor_operation_timeout_seconds == 0.9
assert settings.limits_rate_render_max == 5000
assert settings.limits_rate_default_read_max == 5000
(root / "r-controls.json").write_text(
    json.dumps(
        {
            "observer": mode,
            "pool_size": 5,
            "max_overflow": 5,
            "pre_ping": True,
            "operation_timeout_seconds": 0.9,
            "old_load_helper": "/work/latency_probe.py",
            "provider": False,
            "worker": False,
            "authority_override": "Existing current synthetic subject dependency ONLY",
        },
        indent=2,
    )
)
profiler = monitor = None
try:
    if mode == "on":
        from phase_profiler import PhaseProfiler

        profiler = PhaseProfiler(engine, root)
        profiler.install()
        monitor_stdout = (root / "monitor.stdout.txt").open("x")
        monitor_stderr = (root / "monitor.stderr.txt").open("x")
        monitor = subprocess.Popen(
            [sys.executable, "/work/r/pg_monitor.py", str(root)],
            env=dict(os.environ),
            stdout=monitor_stdout,
            stderr=monitor_stderr,
        )
    # The original script retains all samples, identical seed/load and oracles.
    runpy.run_path("/work/latency_probe.py", run_name="__main__")
finally:
    if monitor is not None:
        (root / "monitor.stop").touch()
        forced = False
        try:
            exit_code = monitor.wait(timeout=6)
        except subprocess.TimeoutExpired:
            forced = True
            monitor.kill()
            exit_code = monitor.wait(timeout=3)
        monitor_stdout.close()
        monitor_stderr.close()
        (root / "monitor-process.json").write_text(
            json.dumps(
                {"pid": monitor.pid, "exit_code": exit_code, "forced_kill": forced}, indent=2
            )
        )
    if profiler is not None:
        profiler.close()
