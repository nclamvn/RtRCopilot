"""Safe fixed-child lifecycle plus original R19 metadata writer subset, not group authority."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pipes import PipeResult, finite_child
from types import SimpleNamespace
from typing import Literal

from envelope import Capture
from launcher import R19, mapping, original_cleanup_writer, source


@dataclass(frozen=True)
class LocalSupervisorResult:
    joined: bool
    outputs: dict[str, bytes]
    original_metadata_subset: bool
    linux_group_authority: bool
    cleanup_deadline: float
    cleanup_not_renewed: bool


class SourceSupervisor:
    def __init__(self, capture: Capture) -> None:
        self.capture = capture
        try:
            self._prepare()
        except BaseException:
            capture.invalidate()
            raise

    def _prepare(self) -> None:
        capture = self.capture
        self.owner_path = capture.register("supervisor/local-control.owner.json", "owner_process")
        self.process_path = capture.register(
            "supervisor/local-control.process.json", "owner_process"
        )
        self.stop_path = capture.register(
            "supervisor/local-control-stop-proof.txt", "supervisor_stop"
        )
        self.cleanup_writer = original_cleanup_writer()
        tree = ast.parse(source(R19))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "supervise"
        )
        expressions = {}
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                name = ast.unparse(node.targets[0])
                if name in {"owner", "result"}:
                    expressions[name] = compile(
                        ast.Expression(node.value), R19 + "#" + name, "eval"
                    )
        if set(expressions) != {"owner", "result"}:
            raise ValueError("R19 original metadata producer shape")
        self.expressions = expressions
        self.started = time.monotonic()

    def metadata_subset(self, result: PipeResult) -> LocalSupervisorResult:
        "One Capture scope after fixed child joined; not pre-spawn durability proof."
        namespace: dict[str, object] = {
            "child": SimpleNamespace(pid=os.getpid(), returncode=0),
            "token": uuid.uuid4().hex,
            "os": os,
            "time": time,
            "started": self.started,
            "reason": "completed",
            "code": 0,
            "process": lambda _pid: {"start": "LOCAL_SUBSET_NOT_LINUX_GROUP_AUTHORITY"},
        }
        try:
            self.capture.guard(context=True)
            owner = mapping(eval(self.expressions["owner"], namespace))
            namespace["owner"] = owner
            # Actual R19 owner/process JSON expressions and full begin_cleanup writer body.
            self.owner_path.write_text(json.dumps(owner), encoding="utf-8")
            deadline = self.cleanup_writer(owner, self.owner_path)
            first_bytes = self.owner_path.read_bytes()
            same_deadline = self.cleanup_writer(owner, self.owner_path)
            if same_deadline != deadline or self.owner_path.read_bytes() != first_bytes:
                raise ValueError("cleanup grace renewed")
            process = mapping(eval(self.expressions["result"], namespace))
            self.process_path.write_text(json.dumps(process, indent=2), encoding="utf-8")
            self.stop_path.write_bytes(
                b"LOCAL fixed child joined; original R19 metadata subset only\n"
            )
        except BaseException:
            self.capture.invalidate()
            raise
        return LocalSupervisorResult(
            result["joined"], result["outputs"], True, False, deadline, True
        )


async def fixed_control(
    capture: Capture,
    mode: Literal["ok", "delay", "excess"] = "ok",
    started: asyncio.Event | None = None,
) -> PipeResult:
    "Actual safe child, not original supervisor/SQL/HTTP or a replacement campaign."
    return await finite_child(capture, mode, started)


def preserve_primary(primary: BaseException, cleanup: BaseException) -> None:
    primary.add_note("R27 local supervisor cleanup failed; primary retained")
    raise primary from cleanup
