"""Source-connected launcher preparation. No Docker/SQL/HTTP launch surface."""

from __future__ import annotations

import ast
import hashlib
import json
import shlex
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, cast

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]
R21 = "v2/experiments/action_executor/r21/run-http-qualification.sh"
R19 = "v2/experiments/action_executor/r19/bounded.py"
BASELINE = "v2/experiments/action_executor/r/run_phase_baseline.py"
PROBE = "v2/experiments/action_executor/latency_probe.py"
CONTRACT = ROOT / "v2/experiments/action_executor/r25/contract.json"
CONTRACT_SHA256 = "43e24fdef2e1acfd3f00b409e9fd5a46853c4105d4b3c71f329b93c6f1eccbcc"
FIXTURE = "tip054-4b-full-20261007-r5qa1"
EPOCH = "r27_runtime_http_e1"
DOMAIN = "rtr_tip054_r27_local_e1"
ENGINE = "rtr_tip054_r27_engine_e1"


class CapturePort(Protocol):
    def register(self, relative: str, family: str, *, defer_parents: bool = False) -> Path: ...

    def invalidate(self) -> None: ...

    def record(self, family: str, payload: bytes, physical: int = 0) -> int: ...

    def guard(self, *, context: bool = False) -> None: ...


@dataclass(frozen=True)
class ProducerPin:
    path: str
    sha256: str


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("string-key object required")
    return cast(dict[str, object], value)


def sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("array required")
    return cast(list[object], value)


def text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("string required")
    return value


def producer_pins() -> tuple[ProducerPin, ...]:
    raw = CONTRACT.read_bytes()
    if CONTRACT.is_symlink() or digest(raw) != CONTRACT_SHA256:
        raise ValueError("fixed historical contract source drift, no self-authorized witnesses")
    data = mapping(json.loads(raw))
    pins: dict[str, str] = {}
    for family in sequence(data["families"]):
        for witness in sequence(mapping(family)["witnesses"]):
            row = mapping(witness)
            path, sha = text(row["path"]), text(row["sha256"])
            if path in pins and pins[path] != sha:
                raise ValueError("conflicting source witness")
            pins[path] = sha
    return tuple(ProducerPin(path, sha) for path, sha in sorted(pins.items()))


def source(path: str) -> str:
    pins = {pin.path: pin.sha256 for pin in producer_pins()}
    if path not in pins:
        raise ValueError("unbound producer")
    target = ROOT / path
    if any(parent.is_symlink() for parent in (target, *target.parents)):
        raise ValueError("source symlink")
    raw = target.read_bytes()
    if digest(raw) != pins[path]:
        raise ValueError("producer source drift")
    return raw.decode("utf-8")


@dataclass(frozen=True)
class PreparedCommand:
    label: str
    producer: str
    argv: tuple[str, ...]
    stdout_family: str
    stderr_family: str
    output_records: str
    seconds: int
    effects: str


def commands() -> tuple[PreparedCommand, ...]:
    "Literal argv for original fixture paths, not executable dispatch functions."
    shell = source(R21)
    required = (
        "exec_runner /app/.venv/bin/python /work/r19/bounded.py run",
        "checked load /usr/bin/env",
        "run_phase_baseline.py",
        "upgrade 0019_action_executor",
        "pg_sql -U rtr_tip054_local",
        "capacity final",
        "r21-campaign-launch.json",
    )
    if not all(fragment in shell for fragment in required):
        raise ValueError("actual original launcher preparation seam changed")
    evidence = "/evidence/r19/" + EPOCH
    docker = "/usr/local/bin/docker"

    def environment(name: str) -> tuple[str, ...]:
        section = shell.split(name + "=(", 1)[1].split(")\n", 1)[0]
        domain = ("postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/") + DOMAIN
        engine = (
            "postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/"
        ) + ENGINE
        return tuple(
            token.replace("$container_evidence", evidence)
            .replace("${POSTGRES_DSN-}", domain)
            .replace("${INTEGRATION_DATABASE_DSN-}", domain)
            .replace("${ACTION_WORKFLOW_DSN-}", engine)
            for token in shlex.split(section)
        )

    base = (
        docker,
        "exec",
        "-w",
        "/workspace/v2/apps/backend",
        f"{FIXTURE}-runner",
        "env",
        "-i",
        *environment("base_env"),
    )
    return (
        PreparedCommand(
            "load",
            R21,
            base
            + (
                "/app/.venv/bin/python",
                "/work/r19/bounded.py",
                "run",
                evidence,
                "http",
                "load",
                "/usr/bin/env",
                *environment("load_env"),
                "/app/.venv/bin/python",
                "/work/r/run_phase_baseline.py",
                evidence + "/run",
                "off",
            ),
            "summary_stdout",
            "load_stderr",
            "original write calls; whole child stream HOLD",
            190,
            "PREPARED_ONLY: original HTTP/SQL workload, never dispatched",
        ),
        PreparedCommand(
            "migration",
            R21,
            base
            + (
                "/app/.venv/bin/python",
                "/work/r19/bounded.py",
                "run",
                evidence,
                "http",
                "migration",
                "/usr/bin/env",
                (
                    "MIGRATION_DSN=postgresql://rtr_tip054_local:rtr_tip054_synth"
                    "etic_only@tip054-pg:5432/"
                )
                + DOMAIN,
                "/app/.venv/bin/alembic",
                "upgrade",
                "0019_action_executor",
            ),
            "migration_streams",
            "migration_streams",
            "native whole streams HOLD",
            120,
            "PREPARED_ONLY: database migration, never dispatched",
        ),
        PreparedCommand(
            "fixture",
            R21,
            (
                "python3",
                "-B",
                "/work/r21/qualification.py",
                "fixture",
                "/work/r12/preflight_e1/fixture-preflight.json",
                docker,
            ),
            "fixture",
            "fixture",
            "one original stdout/stderr stream each",
            120,
            "PREPARED_ONLY: Docker inspect",
        ),
        PreparedCommand(
            "capacity",
            R21,
            (docker, "exec", f"{FIXTURE}-pg", "df", "-k", "/var/lib/postgresql/data"),
            "disk",
            "disk",
            "one original df output",
            120,
            "PREPARED_ONLY: read-only Docker call, not executed",
        ),
        PreparedCommand(
            "absence",
            R21,
            (
                docker,
                "exec",
                f"{FIXTURE}-pg",
                "env",
                "PGCONNECT_TIMEOUT=5",
                "PGOPTIONS=-c statement_timeout=10000 -c lock_timeout=5000",
                "psql",
                "-X",
                "-U",
                "rtr_tip054_local",
                "-d",
                "postgres",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "SELECT count(*) FROM pg_database WHERE datname='" + DOMAIN + "';",
            ),
            "database_admin",
            "database_admin",
            "one original psql output per call",
            120,
            "PREPARED_ONLY: SQL read, no execution",
        ),
        PreparedCommand(
            "reconstruction",
            R21,
            ("python3", "-B", "/work/r21/qualification.py", "analyze", evidence),
            "reconstruction",
            "reconstruction",
            "one original report/error",
            120,
            "PREPARED_ONLY: original reconstruction CLI not executed",
        ),
    )


def literal_scope() -> bytes:
    rows = [line for line in source(R21).splitlines() if '"$evidence/executor-scope.txt"' in line]
    if len(rows) != 1 or not rows[0].startswith("printf '"):
        raise ValueError("exact original literal scope seam")
    value = rows[0].split("'", 2)[1]
    if "%" in value:
        raise ValueError("unexpected format interpolation")
    return value.replace("\\n", "\n").encode("utf-8")


def literal_controls() -> bytes:
    tree = ast.parse(source(BASELINE))
    writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "write_text"
    ]
    selected = [node for node in writes if "r-controls.json" in ast.unparse(node)]
    if len(selected) != 1:
        raise ValueError("exact original controls writer seam")
    # Evaluate the original pure JSON encoder expression only, not imports/engine/load.
    call = selected[0].value
    if not isinstance(call, ast.Call):
        raise ValueError("original controls write call")
    expression = call.args[0]
    if not isinstance(expression, ast.Call) or ast.unparse(expression.func) != "json.dumps":
        raise ValueError("pure JSON source expression")
    namespace: dict[str, object] = {"json": json, "mode": "off"}
    value: object = eval(
        compile(ast.Expression(expression), BASELINE + "#controls", "eval"), namespace
    )
    return text(value).encode("utf-8")


class RoutedLauncher:
    "A finite source-specific endpoint, not generic twenty-family certification."

    def __init__(self, capture: CapturePort) -> None:
        self.capture = capture
        try:
            self._prepare()
        except BaseException:
            capture.invalidate()
            raise

    def _prepare(self) -> None:
        capture = self.capture
        self.binding = capture.register("launcher/binding.json", "frozen_copies")
        self.contract = capture.register("launcher/contract.json", "frozen_copies")
        self.scope = capture.register("launcher/executor-scope.txt", "literal_scope")
        self.controls = capture.register("launcher/r-controls.json", "literal_controls")
        self.returncodes = capture.register("launcher/returncodes.txt", "returncodes")
        self.review = capture.register("launcher/review-pin.txt", "launch_review")
        self.copy_payloads = tuple(
            (destination, relative, source(relative).encode("utf-8"))
            for destination, relative in (
                (self.binding, "v2/experiments/action_executor/r21/source-binding-e1.json"),
                (self.contract, "v2/experiments/action_executor/r21/contract.json"),
            )
        )
        self.scope_payload, self.controls_payload = literal_scope(), literal_controls()

    def safe_outputs(self) -> dict[str, str]:
        # Call inside Capture hooks: exact original copied bytes, charged before each sidecar write.
        hashes = {}
        try:
            self.capture.guard(context=True)
            for destination, relative, raw in self.copy_payloads:
                destination.write_bytes(raw)
                hashes[relative] = digest(raw)
            self.scope.write_bytes(self.scope_payload)
            self.controls.write_bytes(self.controls_payload)
        except BaseException:
            self.capture.invalidate()
            raise
        return hashes

    def returncode(self, label: str, code: int) -> None:
        if label not in {"load", "migration", "source", "cleanup", "local-control"}:
            self.capture.invalidate()
            raise ValueError("finite original returncode domain")
        if type(code) is not int or not -255 <= code <= 255:
            self.capture.invalidate()
            raise ValueError("finite exit code")
        try:
            self.capture.guard(context=True)
            with self.returncodes.open("ab") as stream:
                stream.write(f"{label} {code}\n".encode("ascii"))
        except BaseException:
            self.capture.invalidate()
            raise

    def review_pin(self, path: str, sha: str) -> None:
        try:
            self.capture.guard(context=True)
            if (
                len(path.encode("utf-8")) > 512
                or "\n" in path
                or len(sha) != 64
                or any(character not in "0123456789abcdef" for character in sha)
            ):
                raise ValueError("finite original review pin")
            self.review.write_bytes(f"{path} {sha}\n".encode())
        except BaseException:
            self.capture.invalidate()
            raise


def original_cleanup_writer() -> Callable[[dict[str, object], Path], float]:
    "Actual R19 begin_cleanup body, full source pin; never invokes signal/drain."
    tree = ast.parse(source(R19))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "begin_cleanup"
    )

    def require(ok: object, message: str) -> None:
        if not ok:
            raise ValueError(message)

    namespace: dict[str, object] = {
        "json": json,
        "time": time,
        "math": __import__("math"),
        "CAPS": {"kill_grace_seconds": 10},
        "require": require,
    }
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), R19 + "#begin_cleanup", "exec"), namespace
    )
    function = namespace["begin_cleanup"]
    if not callable(function):
        raise ValueError("cleanup source function")
    return cast(Callable[[dict[str, object], Path], float], function)


def prepared_manifest() -> dict[str, object]:
    return {
        "schema": "r27-runtime-command-preparation-v1",
        "dispatch_surface": "NONE",
        "source_pins": [asdict(pin) for pin in producer_pins()],
        "commands": [asdict(command) for command in commands()],
        "resource_names": [FIXTURE + suffix for suffix in ("-runner", "-pg", "-redis", "-minio")],
        "databases": [DOMAIN, ENGINE],
        "epoch": EPOCH,
        "future_raw_root": "raw/" + FIXTURE + "/r19/" + EPOCH,
        "marker": (
            "r19/r27-runtime-campaign-launch.json; exclusive fresh marker; unknown launch consumed"
        ),
        "historical_marker": (
            "r19/r21-campaign-launch.json; preserved immutable, never deleted/reused"
        ),
        "identity_substitutions": {
            "r21_http_e1": EPOCH,
            "r21-campaign-launch.json": "r27-runtime-campaign-launch.json",
            "rtr_tip054_r21_local_e1": DOMAIN,
            "rtr_tip054_r21_engine_e1": ENGINE,
        },
        "substitution_status": (
            "PREPARED_ONLY; unchanged original R21 guard would not admit "
            "new names; no new effects qualified"
        ),
        "docker_executable": (
            "/usr/local/bin/docker PREPARED_ONLY resolution/identity unverified by runtime"
        ),
        "load_seconds": 190,
        "shared_cleanup_seconds": 10,
        "whole_record_cap_bytes": 10485760,
        "sla": (
            "unchanged admission p95<=500ms; submit/status/cancel p95<=1000ms; errors0, all100/cell"
        ),
        "workload": (
            "original one signed synthetic SOTref; c1/10/25/50; 100 cases/cell; four API operations"
        ),
        "effect_envelope": (
            "serving executor OFF; synthetic queueing true; observer OFF; no worker/provider"
        ),
        "native_and_outer_blockers": [
            "direct native/cached-fd temp writes before Python accounting",
            ("platform-owned Codex tool transcript cannot be precharged or owned"),
        ],
    }
