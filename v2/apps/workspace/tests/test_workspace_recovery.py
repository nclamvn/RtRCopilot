"""Crash the actual product process at its SQL effect/DBOS checkpoint boundary."""
import os
from pathlib import Path
import subprocess
import sys

from agent_workspace.store import Store


def test_product_recovers_receipt_without_duplicate_publication(tmp_path):
    store = Store(tmp_path / "catalogue.sqlite")
    _, owner = store.session(None)
    workspace = store.workspaces(owner, "Crash recovery")["id"]
    store.upload(owner, workspace, "source.txt", "Synthetic budget: 120. Unicode: Việt Nam", "text/plain")
    limits = dict(deadline_seconds=120, request_limit=8, tool_limit=16, token_limit=32000, output_bytes_limit=256000)
    run = store.create_run(owner, workspace, "fixture:create", "recovery-key", limits)
    command = [sys.executable, "tests/runtime_process_probe.py", str(tmp_path), owner, run["id"]]
    env = dict(os.environ, PYTHONPATH="src", PYDANTIC_AI_NO_BANNER="1")
    first = subprocess.run(command + ["--crash-after-effect"], env=env, capture_output=True, text=True, timeout=20)
    assert first.returncode == 41, first.stderr[-2000:]
    assert len(store.items(owner, workspace, "artifacts")) == 1
    assert store.run(owner, run["id"])["state"] == "running"
    second = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
    assert second.returncode == 0, second.stderr[-2000:]
    final = store.run(owner, run["id"])
    assert final["state"] == "completed", final
    assert final["deadline_at"] == run["deadline_at"]
    assert final["limits"] == limits
    artifacts = store.items(owner, workspace, "artifacts")
    assert len(artifacts) == 1 and artifacts[0]["version"] == 1
    events = store.events(owner, run["id"], 0)
    assert len([e for e in events if e["type"] == "artifact.published"]) == 1
    assert len(store.items(owner, workspace, "messages")) == 2
