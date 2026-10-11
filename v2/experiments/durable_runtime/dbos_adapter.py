"""Actual DBOS 3.2.0 adapter for the isolated TIP-054.4a synthetic bake-off.

The source boundary and all business oracles live in shared.py. DBOS owns only
workflow/step durability. No app dependency or live provider is imported here.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass
import hashlib
import inspect
from importlib.metadata import version
import json
import os
from pathlib import Path
import signal
import shutil
import sqlite3
import subprocess
import sys
import time
from typing import Any

from dbos import DBOS, DBOSClient, DBOSConfig, SetWorkflowID, SetWorkflowTimeout

from shared import (
    MANIFEST_SHA256, connection, execute, initialize, make_case, partial_cases,
    result as source_result, snapshot,
)


PIN = "3.2.0"
WAIT_TOPIC = "tip054-approval"
BUILD = "original"


def original_build_result(result: dict[str, Any]) -> dict[str, Any]:
    return result


def compatible_build_result(result: dict[str, Any]) -> dict[str, Any]:
    # Deliberate compatible code variant: no historical step command changes.
    return {**result, "compatible_build": "v1-metadata-only"}


@DBOS.step(retries_allowed=False)
def source_step(case: dict[str, Any], state_dir: str) -> dict[str, Any]:
    """Unknown effects are reconciled by the source, never blindly retried."""
    return execute(case, state_dir)


@DBOS.step(retries_allowed=False)
def observation_step(case: dict[str, Any], state_dir: str, status: str) -> dict[str, Any]:
    return source_result(case, state_dir, status)


@DBOS.workflow()
def synthetic_workflow(case: dict[str, Any], state_dir: str) -> dict[str, Any]:
    final_case = case
    if case.get("native_partial", False):
        first, final_case = partial_cases(case)
        source_step(first, state_dir)
    if case.get("native_wait", False) or case.get("native_partial", False):
        DBOS.set_event("waiting", {"id": case["id"], "version": case["version"]})
        approval = DBOS.recv(WAIT_TOPIC, timeout_seconds=60)
        if approval != "resume":
            return observation_step(case, state_dir, "partial" if case.get("native_partial") else "blocked")
    # source_step revalidates current source authority AFTER a durable wait.
    result = source_step(final_case, state_dir)
    return compatible_build_result(result) if BUILD == "compatible" else original_build_result(result)


def serializable(value: Any) -> Any:
    if is_dataclass(value):
        return serializable(asdict(value))
    if isinstance(value, dict):
        return {key: serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return serializable(vars(value))
    return value


def workflow_id(case: dict[str, Any], state_dir: str) -> str:
    # One trial's duplicate inputs share an ID; other trials cannot alias it.
    trial = hashlib.sha256(str(Path(state_dir).resolve()).encode()).hexdigest()[:16]
    return f"tip054-{trial}-{case['id']}"


def run_one(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter_ns()
    identity = workflow_id(case, args.state_dir)
    record: dict[str, Any] = {"id": case["id"], "workflow_id": identity}
    try:
        existing = DBOS.get_workflow_status(identity)
        if existing is not None and existing.app_version != args.version:
            # Verify the real runtime persisted version, not a source scenario flag.
            raise RuntimeError(
                f"incompatible_version: recorded={existing.app_version} running={args.version}"
            )
        if args.mode == "inspect":
            record["result"] = None
        elif args.mode == "signal":
            if existing is None:
                raise RuntimeError("cannot signal a nonexistent workflow")
            DBOS.send(identity, "resume", WAIT_TOPIC, idempotency_key="tip054-resume")
            record["result"] = DBOS.retrieve_workflow(identity).get_result()
        elif args.mode == "cancel":
            if existing is None:
                raise RuntimeError("cannot cancel a nonexistent workflow")
            DBOS.cancel_workflow(identity)
            record["result"] = None
        else:
            timeout = case.get("native_timeout_seconds")
            deadline_context = SetWorkflowTimeout(float(timeout)) if timeout is not None else nullcontext()
            with SetWorkflowID(identity), deadline_context:
                handle = DBOS.start_workflow(synthetic_workflow, case, args.state_dir)
            if args.mode == "wait-prepare":
                if not (case.get("native_wait", False) or case.get("native_partial", False)):
                    raise RuntimeError("wait-prepare requires native_wait=true or native_partial=true")
                marker = DBOS.get_event(identity, "waiting", timeout_seconds=15)
                if marker is None:
                    raise TimeoutError("native wait checkpoint was not reached")
                record["result"] = {"waiting": marker}
            else:
                record["result"] = handle.get_result()
    except Exception as exc:
        # No fabricated business state; driver compares errors to source state.
        record["result"] = None
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["elapsed_ms"] = (time.perf_counter_ns() - started) / 1_000_000
    persisted = DBOS.get_workflow_status(identity)
    record["runtime_status"] = serializable(persisted)
    record["runtime_steps"] = serializable(DBOS.list_workflow_steps(identity)) if persisted else []
    return record


def native_proofs(args: argparse.Namespace) -> int:
    """Supervise actual child owners; preserve attempts, not only assertions.

    This supplements the shared suite and never certifies full engine backup,
    HA, arbitrary code upgrades, or distinct company input/schema/ACL systems.
    """
    root = Path(args.state_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    proofs = []
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (Path(__file__), Path(__file__).with_name("shared.py"))}
    for name in ("compatible_wait_restart", "approval_drift", "input_drift", "schema_drift", "acl_drift", "version_mismatch",
                 "cancel_before_effect", "cancel_after_partial", "native_timeout"):
        trial = root / name
        trial.mkdir(exist_ok=False)
        state_dir = trial / "state"
        case = make_case("dbos-native-" + name, native_wait=True,
                         native_partial=name == "cancel_after_partial")
        if name == "native_timeout":
            case["native_timeout_seconds"] = 0.3
        initialize([case], str(state_dir))
        requests = trial / "requests.json"
        requests.write_text(json.dumps([case], indent=2) + "\n")
        attempts = []
        base = [sys.executable, str(Path(__file__).resolve()), "--state-dir", str(state_dir),
                "--requests", str(requests), "--concurrency", "1", "--version", "v1"]
        if args.system_database_url:
            base += ["--system-database-url", args.system_database_url]

        def command(mode: str, label: str, extra: list[str] | None = None):
            output = trial / (label + ".json")
            cmd = base + ["--mode", mode, "--output", str(output)] + (extra or [])
            return cmd, output

        def invoke(mode: str, label: str, extra: list[str] | None = None):
            cmd, output = command(mode, label, extra)
            with (trial / (label + ".stdout.txt")).open("w") as stdout, (trial / (label + ".stderr.txt")).open("w") as stderr:
                process = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, start_new_session=True)
                try:
                    code = process.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    code = process.wait()
                    attempts.append({"command": cmd, "pid": process.pid, "returncode": code, "timeout": True})
                    raise TimeoutError(label)
            attempts.append({"command": cmd, "pid": process.pid, "returncode": code, "timeout": False})
            return json.loads(output.read_text())[0]

        proof: dict[str, Any] = {"name": name, "case": case, "attempts": attempts,
                                 "source_state_path": str(state_dir), "before": snapshot(case, str(state_dir))}
        try:
            if name == "native_timeout":
                # A start_workflow future waits for its synchronous recv body;
                # runtime cancellation is cooperative, not thread preemption.
                # Observe the real persistent deadline/state via the SDK client,
                # then deliberately stop the owner AFTER cancellation is proved.
                cmd, output = command("wait-prepare", "prepared")
                with (trial / "prepare.stdout.txt").open("w") as stdout, (trial / "prepare.stderr.txt").open("w") as stderr:
                    owner = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, start_new_session=True)
                    started = time.monotonic()
                    client = DBOSClient(system_database_url=args.system_database_url)
                    try:
                        deadline = started + 15
                        while not output.exists():
                            if owner.poll() is not None or time.monotonic() >= deadline:
                                raise TimeoutError("native timeout wait checkpoint")
                            time.sleep(0.05)
                        time.sleep(0.05)
                        proof["prepared"] = json.loads(output.read_text())[0]
                        handle = client.retrieve_workflow(workflow_id(case, str(state_dir)))
                        while True:
                            status = handle.get_status()
                            if status.status == "CANCELLED":
                                break
                            if time.monotonic() >= deadline:
                                raise TimeoutError("native runtime cancellation metadata")
                            time.sleep(0.05)
                        observed = {"id": case["id"], "result": None,
                                    "runtime_status": serializable(status),
                                    "runtime_steps": serializable(client.list_workflow_steps(status.workflow_id)),
                                    "observation": "actual native deadline/cancellation before supervisor kill",
                                    "observation_elapsed_ms": (time.monotonic() - started) * 1000,
                                    "source_at_cancellation": snapshot(case, str(state_dir)),
                                    "owner_alive_after_native_cancellation": owner.poll() is None,
                                    "native_state_cancellation_ms": status.updated_at - status.created_at,
                                    "configured_recv_timeout_seconds": 60,
                                    "ordinary_caller_prompt_cancellation_certified": False}
                        (trial / "cancelled-metadata.json").write_text(json.dumps(observed, indent=2, default=str) + "\n")
                        assert status.workflow_timeout_ms == 300
                    finally:
                        client.destroy()
                        if owner.poll() is None:
                            os.killpg(owner.pid, signal.SIGKILL)
                        code = owner.wait()
                        attempts.append({"command": cmd, "pid": owner.pid, "returncode": code,
                                         "supervisor_sigkill": True,
                                         "kill_reason": "after persisted native timeout cancellation observation",
                                         "timeout": False})
            else:
                cmd, output = command("wait-prepare", "prepared")
                with (trial / "prepare.stdout.txt").open("w") as stdout, (trial / "prepare.stderr.txt").open("w") as stderr:
                    owner = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, start_new_session=True)
                    deadline = time.monotonic() + 20
                    try:
                        while not output.exists():
                            if owner.poll() is not None or time.monotonic() >= deadline:
                                raise TimeoutError("native wait checkpoint")
                            time.sleep(0.05)
                        time.sleep(0.05)
                        prepared = json.loads(output.read_text())[0]
                    finally:
                        if owner.poll() is None:
                            os.killpg(owner.pid, signal.SIGKILL)
                        code = owner.wait()
                        attempts.append({"command": cmd, "pid": owner.pid, "returncode": code,
                                         "supervisor_sigkill": True, "timeout": False})
                proof["prepared"] = prepared
                proof["before"] = snapshot(case, str(state_dir))
                if name.endswith("_drift"):
                    field, value = {"approval_drift": ("approval_revision", 2),
                                    "input_drift": ("input_digest", "synthetic-input-v2"),
                                    "schema_drift": ("schema_digest", "synthetic-schema-v2"),
                                    "acl_drift": ("allowed", 0)}[name]
                    with connection(str(state_dir)) as conn:
                        conn.execute(f"UPDATE requests SET {field}=? WHERE id=?", (value, case["id"]))
                        conn.commit()
                    proof["source_mutation"] = {"field": field, "value": value,
                                                "at": "after native checkpoint and owner SIGKILL"}
                if name == "version_mismatch":
                    mismatch = invoke("inspect", "mismatch-v2", ["--version", "v2"])
                    proof["mismatch"] = mismatch
                    assert "incompatible_version" in mismatch.get("error", "")
                    assert mismatch["runtime_status"]["status"] == "PENDING"
                    assert snapshot(case, str(state_dir))["effect"] is None
                    observed = invoke("signal", "recovered-v1")
                elif name.startswith("cancel_"):
                    observed = invoke("cancel", "cancelled")
                else:
                    observed = invoke("signal", "resumed", ["--build", "compatible"] if name == "compatible_wait_restart" else None)
            proof["observed"] = observed
            proof["after"] = snapshot(case, str(state_dir))
            if name == "cancel_after_partial":
                first, second = partial_cases(case)
                proof["first"] = snapshot(first, str(state_dir))
                proof["second"] = snapshot(second, str(state_dir))
                assert observed["runtime_status"]["status"] == "CANCELLED"
                assert proof["first"]["effect"] and proof["first"]["receipt"]
                assert proof["second"]["effect"] is None and proof["second"]["receipt"] is None
                assert proof["first"]["spent"] == 1
            elif name in ("native_timeout", "cancel_before_effect"):
                assert observed["runtime_status"]["status"] == "CANCELLED"
                assert proof["after"]["effect"] is None and proof["after"]["receipt"] is None
                assert proof["after"]["spent"] == 0
            elif name.endswith("_drift"):
                assert observed["result"]["status"] == "blocked"
                assert proof["after"]["effect"] is None and proof["after"]["spent"] == 0
            else:
                assert observed["result"]["status"] == "succeeded"
                assert observed["runtime_status"]["app_version"] == "v1"
                assert proof["after"]["effect"] and proof["after"]["receipt"]
                assert proof["after"]["spent"] == 1
                if name == "compatible_wait_restart":
                    assert observed["result"]["compatible_build"] == "v1-metadata-only"
                    assert proof["prepared"]["implementation_sha256"] != observed["implementation_sha256"]
            proof["pass"] = True
        except Exception as exc:
            proof["pass"] = False
            proof["error"] = f"{type(exc).__name__}: {exc}"
        (trial / "proof.json").write_text(json.dumps(proof, indent=2, default=str) + "\n")
        if args.evidence_dir:
            retained = Path(args.evidence_dir) / name
            retained.mkdir(parents=True, exist_ok=False)
            for artifact in trial.iterdir():
                if artifact.is_file():
                    shutil.copy2(artifact, retained / artifact.name)
            (retained / "state").mkdir()
            with connection(str(state_dir)) as source, sqlite3.connect(retained / "state" / "source.sqlite") as dest:
                source.backup(dest)
        proofs.append(proof)
    summary = {"runtime": "dbos", "sdk_version": version("dbos"), "python": sys.version,
               "manifest_sha256": MANIFEST_SHA256, "source_sha256": hashes,
               "proofs": proofs, "pass": all(proof["pass"] for proof in proofs),
               "limitations": ["single stable executor local restart", "controlled metadata-only compatible code variant, not arbitrary upgrades",
                               "distinct synthetic approval/input/schema/ACL guards, not enterprise integrations",
                               "backup_restore_not_certified_by_this_suite"]}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({"pass": summary["pass"], "proofs": [{"name": p["name"], "pass": p["pass"], "error": p.get("error")} for p in proofs]}))
    return int(not summary["pass"])


def main() -> int:
    global BUILD
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--build", choices=["original", "compatible"], default="original")
    parser.add_argument("--system-database-url", default=os.environ.get("DBOS_SYSTEM_DATABASE_URL"))
    parser.add_argument("--executor-id")
    parser.add_argument("--evidence-dir")
    parser.add_argument("--mode", choices=["run", "wait-prepare", "signal", "inspect", "cancel", "native-proofs"], default="run")
    args = parser.parse_args()
    BUILD = args.build
    if version("dbos") != PIN:
        parser.error(f"exact dbos=={PIN} required; found {version('dbos')}")
    if args.concurrency < 1:
        parser.error("--concurrency must be positive")
    if args.mode == "native-proofs":
        return native_proofs(args)
    state_dir = Path(args.state_dir).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    requests = json.loads(Path(args.requests).read_text())
    if not isinstance(requests, list):
        parser.error("--requests must contain a JSON list")
    trial = hashlib.sha256(str(state_dir).encode()).hexdigest()[:16]
    config: DBOSConfig = {
        "name": "tip054-bakeoff",
        "application_version": args.version,
        "executor_id": args.executor_id or f"tip054-dbos-{trial}",
        "system_database_url": args.system_database_url or f"sqlite:///{state_dir / 'dbos-system.sqlite'}",
        "log_level": "WARNING",
    }
    startup = time.perf_counter_ns()
    DBOS(config=config)
    DBOS.launch()
    startup_ms = (time.perf_counter_ns() - startup) / 1_000_000
    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            records = list(executor.map(lambda case: run_one(case, args), requests))
        for record in records:
            record["runtime"] = "dbos"
            record["sdk_version"] = PIN
            record["build"] = BUILD
            variant = compatible_build_result if BUILD == "compatible" else original_build_result
            record["implementation_sha256"] = hashlib.sha256(inspect.getsource(variant).encode()).hexdigest()
            record["startup_ms"] = startup_ms
            record["storage_profile"] = "postgresql" if config["system_database_url"].startswith("postgres") else "sqlite"
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(records, indent=2, default=str) + "\n")
        if args.mode == "wait-prepare":
            # Keep the actual owner alive until the supervisor SIGKILLs it.
            # Normal graceful exit would not prove crash recovery.
            while True:
                time.sleep(1)
        return int(any("error" in record for record in records))
    finally:
        DBOS.destroy(workflow_completion_timeout_sec=5)


if __name__ == "__main__":
    raise SystemExit(main())
