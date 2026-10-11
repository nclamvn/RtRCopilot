"""Closed finite local native EOF route; arbitrary/effectful commands remain denied."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from host import OwnedBroker
from ports import PathPort

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]
CHILD_SHA = "bd995ec8b7752dfb2d0fff323fdfa9e9f46a125b8ce8d596734d36c944ae4258"
DF_SHA = "eb5b6b85a37afa7b201baada03cc6b4173bbdcdd07e4fae586dfd6841ea2f1db"
R21_SHA = "4a2de34ec8fd9ea33a036f9770e2a9e40289c30ed164954624d0bff547dc43b1"
Mode = Literal["okay", "overflow", "nonzero", "delay"]
Kind = Literal["control", "host_df"]
EOF_CAP = 2048  # Original source_cap_child whole-record domain, unchanged.


@dataclass
class Cleanup:
    deadline: float | None = None

    def remaining(self) -> float:
        if self.deadline is None:
            self.deadline = time.monotonic() + 10
        return max(0, self.deadline - time.monotonic())


@dataclass(frozen=True)
class Result:
    stdout: bytes
    stderr: bytes
    code: int
    pid: int
    reaped: bool
    tasks_joined: bool


class NativeFailure(RuntimeError):
    """Raw EOF retained, but original closed command returned nonzero."""


async def whole(reader: asyncio.StreamReader, ceiling: int) -> bytes:
    value = bytearray()
    while block := await reader.read(min(512, ceiling + 1 - len(value))):
        value.extend(block)
        if len(value) > ceiling:
            raise ValueError("whole native EOF exceeds declared family; never split")
    return bytes(value)


async def run(
    broker: OwnedBroker,
    port: PathPort,
    mode: Mode = "okay",
    *,
    cleanup: Cleanup | None = None,
    seconds: float = 5,
    observe: Callable[[asyncio.subprocess.Process], None] | None = None,
    kind: Kind = "control",
) -> Result:
    """Only exact pinned local producer. No arbitrary argv, root/fd export or descendants."""
    lifetime = cleanup or Cleanup()
    process: asyncio.subprocess.Process | None = None
    stdout: asyncio.Task[bytes] | None = None
    stderr: asyncio.Task[bytes] | None = None
    waiter: asyncio.Task[int] | None = None
    task: asyncio.Task[Result] | None = None
    lease: str | None = None
    primary: BaseException | None = None

    async def operation() -> Result:
        nonlocal process, stdout, stderr, waiter
        source = HERE / "native_child.py"
        if (
            mode not in {"okay", "overflow", "nonzero", "delay"}
            or type(seconds) not in (int, float)
            or not 0 < seconds <= 5
            or source.is_symlink()
            or source.stat().st_size > 4096
            or hashlib.sha256(source.read_bytes()).hexdigest() != CHILD_SHA
        ):
            raise ValueError("closed native producer identity/budget")
        command: tuple[str, ...] = (sys.executable, "-B", str(source), mode)
        ceiling, family = EOF_CAP, "source_cap_child"
        if kind == "host_df":
            original = ROOT / "v2/experiments/action_executor/r21/run-http-qualification.sh"
            executable = Path("/bin/df")
            if (
                mode != "okay"
                or original.is_symlink()
                or original.stat().st_size > 65536
                or hashlib.sha256(original.read_bytes()).hexdigest() != R21_SHA
                or b'df -k / > "$evidence/$1-host-disk.txt"' not in original.read_bytes()
                or executable.is_symlink()
                or executable.stat().st_size > 1048576
                or hashlib.sha256(executable.read_bytes()).hexdigest() != DF_SHA
            ):
                raise ValueError("exact original read-only host df endpoint")
            command = (str(executable), "-k", "/")
            ceiling, family = 4096, "disk"
        elif kind != "control":
            raise ValueError("closed command kind")
        process = await asyncio.create_subprocess_exec(
            *command,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
            cwd=ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("exact native pipes missing")
        stdout = asyncio.create_task(whole(process.stdout, ceiling), name="r27-native-stdout")
        stderr = asyncio.create_task(whole(process.stderr, ceiling), name="r27-native-stderr")
        waiter = asyncio.create_task(process.wait(), name="r27-native-reap")
        if observe is not None:
            observe(process)
        await asyncio.gather(stdout, stderr, waiter)
        # EOF and observed reap are necessary; recv chunks are NEVER qualifying records.
        raw_out, raw_err, code = stdout.result(), stderr.result(), waiter.result()
        port.mkdir("native", exist_ok=True)
        port.write("native/" + kind + ".stdout", family, raw_out, "x")
        port.write("native/" + kind + ".stderr", family, raw_err, "x")
        port.flush()
        if code != 0:
            raise NativeFailure(f"closed native command exit {code}; whole EOF retained")
        return Result(raw_out, raw_err, code, process.pid, True, True)

    try:
        port.check()
        lease = broker.begin_operation()
        task = asyncio.create_task(operation(), name="r27-native-operation")
        done, _ = await asyncio.wait({task}, timeout=seconds)
        if not done:
            raise TimeoutError("closed native control deadline")
        result = task.result()
    except BaseException as error:
        primary = error
        broker.capture_fault(error)
    finally:
        if lease is not None:
            lifetime.remaining()  # Persist FIRST absolute deadline before cleanup begins.

            async def terminal() -> None:
                faults: list[BaseException] = []
                if process is None and task is not None and not task.done():
                    await asyncio.wait({task}, timeout=lifetime.remaining())
                if process is not None and process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    except BaseException as error:
                        faults.append(error)
                    if waiter is not None:
                        await asyncio.wait({waiter}, timeout=min(1, lifetime.remaining()))
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        except BaseException as error:
                            faults.append(error)
                tasks = {t for t in (task, stdout, stderr, waiter) if t is not None}
                await asyncio.wait(tasks, timeout=lifetime.remaining())
                reaped = (process is None and (task is None or task.done())) or (
                    process is not None
                    and process.returncode is not None
                    and waiter is not None
                    and waiter.done()
                )
                joined = all(t.done() for t in tasks)
                for owned in tasks:
                    if owned.done() and not owned.cancelled():
                        owned.exception()
                if reaped and joined:
                    broker.end_operation(lease)
                else:
                    faults.append(TimeoutError("unresolved owned native child; lease retained"))
                if faults:
                    broker.capture_fault(faults[0])
                    raise faults[0]

            ending = asyncio.create_task(terminal(), name="r27-native-terminal")
            while not ending.done():
                try:
                    await asyncio.shield(ending)
                except asyncio.CancelledError as error:
                    primary = primary or error
                    broker.capture_fault(primary)
                except BaseException:
                    break
            try:
                ending.result()
            except BaseException as error:
                if primary is not None and primary is not error:
                    raise primary from error
                raise
    if primary is not None:
        raise primary
    return result


def absent(pid: int) -> bool:
    """Observed existence check for this returned exact child, never signal authority."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def dispatch(command: tuple[str, ...]) -> None:
    raise PermissionError("DENY: original native/effectful command not admitted: " + repr(command))
