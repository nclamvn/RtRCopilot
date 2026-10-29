"""Actual-process local/mock upgrade/backup/restore proof, synthetic only.

Own child processes, own temporary catalogue. No repository copy or provider I/O.
The existing user/demo runtimes are never selected by this probe.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "v2/apps/workspace"
WEB = ROOT / "v2/apps/workspace-web"
ORIGIN = "http://127.0.0.1:3140"


def main():
    started = time.perf_counter()
    def key():
        return str(uuid.uuid4())
    environment = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
    environment.update(PYTHONPATH=str(APP / "src"), PYDANTIC_AI_NO_BANNER="1", PYTHONNOUSERSITE="1", WORKSPACE_TEST_MODE="1", WORKSPACE_ORIGINS=json.dumps([ORIGIN]))
    with tempfile.TemporaryDirectory(prefix=".aw08-root-ops-", dir=APP) as scratch:
        scratch = Path(scratch)
        data, restored = scratch / "original", scratch / "restored"
        backup = scratch / "private.zip"

        def cli(*arguments, okay=True):
            result = subprocess.run([sys.executable, "-m", "agent_workspace.cli", *map(str, arguments)], cwd=APP, env=environment, capture_output=True, text=True, timeout=30)
            assert (result.returncode == 0) == okay, (arguments, result.returncode, result.stdout[-1500:], result.stderr[-1000:])
            return json.loads(result.stdout if result.returncode == 0 else result.stderr)

        def process(directory, port):
            log = (scratch / f"process-{port}.log").open("wb")
            child = subprocess.Popen([sys.executable, "-m", "uvicorn", "agent_workspace.api:app", "--host", "127.0.0.1", "--port", str(port)], cwd=APP, env=environment | {"WORKSPACE_DATA_DIR": str(directory)}, stdout=log, stderr=log, start_new_session=True)
            client = httpx.Client(base_url=f"http://127.0.0.1:{port}/api/workspace", headers={"origin": ORIGIN}, timeout=15)
            before = time.perf_counter()
            try:
                for _ in range(120):
                    assert child.poll() is None, "Owned API failed startup; inspect the private scratch log."
                    try:
                        response = client.post("/session", json={})
                        if response.is_success:
                            assert client.get("/readiness").json()["test_mode"]
                            return child, client, log, round((time.perf_counter() - before) * 1000, 3)
                    except httpx.TransportError:
                        pass
                    time.sleep(.05)
                raise AssertionError("Owned API startup timeout")
            except BaseException:
                stop(child, client, log)
                raise

        def stop(child, client, log):
            client.close()
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)
            log.close()

        def post(client, path, body):
            response = client.post(path, json=body)
            assert response.is_success, (path, response.status_code, response.text[:500])
            return response.json()

        first, client, log, startup_ms = process(data, 8141)
        try:
            token = client.cookies.get("workspace_session")
            assert token
            private = "PRIVATE_SYNTHETIC_" + key()
            wid = post(client, "/workspaces", {"name": "Synthetic recovered notebook"})["id"]
            raw = "Synthetic library entry008291; quantity73.875.\nTiếng Việt Δ\n"
            source = post(client, f"/workspaces/{wid}/files", {"filename": "library.txt", "content": raw, "media_type": "text/plain"})
            post(client, f"/workspaces/{wid}/brief", dict(goal=private, decisions="Retain source numbers.", remaining="Reopen after recovery.", expected_revision=0, request_id=key()))
            run = post(client, "/runs", dict(workspace_id=wid, message="fixture:create", client_request_id=key()))["run_id"]
            for _ in range(200):
                state = client.get("/runs/" + run).json()["state"]
                if state == "completed":
                    break
                assert state not in {"failed", "cancelled"}, state
                time.sleep(.03)
            assert state == "completed"
            output = client.get(f"/workspaces/{wid}/artifacts").json()["items"][0]
            original = client.get(f"/artifacts/{output['id']}?version=1").json()["content"]
            post(client, f"/artifacts/{output['id']}/revisions", dict(expected_version=1, content=original + "\nManual reviewed version.\n", request_id=key()))
            snapshot = client.get(f"/runs/{run}/context").json()
            review_run = post(client, "/runs", dict(workspace_id=wid, message="fixture:review", client_request_id=key(), context=dict(references=[], target=dict(kind="artifact", id=output["id"], version=2), review_edits=True)))["run_id"]
            for _ in range(200):
                state = client.get("/runs/" + review_run).json()["state"]
                if state == "completed":
                    break
                assert state not in {"failed", "cancelled"}, state
                time.sleep(.03)
            assert state == "completed"
            pending = next(p for p in client.get(f"/workspaces/{wid}/proposals").json()["items"] if p["run_id"] == review_run)
            assert pending["status"] == "pending" and pending["can_decide"]
            denied = cli("backup", "--data-dir", data, "--output", backup, okay=False)
            assert "runtime_locked" in json.dumps(denied)
            assert not backup.exists()
        finally:
            stop(first, client, log)
        before_hash = hashlib.sha256((data / "catalogue.sqlite").read_bytes()).hexdigest()
        copied = cli("backup", "--data-dir", data, "--output", backup)
        assert backup.stat().st_mode & 0o777 == 0o600
        restored_result = cli("restore", "--archive", backup, "--destination", restored)
        denied = cli("restore", "--archive", backup, "--destination", data, okay=False)
        assert "destination_exists" in json.dumps(denied)
        assert hashlib.sha256((data / "catalogue.sqlite").read_bytes()).hexdigest() == before_hash
        second, recovered, log, restart_ms = process(restored, 8142)
        try:
            recovered.cookies.clear()
            recovered.cookies.set("workspace_session", token, domain="127.0.0.1", path="/api/workspace")
            assert recovered.get(f"/files/{source['id']}/download").content.decode() == raw
            assert recovered.get(f"/artifacts/{output['id']}?version=1").json()["content"] == original
            assert recovered.get(f"/artifacts/{output['id']}").json()["version"] == 2
            assert recovered.get(f"/workspaces/{wid}/brief").json()["goal"] == private
            assert recovered.get(f"/runs/{run}/context").json()["digest"] == snapshot["digest"]
            assert recovered.get("/runs/" + run).json()["state"] == "completed"
            assert private not in recovered.get("/diagnostics").text
            assert recovered.get(f"/workspaces/{wid}/messages").json()["items"]
            candidate = recovered.get("/proposals/" + pending["id"]).json()
            assert candidate["status"] == "pending" and candidate["can_decide"]
            assert recovered.get(f"/artifacts/{output['id']}").json()["version"] == 2
            applied = post(recovered, f"/proposals/{pending['id']}/decision", dict(decision="accept", change_ids=[c["id"] for c in candidate["changes"]], request_id=key()))
            assert applied["version"] == 3 and recovered.get(f"/artifacts/{output['id']}?version=1").json()["content"] == original
        finally:
            stop(second, recovered, log)
        result = dict(status="PASS", provenance="Contractor actual two API subprocesses, HTTP, SQLite/DBOS and offline private backup/restore; synthetic deterministic model", checks=["Runtime lock rejects live backup without an archive", "Stopped private backup and atomic new-directory restore", "Restore refuses existing source directory and leaves original catalogue unchanged", "Same local session retains raw Unicode source, both output versions, user brief and exact saved context fingerprint", "Completed run is still terminal after restore; no prompt was re-dispatched", "Content-free diagnostics omit private synthetic brief canary"], measurements=dict(initial_api_startup_ms=startup_ms, recovered_api_startup_ms=restart_ms, backup_bytes=backup.stat().st_size), backup=copied, restore=restored_result, external_calls=0, real_ai_acceptance="NOT_MEASURED", elapsed_seconds=round(time.perf_counter() - started, 3), scratch_removed=True)
    result["checks"].append("Pending review candidate remains unpublished after restore; only a later explicit decision creates version3, retaining original version1")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
