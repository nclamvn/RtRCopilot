"""Actual original safe writer endpoints and effectful source-prepared DENY seams."""

from __future__ import annotations

import ast
import json
import math
import os
import signal
import time
from collections.abc import Callable
from typing import cast

from composition import ROOT, compile_functions, digest, mapping, source
from ports import PathPort, RichPath

R21 = "v2/experiments/action_executor/r21/run-http-qualification.sh"
R19 = "v2/experiments/action_executor/r19/bounded.py"
QUALIFICATION = "v2/experiments/action_executor/r21/qualification.py"
EPOCH = "r27_real_http_e1"
DOMAIN = "rtr_tip054_r27_real_local_e1"
ENGINE = "rtr_tip054_r27_real_engine_e1"
DSN = "postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/" + DOMAIN


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


class Controller:
    def __init__(self, port: PathPort) -> None:
        self.port = port
        try:
            self.shell = source(R21).decode()
            self.supervisor = source(R19)
            self.routes = mapping(
                json.loads(source("v2/experiments/action_executor/r21/contract.json"))
            )
            self.port.mkdir("controller", exist_ok=True)
            self.port.mkdir("owner", exist_ok=True)
            self.__linux = compile_functions(
                R19,
                (
                    "process",
                    "group_members",
                    "signal_owned",
                    "drain",
                    "begin_cleanup",
                    "child_budget",
                ),
                {
                    "Path": __import__("pathlib").Path,
                    "os": os,
                    "signal": signal,
                    "time": time,
                    "math": math,
                    "json": json,
                    "require": require,
                    "suppress": __import__("contextlib").suppress,
                    "CAPS": {"kill_grace_seconds": 10, "http_seconds": 190, "child_seconds": 120},
                },
            )
            self.cleanup = cast(
                Callable[[dict[str, object], RichPath], float], self.__linux["begin_cleanup"]
            )
        except BaseException as error:
            port.capture_fault(error)
            raise

    def copy_sources(self) -> None:
        """Genuine original cp byte endpoints, with only destination owner changed."""
        try:
            if (
                'cp "$binding" "$evidence/binding.json"' not in self.shell
                or 'cp "$r21_dir/contract.json" "$evidence/contract.json"' not in self.shell
            ):
                raise ValueError("exact original copy operations")
            for name, original in (
                ("binding.json", "v2/experiments/action_executor/r21/source-binding-e1.json"),
                ("contract.json", "v2/experiments/action_executor/r21/contract.json"),
            ):
                raw = source(original)
                self.port.write("controller/" + name, "frozen_copies", raw, "x")
            self.port.flush()
        except BaseException as error:
            self.port.capture_fault(error)
            raise

    def scope_literal(self) -> bytes:
        try:
            line = next(
                line
                for line in self.shell.splitlines()
                if line.endswith('> "$evidence/executor-scope.txt"')
            )
            literal = line.split("'", 2)[1]
            raw = literal.replace("\\n", "\n").encode()
            self.port.write("controller/executor-scope.txt", "literal_scope", raw, "x")
            self.port.flush()
            return raw
        except BaseException as error:
            self.port.capture_fault(error)
            raise

    def returncode(self, label: str, code: int) -> None:
        try:
            if (
                'printf \'%s %d\\n\' "$label" "$code"' not in self.shell
                or label
                not in {
                    "syntax",
                    "pins",
                    "ruff",
                    "format",
                    "collection",
                    "inventory",
                    "offline",
                    "envelope",
                    "migration",
                    "load",
                }
                or type(code) is not int
            ):
                raise ValueError("closed original returncode endpoint")
            self.port.write(
                "controller/returncodes.txt", "returncodes", f"{label} {code}\n".encode(), "a"
            )
            self.port.flush()
        except BaseException as error:
            self.port.capture_fault(error)
            raise

    def marker_control(self, candidate_sha: str) -> None:
        """Owned exclusive local control only; never the future campaign marker."""
        try:
            if len(candidate_sha) != 64 or any(
                char not in "0123456789abcdef" for char in candidate_sha
            ):
                raise ValueError("exact candidate SHA")
            raw = json.dumps(
                {
                    "schema": "r27-local-marker-control",
                    "candidate": candidate_sha,
                    "consumed_on_unknown": True,
                },
                separators=(",", ":"),
            ).encode()
            self.port.write("controller/control-marker.json", "launch_review", raw, "x")
            self.port.flush()
        except BaseException as error:
            self.port.capture_fault(error)
            raise

    def cleanup_deadline(self, owner: dict[str, object]) -> float:
        try:
            return self.cleanup(owner, self.port.path("owner/load.owner.json", "owner_process"))
        except BaseException as error:
            self.port.capture_fault(error)
            raise

    def prepared(self) -> dict[str, object]:
        """Exact original command inventory, explicit new namespace substitutions."""
        commands = [
            line
            for line in self.shell.replace("\\\n", "").splitlines()
            if line.lstrip().startswith(
                ("checked ", "pg_sql ", "exec_runner ", "df ", '"$docker_path" ', "python3 ")
            )
        ]
        return {
            "original_launcher_sha256": digest(self.shell.encode()),
            "original_supervisor_sha256": digest(self.supervisor),
            "commands_original": commands,
            "environment_original": self.shell.split("base_env=(", 1)[1].split(
                "# Real stdlib guard", 1
            )[0],
            "future_exact_dsns": {
                "POSTGRES_DSN": DSN,
                "INTEGRATION_DATABASE_DSN": DSN,
                "MIGRATION_DSN": DSN.replace("rtr_app:", "rtr_tip054_local:"),
                "ACTION_WORKFLOW_DSN": DSN.replace("rtr_app:", "rtr_tip054_engine:").replace(
                    DOMAIN, ENGINE
                ),
            },
            "roles_original": {
                "domain_owner": "rtr_tip054_local",
                "domain_client": "rtr_app",
                "engine": "rtr_tip054_engine",
            },
            "resources": "retained R12 fixture source review/live identity/capacity NOT_RUN; "
            "source unchanged",
            "resolution": "PREPARED_ONLY_NOT_DISPATCHED",
            "substitutions": {
                "r21_http_e1": EPOCH,
                "rtr_tip054_r21_local_e1": DOMAIN,
                "rtr_tip054_r21_engine_e1": ENGINE,
                "r21-campaign-launch.json": "r27-real-campaign-launch.json",
            },
            "limits": {"load_seconds": 190, "cleanup_seconds": 10, "other_child_seconds": 120},
            "linux_functions": [
                name
                for name in self.__linux
                if callable(self.__linux[name]) and name not in {"Path", "require", "suppress"}
            ],
            "native": "NOT_RUN: Linux /proc/killpg prepared; "
            "native EOF only when whole family domain admits",
            "plugins": {
                "pytest_junit": "UNSUPPORTED_BEFORE_DISPATCH",
                "alembic_fileConfig": "UNSUPPORTED_BEFORE_DISPATCH",
            },
            "effects": "DENY_THIS_BATCH",
            "source_entry": str(ROOT / R21),
        }

    def dispatch(self, command: tuple[str, ...]) -> None:
        raise PermissionError(
            "DENY before native/plugin/Linux/SQL/Docker/HTTP effects: " + repr(command)
        )


def full_ast_proof() -> dict[str, object]:
    raw = source(R19)
    tree = ast.parse(raw)
    return {
        "full_source_sha256": digest(raw),
        "full_ast_sha256": digest(ast.dump(tree, include_attributes=True).encode()),
        "native_fd_dependency": "Popen stdout/stderr native descriptor ports; "
        "original unadapted launcher MUST NOT run",
        "group_execution": "NOT_RUN",
    }
