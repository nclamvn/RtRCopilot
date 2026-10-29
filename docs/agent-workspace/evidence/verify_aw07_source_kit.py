"""Small allowlisted source-kit extraction/build/start proof, no project copy.

Explicitly reuses this host's already installed Python/Node dependencies. This
does not prove a fresh-machine install, offline binary or real AI acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "v2/apps/workspace"
MODULES = ROOT / "v2/apps/workspace-web/node_modules"


def main():
    assert shutil.disk_usage(ROOT).free >= 10 * 1024 ** 3
    started = time.perf_counter()
    environment = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
    environment.update(PYTHONNOUSERSITE="1", PYDANTIC_AI_NO_BANNER="1", NEXT_TELEMETRY_DISABLED="1")
    with tempfile.TemporaryDirectory(prefix=".aw07-root-kit-", dir=APP) as scratch:
        scratch = Path(scratch)
        archive = scratch / "pilot.zip"
        kit = scratch / "extracted"
        original_env = environment | {"PYTHONPATH": str(APP / "src")}

        def cli(env, *arguments):
            result = subprocess.run([sys.executable, "-m", "agent_workspace.cli", *map(str, arguments)], env=env, cwd=kit if kit.exists() else APP, text=True, capture_output=True, timeout=30)
            assert result.returncode == 0, (arguments, result.stdout[-1000:], result.stderr[-1000:])
            return json.loads(result.stdout)

        created = cli(original_env, "source-kit", "--output", archive)
        assert created["integrity_only"] and not created["self_contained"]
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive_bytes = archive.stat().st_size
        with zipfile.ZipFile(archive) as zipped:
            names = zipped.namelist()
            assert not any(part in name.split("/") for name in names for part in (".env", ".git", ".venv", "node_modules", ".workspace-data", ".next-build", "tests"))
            assert not any(name.endswith((".sqlite", ".log", ".pem")) for name in names)
            assert "v2/apps/workspace/src/agent_workspace/simulation_model.py" in names
            assert "v2/apps/workspace/src/agent_workspace/assets/research_fixtures.json" in names
            guide = zipped.read("v2/apps/workspace/LOCAL_PILOT.md")
            assert zipped.read("v2/apps/workspace/README.md") == guide
            assert b"/Users/" not in guide and b"RtR" not in guide
            kit.mkdir()
            zipped.extractall(kit)  # Only after the bounded exact-path verifier.
        web = kit / "v2/apps/workspace-web"
        (web / "node_modules").symlink_to(MODULES, target_is_directory=True)
        # Shared neutral UI is intentionally outside the frontend directory.
        # Its TypeScript imports need the same explicit trusted dependency binding.
        (kit / "v2/node_modules").symlink_to(MODULES, target_is_directory=True)
        env = environment | {"PYTHONPATH": str(kit / "v2/apps/workspace/src")}
        import_probe = subprocess.run([sys.executable, "-c", "import agent_workspace;print(agent_workspace.__file__)"], env=env, cwd=kit, capture_output=True, text=True, timeout=10)
        assert import_probe.returncode == 0 and str(kit) in import_probe.stdout
        # A nonsemantic comment makes the extracted Python fingerprint distinct
        # from the editable checkout. Detect an accidental child-process import
        # from the old venv's editable installation, not just a correct CLI import.
        sentinel = kit / "v2/apps/workspace/src/agent_workspace/__init__.py"
        sentinel.write_bytes(sentinel.read_bytes() + b"\n# AW07 synthetic extracted-source provenance sentinel.\n")
        def source_id(folder):
            digest = hashlib.sha256()
            for path in sorted(folder.glob("*.py")):
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
            return "python-source-" + digest.hexdigest()[:20]
        expected_source = source_id(sentinel.parent)
        assert expected_source != source_id(APP / "src/agent_workspace")
        build_env = env | {"WORKSPACE_PRODUCTION_BUILD": "1"}
        build = subprocess.run(["node", str(MODULES / "next/dist/bin/next"), "build", "--webpack"], cwd=web, env=build_env, capture_output=True, text=True, timeout=180)
        assert build.returncode == 0, (build.stdout[-3000:], build.stderr[-3000:])
        build_id = (web / ".next-build/BUILD_ID").read_text().strip()
        preflight = cli(env, "preflight", "--data-dir", kit / "local-data", "--web-dir", web, "--node-modules", MODULES, "--api-port", 8140, "--web-port", 3140)
        assert preflight["status"] == "ready" and not preflight["network_tested"]
        log = (scratch / "launcher.log").open("wb")
        launch_args = [sys.executable, "-m", "agent_workspace.cli", "launch", "--simulation", "--production", "--data-dir", str(kit / "local-data"), "--web-dir", str(web), "--node-modules", str(MODULES), "--api-port", "8140", "--web-port", "3140"]
        child = subprocess.Popen(launch_args, cwd=kit, env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url="http://127.0.0.1:3140", headers={"origin": "http://127.0.0.1:3140"}, timeout=5) as client:
                for _ in range(150):
                    assert child.poll() is None, "Extracted-kit launcher stopped early"
                    try:
                        response = client.post("/api/workspace/session", json={})
                        if response.is_success:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.05)
                else:
                    raise AssertionError("Extracted-kit startup timeout")
                status = client.get("/api/workspace/status").json()
                assert status["available"] and status["test_mode"]
                assert client.get("/api/workspace/diagnostics").json()["application"]["build_id"] == expected_source
                page = client.get("/workspace")
                assert page.is_success and "Agent Workspace" in page.text
                wid = client.post("/api/workspace/workspaces", json={"name": "Synthetic standalone kit proof"}).json()["id"]
                run = client.post("/api/workspace/runs", json={"workspace_id": wid, "message": "fixture:research", "client_request_id": "kit-local-script-001"}).json()["run_id"]
                for _ in range(250):
                    state = client.get("/api/workspace/runs/" + run).json()["state"]
                    if state == "completed":
                        break
                    assert state not in {"failed", "cancelled"}, state
                    time.sleep(.03)
                assert state == "completed"
                outputs = client.get(f"/api/workspace/workspaces/{wid}/artifacts").json()["items"]
                assert outputs
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            log.close()
        # Prove the launcher's subprocess groups released both owned ports.
        for port in (8140, 3140):
            import socket
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
        result = dict(status="PASS", provenance="Contractor neutral allowlisted kit, exact hash verification, actual Next build and Python/Next processes from extracted source", archive=dict(sha256=archive_digest, bytes=archive_bytes, members=len(names)), frontend_build_id=build_id, preflight=preflight, checks=["Archive excludes private data, tests, dependency trees and build output", "Python CLI and actual API import extracted source, proved with a nonsemantic extracted-only sentinel fingerprint", "Neutral frontend compiles using declared existing same-host dependencies", "Packaged scripted model and packaged research fixtures produce an artifact through the actual BFF", "Ctrl-C launcher cleanup releases both owned loopback ports"], external_calls=0, real_ai_acceptance="NOT_MEASURED", limitations=["Existing trusted Python environment and Node dependency trees explicitly reused", "One synthetic comment added after archive integrity verification only to prove API source provenance", "Not a fresh-machine install, signed distributor, self-contained binary or real AI evaluation"], elapsed_seconds=round(time.perf_counter() - started, 3), extracted_build_removed=True, scratch_removed=True)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
