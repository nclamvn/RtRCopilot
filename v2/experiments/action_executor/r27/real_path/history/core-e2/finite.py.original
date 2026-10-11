"""Bounded exact local IPC child; no Linux group or arbitrary-child authority."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from transport import HostIPC

HERE = Path(__file__).absolute().parent
CHILD_SHA = "6a269f1266302742dc26c368d02ca1250d3073f32eb79394ee7fc1cdf4b21561"


@dataclass(frozen=True)
class Result:
    stdout: bytes
    stderr: bytes
    code: int
    pid: int
    reaped: bool
    tasks_joined: bool


async def output(reader: asyncio.StreamReader) -> bytes:
    raw = bytearray()
    while part := await reader.read(min(512, 4097 - len(raw))):
        if len(raw) + len(part) > 4096:
            raise ValueError("fixed child whole output limit")
        raw.extend(part)
    return bytes(raw)


async def run_child(
    server: HostIPC,
    mode: str = "ok",
    observe: Callable[[asyncio.subprocess.Process], None] | None = None,
) -> Result:
    broker = server.broker
    lease = broker.begin_operation()
    process: asyncio.subprocess.Process | None = None
    stdout: asyncio.Task[bytes] | None = None
    stderr: asyncio.Task[bytes] | None = None
    waiter: asyncio.Task[int] | None = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5

    async def operation() -> Result:
        nonlocal process, stdout, stderr, waiter
        source = HERE / "ipc_child.py"
        if (
            mode not in {"ok", "lost_ack", "bad_encode"}
            or source.is_symlink()
            or source.stat().st_size > 16384
            or hashlib.sha256(source.read_bytes()).hexdigest() != CHILD_SHA
        ):
            raise ValueError("exact local child source/mode")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            str(source),
            str(server.address),
            mode,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "R27_IPC_TOKEN": server.token,
            },
            cwd=server._cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if observe is not None:
            observe(process)
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("owned child pipe creation")
        stdout = asyncio.create_task(output(process.stdout), name="r27-control-stdout")
        stderr = asyncio.create_task(output(process.stderr), name="r27-control-stderr")
        waiter = asyncio.create_task(process.wait(), name="r27-control-reap")
        await asyncio.gather(stdout, stderr, waiter)
        return Result(stdout.result(), stderr.result(), waiter.result(), process.pid, True, True)

    task = asyncio.create_task(operation(), name="r27-control-child")
    primary: BaseException | None = None
    cleanup_fault: BaseException | None = None
    try:
        completed, _ = await asyncio.wait({task}, timeout=max(0, deadline - loop.time()))
        if not completed:
            raise TimeoutError("fixed child control deadline")
        return task.result()
    except BaseException as error:
        primary = error
        broker.capture_fault(error)
        raise
    finally:
        if server._deadline is None:
            server._deadline = time.monotonic() + 10
        cleanup_deadline = loop.time() + max(0, server._deadline - time.monotonic())

        async def cleanup() -> None:
            nonlocal cleanup_fault
            # A pending spawn is owned by task; never cancel it and lose the Process.
            if process is None and not task.done():
                await asyncio.wait({task}, timeout=max(0, cleanup_deadline - loop.time()))
            if process is not None and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                except BaseException as error:
                    cleanup_fault = cleanup_fault or error
                if waiter is not None:
                    await asyncio.wait(
                        {waiter}, timeout=min(1, max(0, cleanup_deadline - loop.time()))
                    )
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    except BaseException as error:
                        cleanup_fault = cleanup_fault or error
            tasks = {t for t in (task, stdout, stderr, waiter) if t is not None}
            await asyncio.wait(tasks, timeout=max(0, cleanup_deadline - loop.time()))
            resolved = all(t.done() for t in tasks)
            reaped = (
                process is None
                and task.done()
                or (
                    process is not None
                    and process.returncode is not None
                    and waiter is not None
                    and waiter.done()
                )
            )
            # Retrieve all exceptions: no asyncio.run shutdown as implicit cleanup proof.
            for owned_task in tasks:
                if owned_task.done() and not owned_task.cancelled():
                    owned_task.exception()
            if not resolved or not reaped:
                cleanup_fault = cleanup_fault or TimeoutError(
                    "owned child unresolved; lease retained"
                )
            else:
                broker.end_operation(lease)
            if cleanup_fault is not None:
                broker.capture_fault(cleanup_fault)
                raise cleanup_fault

        terminal = asyncio.create_task(cleanup(), name="r27-control-terminal")
        while not terminal.done():
            try:
                await asyncio.shield(terminal)
            except asyncio.CancelledError as error:
                primary = primary or error
                broker.capture_fault(error)
            except BaseException:
                break
        try:
            terminal.result()
        except BaseException as error:
            if primary is not None and primary is not error:
                raise primary from error
            raise
        if primary is not None:
            raise primary
