"""Real Temporal SDK adapter for the isolated synthetic bake-off.

Requires an actual, separately managed Temporal CLI dev server. No test server,
emulator, live provider, or serving-application import is used here.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hashlib
import importlib.metadata
import inspect
import json
import os
import platform
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowFailureError, WorkflowHistory
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import CancelledError as TemporalCancelledError
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Replayer, Worker

SDK_PIN = "1.34.0"
WORKFLOW_NAME = "TIP054SyntheticSourceV1"
ACTIVITY_NAME = "TIP054SharedSourceExecuteV1"


async def source_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Same deterministic command and finite policy in both implementations."""
    return await workflow.execute_activity(
        ACTIVITY_NAME, payload,
        start_to_close_timeout=timedelta(seconds=5),
        schedule_to_close_timeout=timedelta(seconds=30),
        retry_policy=RetryPolicy(
            initial_interval=timedelta(milliseconds=100),
            maximum_interval=timedelta(milliseconds=100),
            backoff_coefficient=1, maximum_attempts=3,
        ),
    )


async def native_wait(released: Any, payload: dict[str, Any]) -> None:
    timeout_seconds = payload["case"].get("native_timeout_seconds")
    if timeout_seconds is None:
        await workflow.wait_condition(released)
    else:
        if timeout_seconds <= 0:
            raise ValueError("native timeout must be positive")
        await workflow.wait_condition(released, timeout=timedelta(seconds=timeout_seconds))


@activity.defn(name=ACTIVITY_NAME)
def execute_source(payload: dict[str, Any]) -> dict[str, Any]:
    # Activity, not replaying Workflow code, is the only boundary to source state.
    from shared import execute

    return execute(payload["case"], payload["state_dir"])


@workflow.defn(name=WORKFLOW_NAME)
class DurableSourceWork:
    def __init__(self) -> None:
        self.released = False
        self.phase = "queued"
        self.first_result: dict[str, Any] | None = None

    @workflow.signal
    def resume(self) -> None:
        self.released = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"phase": self.phase, "released": self.released,
                "first_result": self.first_result}

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        partial = payload.get("partial_cases")
        if partial:
            self.phase = "executing_first_effect"
            self.first_result = await source_command({**payload, "case": partial[0]})
        if partial or payload.get("wait_for_signal", False) or payload["case"].get("native_wait", False):
            self.phase = "awaiting_signal"
            # Native signal is persisted in actual server history. Source rights
            # are deliberately NOT captured as Workflow authorization.
            try:
                await native_wait(lambda: self.released, payload)
            except asyncio.TimeoutError:
                self.phase = "timed_out"
                return {"status": "partial" if self.first_result else "failed",
                        "effect_key": payload["case"]["effect_key"],
                        "receipt_id": None, "spent": self.first_result["spent"] if self.first_result else 0,
                        "native_timeout": True, "completed": self.first_result}
        self.phase = "executing_source"
        result = await source_command({**payload, "case": partial[1]} if partial else payload)
        self.phase = "finished"
        return result


@workflow.defn(name=WORKFLOW_NAME)
class CompatibleSourceWork:
    """Finite code-change fixture: same old commands, new outcome metadata."""

    def __init__(self) -> None:
        self.released = False
        self.phase = "queued"
        self.first_result: dict[str, Any] | None = None

    @workflow.signal
    def resume(self) -> None:
        self.released = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"phase": self.phase, "released": self.released,
                "first_result": self.first_result,
                "implementation": "v1-compatible"}

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        partial = payload.get("partial_cases")
        if partial:
            self.phase = "executing_first_effect"
            self.first_result = await source_command({**payload, "case": partial[0]})
        if partial or payload.get("wait_for_signal", False) or payload["case"].get("native_wait", False):
            self.phase = "awaiting_signal"
            try:
                await native_wait(lambda: self.released, payload)
            except asyncio.TimeoutError:
                self.phase = "timed_out"
                return {"status": "partial" if self.first_result else "failed",
                        "effect_key": payload["case"]["effect_key"],
                        "receipt_id": None, "spent": self.first_result["spent"] if self.first_result else 0,
                        "native_timeout": True, "completed": self.first_result,
                        "implementation": "v1-compatible"}
        self.phase = "executing_source"
        result = await source_command({**payload, "case": partial[1]} if partial else payload)
        self.phase = "finished"
        return {**result, "implementation": "v1-compatible"}


@workflow.defn(name=WORKFLOW_NAME)
class IncompatibleSourceWork:
    """Negative replay fixture: changed first command must not pass replay."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        await workflow.sleep(1)
        return await workflow.execute_activity(
            "TIP054DeliberatelyIncompatibleActivity",
            payload,
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


def identity(state_dir: str, case_id: str) -> tuple[str, str]:
    scope = hashlib.sha256(str(Path(state_dir).resolve()).encode()).hexdigest()[:16]
    return f"tip054-temporal-{scope}-{case_id}", f"tip054-temporal-{scope}"


def validate_runtime() -> None:
    if platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("Bake-off requires actual Python 3.12")
    installed = importlib.metadata.version("temporalio")
    if installed != SDK_PIN:
        raise RuntimeError(f"temporalio {installed} is not frozen pin {SDK_PIN}")


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    validate_runtime()
    cases = json.loads(Path(args.requests).read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError("requests must be a nonempty frozen case list")
    state_dir = str(Path(args.state_dir).resolve())
    _, queue = identity(state_dir, cases[0]["id"])
    startup = time.perf_counter()
    client = await Client.connect(args.temporal_address, namespace=args.namespace)
    semaphore = asyncio.Semaphore(args.concurrency)

    async def one(case: dict[str, Any]) -> dict[str, Any]:
        workflow_id, _ = identity(state_dir, case["id"])
        queued = time.perf_counter()
        record: dict[str, Any] = {"id": case["id"]}
        async with semaphore:
            began = time.perf_counter()
            try:
                handle = client.get_workflow_handle(workflow_id)
                if args.mode in {"run", "submit", "wait-prepare"}:
                    payload = {"case": case, "state_dir": state_dir,
                               "wait_for_signal": args.wait_for_signal}
                    if case.get("native_partial", False):
                        from shared import partial_cases

                        payload["partial_cases"] = partial_cases(case)
                    try:
                        handle = await client.start_workflow(
                            WORKFLOW_NAME, payload, id=workflow_id,
                            task_queue=queue,
                            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                            execution_timeout=timedelta(seconds=180),
                            task_timeout=timedelta(seconds=10),
                        )
                    except WorkflowAlreadyStartedError:
                        # Reattach even to a completed durable ID, never resubmit
                        # source work under a fresh identity on command retry.
                        record["attached_existing"] = True
                if args.mode == "resume":
                    await handle.signal("resume")
                    record["result"] = await asyncio.wait_for(handle.result(), args.result_timeout)
                elif args.mode == "cancel":
                    await handle.cancel()
                    try:
                        record["result"] = await asyncio.wait_for(handle.result(), args.result_timeout)
                        record["error"] = "CancellationDidNotStop: workflow already completed"
                    except WorkflowFailureError as exc:
                        if not isinstance(exc.cause, TemporalCancelledError):
                            raise
                        record["result"] = {"status": "engine_cancelled", "effect_key": case["effect_key"]}
                        record["runtime_status"] = (await handle.describe()).status.name
                elif args.mode == "query":
                    record["result"] = await handle.query("state")
                elif args.mode in {"history", "replay", "replay-compatible", "replay-incompatible"}:
                    history = await handle.fetch_history()
                    history_json = history.to_json()
                    record["history_sha256"] = hashlib.sha256(history_json.encode()).hexdigest()
                    if args.mode == "history":
                        record["result"] = {"workflow_id": workflow_id,
                                            "history_json": history_json}
                    else:
                        cls = {"replay": DurableSourceWork,
                               "replay-compatible": CompatibleSourceWork,
                               "replay-incompatible": IncompatibleSourceWork}[args.mode]
                        record["implementation_sha256"] = hashlib.sha256(inspect.getsource(cls).encode()).hexdigest()
                        record["adapter_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                        replay = await Replayer(workflows=[cls]).replay_workflow(
                            WorkflowHistory.from_json(workflow_id, history_json),
                            raise_on_replay_failure=False,
                        )
                        record["result"] = {
                            "replay_passed": replay.replay_failure is None,
                            "failure": str(replay.replay_failure) if replay.replay_failure else None,
                        }
                elif args.mode == "submit":
                    record["result"] = {"status": "submitted", "effect_key": case["effect_key"]}
                elif args.mode == "wait-prepare":
                    if not (args.wait_for_signal or case.get("native_wait", False) or case.get("native_partial", False)):
                        raise ValueError("wait-prepare requires native wait input")
                    async def reach_wait() -> dict[str, Any]:
                        while True:
                            state = await handle.query("state")
                            if state["phase"] == "awaiting_signal":
                                return state
                            await asyncio.sleep(0.05)
                    record["result"] = {"waiting": await asyncio.wait_for(reach_wait(), 15)}
                else:
                    # Never synthesize effect-success from engine submission.
                    record["result"] = await asyncio.wait_for(handle.result(), args.result_timeout)
            except Exception as exc:
                record["result"] = None
                record["error"] = f"{type(exc).__name__}: {exc}"
            record["elapsed_ms"] = (time.perf_counter() - began) * 1000
            record["queued_elapsed_ms"] = (time.perf_counter() - queued) * 1000
            record["runtime"] = "temporal"
            record["sdk_version"] = SDK_PIN
            record["storage_profile"] = "cli_dev_server_sqlite"
            record["workflow_id"] = workflow_id
            return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        if args.mode in {"run", "worker", "wait-prepare", "resume", "cancel"}:
            worker = Worker(
                client, task_queue=queue,
                workflows=[CompatibleSourceWork if args.version == "v1-compatible" else DurableSourceWork],
                activities=[execute_source], activity_executor=executor,
                max_concurrent_activities=args.concurrency,
                max_concurrent_workflow_tasks=max(2, args.concurrency),
                identity=f"tip054-{args.version}",
            )
            async with worker:
                startup_ms = (time.perf_counter() - startup) * 1000
                if args.mode == "worker":
                    await asyncio.Event().wait()
                    return []
                records = await asyncio.gather(*(one(case) for case in cases))
                for record in records:
                    record["startup_ms"] = startup_ms
                if args.mode == "wait-prepare":
                    output = Path(args.output)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
                    # Supervisor must actually kill this Worker process; a
                    # graceful exit is not presented as crash recovery.
                    await asyncio.Event().wait()
                return records
        return await asyncio.gather(*(one(case) for case in cases))


def native_proofs(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Reproducible supervisor; all files/processes belong to this fixture run."""
    from shared import MANIFEST_SHA256, connection, initialize, make_case, partial_cases, snapshot

    validate_runtime()
    root = Path(args.state_dir)
    root.mkdir(parents=True, exist_ok=False)
    proofs: list[dict[str, Any]] = []

    def write(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def record(proof: dict[str, Any]) -> None:
        proofs.append(proof)
        write(root / "proofs.json", {
            "manifest_sha256": MANIFEST_SHA256,
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "sdk_version": SDK_PIN, "python": sys.version, "proofs": proofs,
            "status": "in_progress",
        })

    def state_location(directory: Path) -> Path:
        return Path(args.native_runtime_root) / root.name / directory.name / "state"

    def source_evidence(case: dict[str, Any], directory: Path) -> dict[str, Any]:
        state_dir = str(state_location(directory))
        observed = snapshot(case, state_dir)
        with connection(state_dir) as conn:
            observed["current_guard"] = dict(conn.execute("SELECT * FROM requests WHERE id=?", (case["id"],)).fetchone())
            observed["counts"] = {
                "effects_for_key": conn.execute("SELECT COUNT(*) FROM effects WHERE effect_key=?", (case["effect_key"],)).fetchone()[0],
                "receipts_for_key": conn.execute("SELECT COUNT(*) FROM receipts WHERE effect_key=?", (case["effect_key"],)).fetchone()[0],
                "source_effect_events_for_id": conn.execute("SELECT COUNT(*) FROM audit WHERE id=? AND event='source_effect'", (case["id"],)).fetchone()[0],
                "priced_calls_for_parent": conn.execute("SELECT COUNT(*) FROM calls WHERE parent_id=?", (case["parent_id"],)).fetchone()[0],
            }
            # Child worker has exited/killed before this helper. SQLite backup
            # retains a coherent quiescent source snapshot without host live DB.
            backup_dir = directory / "state"
            backup_dir.mkdir(exist_ok=True)
            target = sqlite3.connect(str(backup_dir / "source.sqlite"))
            try:
                conn.backup(target)
            finally:
                target.close()
        observed["live_state_dir"] = state_dir
        return observed

    write(root / "provenance.json", {
        "manifest_sha256": MANIFEST_SHA256, "python": sys.version,
        "sdk_version": SDK_PIN,
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in Path(__file__).parent.glob("*.py")},
    })

    def prepare(label: str, **overrides: Any) -> tuple[dict[str, Any], Path]:
        directory = root / label
        directory.mkdir()
        case = make_case("temporal-native-" + label, **overrides)
        write(directory / "requests.json", [case])
        initialize([{**case, "scenario": "success"} if case["scenario"].endswith("_drift") else case],
                   str(state_location(directory)))
        return case, directory

    def command(directory: Path, mode: str, tag: str, version: str = "v1") -> list[str]:
        return [sys.executable, str(Path(__file__).resolve()),
                "--state-dir", str(state_location(directory)),
                "--requests", str(directory / "requests.json"),
                "--output", str(directory / (tag + ".json")),
                "--concurrency", "1", "--version", version,
                "--mode", mode, "--temporal-address", args.temporal_address]

    def invoke(directory: Path, mode: str, tag: str, version: str = "v1") -> list[dict[str, Any]]:
        cmd = command(directory, mode, tag, version)
        began = time.perf_counter()
        timed_out = False
        with (directory / (tag + ".stdout")).open("w") as out, (directory / (tag + ".stderr")).open("w") as err:
            proc = subprocess.Popen(cmd, stdout=out, stderr=err)
            try:
                code = proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                code = proc.wait(timeout=5)
        write(directory / (tag + ".command.json"), {
            "command": cmd, "pid": proc.pid, "returncode": code,
            "supervisor_timeout": timed_out,
            "elapsed_ms": (time.perf_counter() - began) * 1000,
        })
        output = directory / (tag + ".json")
        records = json.loads(output.read_text()) if output.exists() else []
        if code or timed_out or any(r.get("error") for r in records):
            raise RuntimeError(f"native proof command failed: {tag}, exit {code}")
        return records

    def kill_wait(directory: Path) -> None:
        cmd = command(directory, "wait-prepare", "wait")
        began = time.perf_counter()
        with (directory / "wait.stdout").open("w") as out, (directory / "wait.stderr").open("w") as err:
            proc = subprocess.Popen(cmd, stdout=out, stderr=err)
            try:
                deadline = time.monotonic() + 30
                while not (directory / "wait.json").exists():
                    if proc.poll() is not None:
                        raise RuntimeError(f"wait worker exited before checkpoint: {proc.returncode}")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("native wait checkpoint not observed")
                    time.sleep(0.05)
                records = json.loads((directory / "wait.json").read_text())
                if records[0].get("error") or records[0]["result"]["waiting"]["phase"] != "awaiting_signal":
                    raise RuntimeError("native wait state not confirmed")
                os.kill(proc.pid, signal.SIGKILL)
                code = proc.wait(timeout=5)
                write(directory / "wait.command.json", {
                    "command": cmd, "pid": proc.pid, "returncode": code,
                    "fault": "supervisor SIGKILL after actual Workflow query checkpoint",
                    "elapsed_ms": (time.perf_counter() - began) * 1000,
                })
                if code != -signal.SIGKILL:
                    raise RuntimeError("actual kill boundary not observed")
            finally:
                if proc.poll() is None:
                    os.kill(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                if not (directory / "wait.command.json").exists():
                    write(directory / "wait.command.json", {
                        "command": cmd, "pid": proc.pid, "returncode": proc.returncode,
                        "error": "wait checkpoint failed; supervisor killed owned process",
                        "elapsed_ms": (time.perf_counter() - began) * 1000,
                    })

    case, directory = prepare("smoke-replay")
    records = invoke(directory, "run", "run")
    exported = invoke(directory, "history", "history")
    replay = invoke(directory, "replay", "replay")
    compatible = invoke(directory, "replay-compatible", "replay-compatible")
    incompatible = invoke(directory, "replay-incompatible", "replay-incompatible")
    record({"id": "real_history_replay", "pass": (
        records[0]["result"]["status"] == "succeeded"
        and replay[0]["result"]["replay_passed"]
        and compatible[0]["result"]["replay_passed"]
        and not incompatible[0]["result"]["replay_passed"]),
        "source": source_evidence(case, directory),
        "history_sha256": exported[0]["history_sha256"],
        "implementations": [replay[0], compatible[0], incompatible[0]]})

    case, directory = prepare("wait-compatible", native_wait=True)
    kill_wait(directory)
    before = source_evidence(case, directory)
    records = invoke(directory, "resume", "resume-compatible", "v1-compatible")
    exported = invoke(directory, "history", "history")
    record({"id": "wait_sigkill_resume_changed_compatible_code", "pass": (
        before["effect"] is None and before["spent"] == 0
        and records[0]["result"]["status"] == "succeeded"
        and records[0]["result"]["implementation"] == "v1-compatible"),
        "before": before, "after": source_evidence(case, directory),
        "history_sha256": exported[0]["history_sha256"]})

    for label, scenario, mutation in (
            ("wait-approval-drift", "approval_drift", "approval_revision=2"),
            ("wait-input-drift", "input_drift", "input_digest='synthetic-input-v2'"),
            ("wait-schema-drift", "schema_drift", "schema_digest='synthetic-schema-v2'"),
            ("wait-acl-revoked", "acl_drift", "allowed=0"),
            ("wait-version-drift", "success", "version='v2'")):
        case, directory = prepare(label, scenario=scenario, native_wait=True)
        kill_wait(directory)
        before = source_evidence(case, directory)
        with connection(str(state_location(directory))) as conn:
            conn.execute("UPDATE requests SET " + mutation + " WHERE id=?", (case["id"],))
            conn.commit()
        records = invoke(directory, "resume", "resume")
        after = source_evidence(case, directory)
        exported = invoke(directory, "history", "history")
        record({"id": label, "pass": records[0]["result"]["status"] == "blocked" and after["effect"] is None and after["spent"] == 0,
                       "mutation": mutation, "before": before, "after": after,
                       "history_sha256": exported[0]["history_sha256"]})

    case, directory = prepare("partial-cancel", native_partial=True)
    first, second = partial_cases(case)
    kill_wait(directory)
    before = {"first": source_evidence(first, directory),
              "second": source_evidence(second, directory)}
    records = invoke(directory, "cancel", "cancel")
    after = {"first": source_evidence(first, directory),
             "second": source_evidence(second, directory)}
    exported = invoke(directory, "history", "history")
    record({"id": "native_cancel_after_partial_effect", "pass": (
        records[0]["runtime_status"] == "CANCELED"
        and after["first"]["effect"] is not None
        and after["first"]["receipt"] is not None
        and after["second"]["effect"] is None and after["first"]["spent"] == 1),
        "before": before, "after": after,
        "engine_result": records[0], "history_sha256": exported[0]["history_sha256"],
        "limitation": "Native cancellation stops remaining work; committed first effect is not undone."})

    case, directory = prepare("native-timeout", native_wait=True, native_timeout_seconds=0.25)
    records = invoke(directory, "run", "run")
    after = source_evidence(case, directory)
    exported = invoke(directory, "history", "history")
    record({"id": "bounded_native_wait_timeout", "pass": (
        records[0]["result"]["status"] == "failed" and records[0]["result"]["native_timeout"]
        and after["effect"] is None and after["spent"] == 0),
        "after": after, "engine_result": records[0],
        "history_sha256": exported[0]["history_sha256"],
        "limitation": "Durable wait deadline; not external network Activity timeout or compensation proof."})

    # Leave actual persisted pending wait for the shared fixture owner to exercise
    # cold joint server/source backup+restore, then resume under identical paths.
    case, directory = prepare("restore", native_wait=True)
    kill_wait(directory)
    exported = invoke(directory, "history", "history-before-restore")
    record({"id": "joint_backup_restore", "pass": None,
                   "status": "pending_shared_fixture_owner_restore",
                   "case": case, "state_dir": str(state_location(directory)),
                   "source": source_evidence(case, directory),
                   "requests": str(directory / "requests.json"),
                   "history_sha256": exported[0]["history_sha256"]})
    write(root / "proofs.json", {
        "manifest_sha256": MANIFEST_SHA256,
        "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sdk_version": SDK_PIN, "python": sys.version,
        "proofs": proofs,
        "scope": "finite actual CLI SQLite dev server proofs, not production upgrades or restore certification",
    })
    return proofs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--version", default="v1", choices=("v1", "v1-compatible"))
    parser.add_argument("--temporal-address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--result-timeout", type=float, default=60)
    parser.add_argument("--native-runtime-root", default="/bakeoff/native")
    parser.add_argument("--wait-for-signal", action="store_true")
    parser.add_argument("--mode", default="run", choices=(
        "run", "submit", "worker", "wait-prepare", "result", "resume", "cancel", "query",
        "history", "replay", "replay-compatible", "replay-incompatible", "native-proofs",
    ))
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be positive")
    records = native_proofs(args) if args.mode == "native-proofs" else asyncio.run(run(args))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
    if any(record.get("error") for record in records) or (args.mode == "native-proofs" and any(record.get("pass") is False for record in records)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
