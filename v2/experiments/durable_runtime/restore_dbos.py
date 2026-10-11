"""Prepare/verify cold synthetic DBOS PG + source restore; PG restore is external."""
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
from shared import initialize, make_case, snapshot

STATE = Path("/bakeoff/native/dbos-restore/state")
OUT = Path("/evidence/dbos-cold-restore")
BACKUP = Path("/bakeoff/backup-dbos-source.sqlite")


def fingerprint():
    import psycopg
    from psycopg import sql
    observed = {}
    with psycopg.connect(os.environ["DBOS_SYSTEM_DATABASE_URL"], connect_timeout=3) as conn:
        for table, in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='dbos' ORDER BY tablename"):
            rows = [row[0] for row in conn.execute(sql.SQL("SELECT row_to_json(t) FROM dbos.{} t").format(sql.Identifier(table)))]
            encoded = sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)
            observed[table] = {"rows": len(rows), "sha256": hashlib.sha256(json.dumps(encoded).encode()).hexdigest()}
    return observed


def command(mode, filename):
    return [sys.executable, "/work/dbos_adapter.py", "--state-dir", str(STATE), "--requests", str(OUT / "requests.json"),
            "--output", str(OUT / filename), "--concurrency", "1", "--version", "v1", "--mode", mode]


def main():
    mode = sys.argv[1]
    if mode == "prepare":
        OUT.mkdir(exist_ok=False)
        case = make_case("dbos-cold-restore", native_wait=True)
        initialize([case], str(STATE))
        (OUT / "requests.json").write_text(json.dumps([case], indent=2))
        with (OUT / "prepare.stdout").open("w") as stdout, (OUT / "prepare.stderr").open("w") as stderr:
            worker = subprocess.Popen(command("wait-prepare", "waiting.json"), stdout=stdout, stderr=stderr)
            deadline = time.monotonic() + 25
            while not (OUT / "waiting.json").exists():
                if worker.poll() is not None or time.monotonic() > deadline:
                    worker.kill()
                    worker.wait()
                    raise RuntimeError("owned restore worker did not reach native wait")
                time.sleep(0.05)
            prepared = json.loads((OUT / "waiting.json").read_text())
            os.kill(worker.pid, signal.SIGKILL)
            code = worker.wait(timeout=5)
        if code != -9 or not prepared[0].get("result", {}).get("waiting"):
            raise RuntimeError("native wait / actual SIGKILL not proved")
        with sqlite3.connect(STATE / "source.sqlite") as src, sqlite3.connect(BACKUP) as dst:
            src.backup(dst)
        data = {"worker_pid": worker.pid, "returncode": code, "command": command("wait-prepare", "waiting.json"),
                "source_before": snapshot(case, str(STATE)), "pg_before": fingerprint(),
                "source_backup_sha256": hashlib.sha256(BACKUP.read_bytes()).hexdigest()}
        (OUT / "prepared.json").write_text(json.dumps(data, indent=2))
        print("native wait prepared and worker SIGKILLed; perform owned PG dump/restore now")
        return 0
    if mode != "resume":
        raise ValueError("mode must be prepare or resume")
    prepared = json.loads((OUT / "prepared.json").read_text())
    after_pg = fingerprint()
    for path in (STATE / "source.sqlite", STATE / "source.sqlite-wal", STATE / "source.sqlite-shm"):
        if path.exists():
            path.unlink()
    shutil.copyfile(BACKUP, STATE / "source.sqlite")
    sha = hashlib.sha256((STATE / "source.sqlite").read_bytes()).hexdigest()
    with (OUT / "resume.stdout").open("w") as stdout, (OUT / "resume.stderr").open("w") as stderr:
        resumed = subprocess.run(command("signal", "resumed.json"), stdout=stdout, stderr=stderr, timeout=30)
    records = json.loads((OUT / "resumed.json").read_text())
    case = json.loads((OUT / "requests.json").read_text())[0]
    final = snapshot(case, str(STATE))
    passed = prepared["pg_before"] == after_pg and prepared["source_backup_sha256"] == sha and resumed.returncode == 0 and records[0].get("result", {}).get("status") == "succeeded" and final["effect"] is not None and final["receipt"] is not None and final["spent"] == 1
    (OUT / "summary.json").write_text(json.dumps({"pass": passed, "prepared": prepared, "pg_after_restore": after_pg,
        "restored_source_sha256": sha, "resume_command": command("signal", "resumed.json"), "resume_returncode": resumed.returncode,
        "source_after": final, "scope": "finite cold label-owned PG logical dump/restore + SQLite source at same paths; not production/live-safe upgrades or role/cluster restore certification"}, indent=2))
    print(json.dumps({"pass": passed, "source_after": final}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
