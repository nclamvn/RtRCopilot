"""Finite unframed raw pipes owned by the unchanged full terminal class; no SQL."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Literal, TypedDict

from envelope import Capture
from producers import request_class
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

HERE = Path(__file__).absolute().parent


async def _finite_child(
    capture: Capture,
    mode: Literal["ok", "delay", "excess"] = "ok",
    started: asyncio.Event | None = None,
) -> PipeResult:
    if mode not in ("ok", "delay", "excess"):
        capture.fail("fixed finite child only")
    cls = request_class(capture)  # Full source and module identity checked before any spawn.
    if (
        hashlib.sha256((HERE / "raw_child.py").read_bytes()).hexdigest()
        != "11b47b29c61e8d577bdbdd8ccf63e2148e3fcb71876c5990a68c45c3269c9b0f"
    ):
        capture.fail("fixed raw emitter source drift before spawn")
    engine = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/unused")
    owner = cls(async_sessionmaker(engine, expire_on_commit=False))
    outputs: dict[str, bytes] = {}

    async def drain(reader: asyncio.StreamReader, family: str, maximum: int) -> bytes:
        raw = bytearray()
        while chunk := await reader.read(1024):
            raw.extend(chunk)
            if len(raw) > 4096:
                raise ValueError("fixed finite emitter bound, not arbitrary child support")
        outputs[family] = bytes(raw)
        if len(raw) > maximum:
            raise ValueError("whole raw stream exceeds family, never split")
        return bytes(raw)

    async def operation() -> dict[str, bytes]:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            str(HERE / "raw_child.py"),
            mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=HERE,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if started is not None:
            started.set()
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("owned pipes missing")
        result = await asyncio.gather(
            drain(process.stdout, "summary_stdout", 16384),
            drain(process.stderr, "load_stderr", 512),
            process.wait(),
            return_exceptions=True,
        )
        for value in result:
            if isinstance(value, BaseException):
                raise value
        if process.returncode != 0:
            raise RuntimeError("finite local emitter failed")
        return outputs

    original = None
    try:
        result = await owner.join_terminal(operation())
        for family, raw in result.items():
            if raw:
                capture.record(family, raw)
        return {"outputs": result, "joined": owner.terminal_task is None, "full_class": True}
    except BaseException as error:
        capture.invalidate()
        original = error
        raise
    finally:
        try:
            await engine.dispose()  # Never checked out; no database or physical lease proof.
        except BaseException as cleanup:
            capture.invalidate()
            if original is not None:
                raise original from cleanup
            raise


class PipeResult(TypedDict):
    outputs: dict[str, bytes]
    joined: bool
    full_class: bool


async def finite_child(
    capture: Capture,
    mode: Literal["ok", "delay", "excess"] = "ok",
    started: asyncio.Event | None = None,
) -> PipeResult:
    try:
        capture.guard()
        return await _finite_child(capture, mode, started)
    except BaseException:
        capture.invalidate()
        raise
