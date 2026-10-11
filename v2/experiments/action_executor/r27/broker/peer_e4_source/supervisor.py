"""Exact owned fixed-child supervision. Not Linux process-group/descendant authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from broker import Broker
from integration import ROOT, cleanup_writer, mapping, metadata_expressions

CHILD = ROOT / "v2/experiments/action_executor/r27/runtime/raw_child.py"
CHILD_SHA = "11b47b29c61e8d577bdbdd8ccf63e2148e3fcb71876c5990a68c45c3269c9b0f"


@dataclass(frozen=True)
class ChildResult:
    outputs: dict[str, bytes]
    pid: int
    returncode: int
    joined: bool
    cleanup_deadline: float
    deadline_attempts: int
    linux_group_authority: bool = False


async def owned_child(broker: Broker, mode: Literal["ok", "delay", "excess"] = "ok",
                      started: asyncio.Event | None = None) -> ChildResult:
    try:
        if mode not in {"ok", "delay", "excess"} or CHILD.is_symlink():
            raise ValueError("fixed admitted child only")
        if hashlib.sha256(CHILD.read_bytes()).hexdigest() != CHILD_SHA:
            raise ValueError("unchanged raw child source pin")
        begin = cleanup_writer(broker)
        expressions = metadata_expressions(broker)
        broker.path("supervisor").mkdir(exist_ok=True)
        owner_path = broker.path("supervisor/owner.json", "owner_process")
        process_path = broker.path("supervisor/process.json", "owner_process")
    except BaseException:
        broker.invalidate()
        raise
    process: asyncio.subprocess.Process | None = None
    owner: dict[str, object] = {"cleanup_deadline": None}
    readers: list[asyncio.Task[bytes]] = []
    deadline: float | None = None
    deadline_attempts = 0
    received: dict[str, bytes] = {}
    began = time.monotonic()
    primary: BaseException | None = None
    cleanup_error: BaseException | None = None

    async def drain(reader: asyncio.StreamReader, family: str, maximum: int) -> bytes:
        raw = bytearray()
        while chunk := await reader.read(min(1024, maximum - len(raw) + 1)):
            if len(raw) + len(chunk) > maximum:
                raise ValueError("whole fixed raw stream excess; no prefix/truncation")
            raw.extend(chunk)
        received[family] = bytes(raw)
        return bytes(raw)

    async def operation() -> None:
        nonlocal process, owner
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", str(CHILD), mode,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=4096,
            cwd=CHILD.parent, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("exact child pipes missing")
        readers.extend((asyncio.create_task(drain(process.stdout, "summary_stdout", 4096)),
                        asyncio.create_task(drain(process.stderr, "load_stderr", 512))))
        namespace: dict[str, object] = {"child": process, "token": uuid.uuid4().hex, "os": os,
            "process": lambda _pid: {"start": "HOST_EXACT_CHILD_NOT_LINUX_GROUP"}}
        old_deadline = owner.get("cleanup_deadline")
        owner = mapping(eval(expressions["owner"], namespace))
        if old_deadline is not None:
            owner["cleanup_deadline"] = old_deadline
        owner_path.write_text(json.dumps(owner))
        if started is not None:
            started.set()
        result = await asyncio.gather(*readers, process.wait(), return_exceptions=True)
        for item in result:
            if isinstance(item, BaseException):
                raise item
        if process.returncode != 0:
            raise RuntimeError("exact finite child failed")

    operation_task = asyncio.create_task(operation())

    async def cleanup() -> None:
        nonlocal deadline, deadline_attempts, cleanup_error
        deadline_attempts += 1
        try:
            deadline = begin(owner, owner_path)  # Actual R19 source: assignment before overwrite.
        except BaseException as error:
            cleanup_error = error
            value = owner.get("cleanup_deadline")
            deadline = float(value) if isinstance(value, (int, float)) else time.monotonic() + 10
        # Spawn can still be completing after parent cancellation; never abandon that task.
        while process is None and not operation_task.done() and time.monotonic() < deadline:
            await asyncio.sleep(0)
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), max(.001, deadline - time.monotonic() - 2))
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), max(.001, deadline - time.monotonic()))
        if readers:
            await asyncio.wait_for(asyncio.gather(*readers, return_exceptions=True),
                                   max(.001, deadline - time.monotonic()))
        await asyncio.wait_for(asyncio.gather(operation_task, return_exceptions=True),
                               max(.001, deadline - time.monotonic()))
        if process is None or process.returncode is None:
            raise RuntimeError("exact owned child not reaped")

    try:
        await asyncio.shield(operation_task)
    except BaseException as error:
        primary = error
    finally:
        terminal = asyncio.create_task(cleanup())
        while True:
            try:
                await asyncio.shield(terminal)
                break
            except asyncio.CancelledError as error:
                primary = primary or error
                if terminal.done():
                    try:
                        terminal.result()
                    except BaseException as fault:
                        cleanup_error = cleanup_error or fault
                    break
            except BaseException as fault:
                cleanup_error = cleanup_error or fault
                break
    if process is None or deadline is None:
        broker.invalidate()
        if primary is not None:
            raise primary from cleanup_error
        raise RuntimeError("exact child spawn/cleanup unresolved") from cleanup_error
    try:
        namespace = {"child": process, "owner": owner, "code": 0 if primary is None else 125,
                     "reason": "completed" if primary is None else "interrupted_or_fault",
                     "started": began, "time": time}
        metadata = mapping(eval(expressions["result"], namespace))
        process_path.write_text(json.dumps(metadata, indent=2))
        if primary is None and cleanup_error is None:
            # Exactly one whole EOF record per stream; sidecar AND packet precharged by sole broker.
            for family, raw in received.items():
                broker.path("supervisor/" + family + ".raw", family).write_bytes(raw)
    except BaseException as fault:
        cleanup_error = cleanup_error or fault
    if primary is not None:
        broker.invalidate()
        if cleanup_error is not None:
            primary.add_note("broker child cleanup/storage fault; primary retained")
            raise primary from cleanup_error
        raise primary
    if cleanup_error is not None:
        broker.invalidate()
        raise cleanup_error
    return ChildResult(received, process.pid, process.returncode or 0, True, deadline, deadline_attempts)
