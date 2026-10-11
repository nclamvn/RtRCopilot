"""Cold joint backup/restore of an owned synthetic dev server and waiting source."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    state = Path(sys.argv[1])
    requests = Path(sys.argv[2])
    out = Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=False)
    engine = Path("/bakeoff/temporal.sqlite")
    pids = []
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit():
            try:
                args = (proc / "cmdline").read_bytes().split(b"\0")
                if args[:3] == [b"/bakeoff/bin/temporal", b"server", b"start-dev"]:
                    pids.append(int(proc.name))
            except OSError:
                pass
    if len(pids) != 1:
        raise RuntimeError(f"expected one owned real server, got {pids}")
    pid = pids[0]
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while Path(f"/proc/{pid}").exists():
        try:
            status = Path(f"/proc/{pid}/status").read_text()
            if "State:\tZ" in status:
                break
        except OSError:
            break
        if time.monotonic() > deadline:
            raise TimeoutError("owned server did not stop before cold backup")
        time.sleep(0.05)
    backup = Path("/bakeoff/backup-temporal-r3")
    backup.mkdir(exist_ok=False)
    with sqlite3.connect(engine) as src, sqlite3.connect(backup / "engine.sqlite") as dst:
        src.backup(dst)
    with sqlite3.connect(state / "source.sqlite") as src, sqlite3.connect(backup / "source.sqlite") as dst:
        src.backup(dst)
    hashes = {p.name: sha(p) for p in backup.iterdir()}
    # Restore ONLY these validated owned tmpfs database files; no app state.
    for path in (engine, Path(str(engine) + "-wal"), Path(str(engine) + "-shm"),
                 state / "source.sqlite", state / "source.sqlite-wal", state / "source.sqlite-shm"):
        if path.exists():
            path.unlink()
    shutil.copyfile(backup / "engine.sqlite", engine)
    shutil.copyfile(backup / "source.sqlite", state / "source.sqlite")
    restored = {"engine.sqlite": sha(engine), "source.sqlite": sha(state / "source.sqlite")}
    if hashes != restored:
        raise RuntimeError("joint restored bytes do not match cold backup")
    command = ["/bakeoff/bin/temporal", "server", "start-dev", "--ip", "127.0.0.1", "--port", "7233", "--headless", "--db-filename", str(engine)]
    log = (out / "server-after-restore.log").open("w")
    server = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 40
    while True:
        ready = subprocess.run(["/bakeoff/bin/temporal", "operator", "cluster", "health"], capture_output=True, timeout=5)
        if ready.returncode == 0:
            break
        if server.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("restored real server not healthy")
        time.sleep(0.1)
    resume = [sys.executable, "/work/temporal_adapter.py", "--mode", "resume", "--state-dir", str(state),
              "--requests", str(requests), "--output", str(out / "resume.json"), "--concurrency", "1", "--version", "v1"]
    with (out / "resume.stdout").open("w") as stdout, (out / "resume.stderr").open("w") as stderr:
        worker = subprocess.run(resume, stdout=stdout, stderr=stderr, timeout=60)
    records = json.loads((out / "resume.json").read_text())
    case = json.loads(requests.read_text())[0]
    from shared import snapshot
    observed = snapshot(case, str(state))
    passed = worker.returncode == 0 and records[0].get("result", {}).get("status") == "succeeded" and observed["effect"] is not None and observed["receipt"] is not None and observed["spent"] == 1
    summary = {"pass": passed, "cold_server_pid": pid, "new_server_pid": server.pid,
        "backup_sha256": hashes, "restored_sha256": restored, "source": observed,
        "resume_returncode": worker.returncode, "resume_command": resume,
        "scope": "one finite actual CLI SQLite dev-server/source cold joint backup+restore at identical paths, not live-safe/production restore certification"}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
