"""Two REAL adapter processes share a synthetic effect, with final-source fencing."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from driver import ROOT, write_json
from shared import MANIFEST_SHA256, connection, initialize, make_case, snapshot


def run(engine, out):
    out.mkdir(parents=True, exist_ok=False)
    state = out / "state"
    old = make_case("old-owner", hold_before_effect=True, effect_key="shared-effect", parent_id="shared-parent")
    new = make_case("new-owner", fence=2, effect_key="shared-effect", parent_id="shared-parent")
    initialize([old, new], str(state))
    write_json(out / "old.json", [old])
    write_json(out / "new.json", [new])
    def command(which):
        return [sys.executable, str(ROOT / f"{engine}_adapter.py"), "--state-dir", str(state),
                "--requests", str(out / f"{which}.json"), "--output", str(out / f"{which}-records.json"),
                "--concurrency", "1", "--version", "v1"]
    with (out / "old.stdout.txt").open("w") as stdout, (out / "old.stderr.txt").open("w") as stderr:
        old_process = subprocess.Popen(command("old"), stdout=stdout, stderr=stderr)
        marker = state / "old-owner.before-effect"
        deadline = time.monotonic() + 30
        while not marker.exists() and old_process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not marker.exists():
            old_process.kill()
            old_process.wait()
            write_json(out / "summary.json", {"pass": False, "error": "old process did not reach actual before-effect boundary", "pid": old_process.pid})
            return False
        with connection(str(state)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE ownership SET fence=2 WHERE effect_key='shared-effect'")
            conn.commit()
        advance_time = time.time()
        try:
            with (out / "new.stdout.txt").open("w") as new_stdout, (out / "new.stderr.txt").open("w") as new_stderr:
                newer = subprocess.run(command("new"), stdout=new_stdout, stderr=new_stderr, timeout=30)
        finally:
            (state / "old-owner.release-effect").write_text("release")
        try:
            old_code = old_process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            old_process.kill()
            old_code = old_process.wait()
    old_records = json.loads((out / "old-records.json").read_text()) if (out / "old-records.json").exists() else []
    new_records = json.loads((out / "new-records.json").read_text()) if (out / "new-records.json").exists() else []
    observed_old = old_records[0].get("result") if old_records else None
    observed_new = new_records[0].get("result") if new_records else None
    state_snapshot = snapshot(new, str(state))
    with connection(str(state)) as conn:
        events = [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY seq")]
    passed = bool(observed_old and observed_new and observed_old["status"] == "blocked"
                  and observed_old.get("receipt_id") is None and observed_new["status"] == "succeeded"
                  and state_snapshot["effect"]["fence"] == 2 and state_snapshot["receipt"]["fence"] == 2
                  and sum(e["event"] == "source_effect" for e in events) == 1)
    write_json(out / "summary.json", {"pass": passed, "engine": engine, "manifest_sha256": MANIFEST_SHA256,
        "old_pid": old_process.pid, "old_returncode": old_code, "new_returncode": newer.returncode,
        "old_command": command("old"), "new_command": command("new"), "before_effect_marker": json.loads(marker.read_text()),
        "ownership_advanced_at": advance_time, "old_result": observed_old, "new_result": observed_new,
        "source": state_snapshot, "audit": events,
        "scope": "two adapter processes, distinct durable IDs, SAME source effect/parent; not only workflow-ID dedup"})
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=("direct", "dbos", "temporal"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.engine, args.out) else 1)
