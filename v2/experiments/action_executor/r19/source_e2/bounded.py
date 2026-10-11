"""Linux fixture-only child process-group deadline and evidence-cap supervisor."""

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from pathlib import Path

from qualification import CAPS, evidence_cap, require


def process(pid, proc=Path("/proc")):
    try:
        raw = (proc / str(pid) / "stat").read_text()
        fields = raw[raw.rfind(")") + 2 :].split()
        return {"state": fields[0], "group": int(fields[2]), "start": fields[19]}
    except FileNotFoundError:
        return None


def group_members(owner, proc=Path("/proc")):
    members = []
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        state = process(int(entry.name), proc)
        if state is None or state["group"] != owner["group"] or state["state"] == "Z":
            continue
        try:
            environment = (entry / "environ").read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        require(
            f"R19_OWNED_CHILD={owner['token']}".encode() in environment,
            "unknown process in owned group; do not signal arbitrary processes",
        )
        members.append(int(entry.name))
    return members


def signal_owned(owner, signum):
    members = group_members(owner)
    if members:
        with suppress(ProcessLookupError):
            os.killpg(owner["group"], signum)
    return members


def drain(owner, grace=10, *, deadline=None):
    signal_owned(owner, signal.SIGTERM)
    if deadline is None:
        deadline = time.monotonic() + grace
    remaining = max(0, deadline - time.monotonic())
    kill_at = deadline - min(2, remaining / 2)
    while group_members(owner) and time.monotonic() < kill_at:
        time.sleep(0.02)
    if group_members(owner):
        signal_owned(owner, signal.SIGKILL)
    while group_members(owner) and time.monotonic() < deadline:
        time.sleep(0.02)
    require(not group_members(owner), "owned group did not drain; no DB cleanup admission")


def run(root, stage, label, command):
    root = Path(root)
    require(root.as_posix().startswith("/evidence/r19/"), "fixture evidence root")
    require(stage in {"pre", "http"} and label.replace("-", "").isalnum(), "fixed child label")
    require(command and command[0].startswith("/"), "absolute child executable")
    return supervise(root, stage, label, command)


def supervise(root, stage, label, command):
    stopped = []
    previous = {}
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[signum] = signal.signal(signum, lambda number, frame: stopped.append(number))
    token = uuid.uuid4().hex
    environment = dict(os.environ, R19_OWNED_CHILD=token)
    started = time.monotonic()
    reason = "completed"
    with (
        (root / f"{label}.stdout.txt").open("xb") as stdout,
        (root / f"{label}.stderr.txt").open("xb") as stderr,
    ):
        child = subprocess.Popen(
            command, stdout=stdout, stderr=stderr, env=environment, start_new_session=True
        )
        owner = {
            "group": child.pid,
            "token": token,
            "supervisor": os.getpid(),
            "supervisor_start": process(os.getpid())["start"],
        }
        owner_path = root / f"{label}.owner.json"
        owner_path.write_text(json.dumps(owner))
        cleanup_deadline = None

        def cleanup_group():
            nonlocal cleanup_deadline
            if cleanup_deadline is None:
                cleanup_deadline = time.monotonic() + CAPS["kill_grace_seconds"]
            drain(owner, deadline=cleanup_deadline)

        def reap():
            remaining = (
                2 if cleanup_deadline is None else max(0, cleanup_deadline - time.monotonic())
            )
            return child.wait(timeout=remaining)

        try:
            while child.poll() is None:
                if stopped:
                    reason = "interrupted"
                    break
                if time.monotonic() - started >= child_budget(stage, label):
                    reason = "deadline"
                    break
                try:
                    evidence_cap(root, stage)
                except ValueError:
                    reason = "evidence_cap"
                    break
                time.sleep(0.02)
            if reason != "completed" or group_members(owner):
                if reason == "completed" and child.poll() is not None and group_members(owner):
                    reason = "lingering_owned_child"
                cleanup_group()
            original_code = reap()
            try:
                evidence_cap(root, stage)
            except ValueError:
                reason = "evidence_cap"
            code = original_code if reason == "completed" else 124
        finally:
            if group_members(owner):
                cleanup_group()
            reap()
            result = {
                "exit_code": locals().get("code", 125),
                "reason": reason,
                "original_exit_code": child.returncode,
                "group_drained": True,
                "wall_seconds": time.monotonic() - started,
                "owner": owner,
            }
            (root / f"{label}.process.json").write_text(json.dumps(result, indent=2))
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return code


def child_budget(stage, label):
    return CAPS["http_seconds"] if stage == "http" and label == "load" else CAPS["child_seconds"]


def stop(root, label):
    owner_path = Path(root) / f"{label}.owner.json"
    deadline = time.monotonic() + 2
    while not owner_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not owner_path.exists():
        # No ownership yet: never signal guessed PIDs. The harness joins exec
        # before any cleanup, and the normal supervisor budget still applies.
        return
    owner = json.loads(owner_path.read_bytes())
    state = process(owner["supervisor"])
    if state is not None and state["start"] == owner["supervisor_start"]:
        command = (Path("/proc") / str(owner["supervisor"]) / "cmdline").read_bytes()
        require(b"/work/r19/bounded.py\0run\0" in command, "exact supervisor identity")
        os.kill(owner["supervisor"], signal.SIGTERM)
    else:
        drain(owner, CAPS["kill_grace_seconds"])


if __name__ == "__main__":
    action, root, stage_or_label, *arguments = sys.argv[1:]
    if action == "run":
        label, *command = arguments
        sys.exit(run(root, stage_or_label, label, command))
    require(action == "stop", "unknown bounded action")
    stop(root, stage_or_label)
