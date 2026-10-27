"""Real DBOS 3.2/SQLite subprocess evidence with a simulated FunctionModel only."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


WORKER = Path(__file__).resolve().parents[1] / "proof" / "harness_worker.py"


def records(root):
    try:
        with sqlite3.connect(root / "evidence.sqlite") as conn:
            return [(kind, json.loads(data)) for kind, data in conn.execute("SELECT kind,data FROM log ORDER BY seq")]
    except sqlite3.OperationalError:
        return []


def wait_for(root, kind, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        rows = records(root)
        if any(k == kind for k, _ in rows):
            return rows
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"Worker exited {process.returncode}: {stdout}\n{stderr}; rows={rows}")
        time.sleep(0.02)
    raise AssertionError(f"No {kind} within bounded probe; rows={records(root)}")


def test_live_handler_and_real_checkpoint_restart(tmp_path):
    first = subprocess.Popen([sys.executable, str(WORKER), str(tmp_path), "pause"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        before = wait_for(tmp_path, "checkpoint", first)
        # Live deltas precede model finalization, not buffered run-side replay.
        kinds = [kind for kind, _ in before]
        assert kinds.index("text") < kinds.index("model_finished")
        assert sum(k == "tool_effect" for k in kinds) == 1
        assert sum(k == "model_call" for k in kinds) == 2
    finally:
        first.kill()
        first.communicate(timeout=10)
    second = subprocess.run([sys.executable, str(WORKER), str(tmp_path), "resume"], capture_output=True, text=True, timeout=20)
    assert second.returncode == 0, second.stderr
    after = records(tmp_path)
    assert sum(k == "model_call" for k, _ in after) == 2, after
    assert sum(k == "tool_effect" for k, _ in after) == 1, after
    assert sum(k == "published" for k, _ in after) == 1, after
    assert ("result", "first second") in after
    assert ("status", "SUCCESS") in after


def test_real_dbos_cancel_during_model_does_not_publish(tmp_path):
    result = subprocess.run([sys.executable, str(WORKER), str(tmp_path), "cancel"], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    rows = records(tmp_path)
    assert any(k == "cancel_requested" for k, _ in rows), rows
    assert ("status", "CANCELLED") in rows
    assert not any(k == "published" for k, _ in rows), rows
    assert any(k == "exception" for k, _ in rows), rows


def test_crash_after_sql_effect_before_dbos_receipt_reconciles(tmp_path):
    first = subprocess.Popen([sys.executable, str(WORKER), str(tmp_path), "before-receipt-crash"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_for(tmp_path, "before_tool_checkpoint", first)
    finally:
        first.kill()
        first.communicate(timeout=10)
    resumed = subprocess.run([sys.executable, str(WORKER), str(tmp_path), "resume"], capture_output=True, text=True, timeout=20)
    assert resumed.returncode == 0, resumed.stderr
    rows = records(tmp_path)
    assert sum(k == "tool_attempt" for k, _ in rows) == 2, rows
    assert sum(k == "tool_effect" for k, _ in rows) == 1, rows
    assert sum(k == "model_call" for k, _ in rows) == 2, rows
    assert sum(k == "published" for k, _ in rows) == 1, rows


def test_sdk_budget_stops_before_second_model_dispatch(tmp_path):
    result = subprocess.run([sys.executable, str(WORKER), str(tmp_path), "budget"], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    rows = records(tmp_path)
    assert sum(k == "model_call" for k, _ in rows) == 1, rows
    assert ("exception", "UsageLimitExceeded") in rows
    assert not any(k == "published" for k, _ in rows)


def test_recovered_run_keeps_original_deadline(tmp_path):
    first = subprocess.Popen([sys.executable, str(WORKER), str(tmp_path), "deadline"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_for(tmp_path, "before_tool_checkpoint", first)
    finally:
        first.kill()
        first.communicate(timeout=10)
    time.sleep(1.1)
    resumed = subprocess.run([sys.executable, str(WORKER), str(tmp_path), "deadline-resume"], capture_output=True, text=True, timeout=20)
    assert resumed.returncode == 0, resumed.stderr
    rows = records(tmp_path)
    assert ("exception", "RunTimedOut") in rows, rows
    assert sum(k == "model_call" for k, _ in rows) == 1
    assert not any(k == "published" for k, _ in rows)


def test_provisional_events_are_idempotent_if_model_step_restarts(tmp_path):
    first = subprocess.Popen([sys.executable, str(WORKER), str(tmp_path), "stream-crash"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_for(tmp_path, "text", first)
    finally:
        first.kill()
        first.communicate(timeout=10)
    resumed = subprocess.run([sys.executable, str(WORKER), str(tmp_path), "resume"], capture_output=True, text=True, timeout=20)
    assert resumed.returncode == 0, resumed.stderr
    rows = records(tmp_path)
    assert sum(k == "model_call" for k, _ in rows) == 3, rows
    assert sum(k == "tool_effect" for k, _ in rows) == 1, rows
    assert sum(k == "text" for k, _ in rows) == 1, rows
    assert ("result", "first second") in rows


def test_recovered_run_does_not_reset_request_budget(tmp_path):
    first = subprocess.Popen([sys.executable, str(WORKER), str(tmp_path), "budget-pause"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_for(tmp_path, "before_tool_checkpoint", first)
    finally:
        first.kill()
        first.communicate(timeout=10)
    resumed = subprocess.run([sys.executable, str(WORKER), str(tmp_path), "budget-resume"], capture_output=True, text=True, timeout=20)
    assert resumed.returncode == 0, resumed.stderr
    rows = records(tmp_path)
    assert ("exception", "UsageLimitExceeded") in rows, rows
    assert sum(k == "model_call" for k, _ in rows) == 1, rows
    assert not any(k == "published" for k, _ in rows)
