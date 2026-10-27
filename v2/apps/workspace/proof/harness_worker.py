"""Standalone real-SQL harness probe; FunctionModel output is scripted, not AI quality evidence."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import socket
import sqlite3
import sys
from pathlib import Path

from dbos import DBOS, SetWorkflowID
from pydantic_ai import Agent
from pydantic_ai.durable_exec.dbos import DBOSDurability
from pydantic_ai.messages import PartDeltaEvent, PartStartEvent, TextPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.usage import UsageLimits


async def main(root: Path, mode: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    log = sqlite3.connect(root / "evidence.sqlite")
    log.execute("CREATE TABLE IF NOT EXISTS log (seq INTEGER PRIMARY KEY, kind TEXT, data TEXT)")
    log.execute("CREATE TABLE IF NOT EXISTS receipts (operation_key TEXT PRIMARY KEY, result TEXT)")
    log.execute("CREATE TABLE IF NOT EXISTS event_receipts (event_key TEXT PRIMARY KEY)")
    log.commit()

    def record(kind: str, data: object = None) -> None:
        log.execute("INSERT INTO log(kind,data) VALUES (?,?)", (kind, json.dumps(data)))
        log.commit()

    # Dependency/SQL proof must never silently acquire a provider network lane.
    def deny_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("Harness proof forbids all socket connections")

    socket.socket.connect = deny_connect
    DBOS(config={
        "name": "agent-workspace-harness-proof",
        "application_version": "aw01-proof-v1",
        "system_database_url": f"sqlite:///{root / 'dbos.sqlite'}",
        "enable_otlp": False,
        "log_level": "ERROR",
    })

    async def stream(messages, info):
        record("model_call")
        record("model_step", DBOS.step_id)
        if not any(isinstance(part, ToolReturnPart) for message in messages for part in message.parts):
            yield {0: DeltaToolCall(name="read_source", json_args='{}', tool_call_id="read-1")}
            return
        yield "first "
        if mode == "stream-crash":
            await asyncio.sleep(30)
        await asyncio.sleep(0.08 if mode != "cancel" else 1)
        yield "second"
        record("model_finished")

    async def on_event(ctx, events):
        index = 0
        async for event in events:
            key = f"{DBOS.step_id}:{index}"
            index += 1
            if not log.execute("INSERT OR IGNORE INTO event_receipts VALUES (?)", (key,)).rowcount:
                continue
            if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                record("text", event.part.content)
            elif isinstance(event, PartDeltaEvent):
                record("delta", dataclasses.asdict(event.delta))
            else:
                record("event", event.event_kind)

    @DBOS.step()
    async def read_source() -> str:
        """Read the synthetic source from the authorized proof scope."""
        record("tool_attempt")
        # This local SQL receipt, not the DBOS checkpoint, makes a crash after the
        # effect safe to retry. External effects need endpoint idempotency/reconcile.
        value = "Synthetic source value: 42"
        if log.execute("INSERT OR IGNORE INTO receipts VALUES (?,?)", ("read-1", value)).rowcount:
            record("tool_effect", {"source": "synthetic", "value": 42})
        log.commit()
        if mode in {"before-receipt-crash", "deadline", "budget-pause"}:
            record("before_tool_checkpoint")
            await asyncio.sleep(30)
        return value

    agent = Agent(
        FunctionModel(stream_function=stream, model_name="aw01-scripted-fixture"),
        name="aw01_harness_proof_agent_v1",
        tools=[read_source],
        capabilities=[DBOSDurability(event_stream_handler=on_event, parallel_execution_mode="sequential")],
        retries=0,
    )

    @DBOS.step()
    async def checkpointed(output: str) -> None:
        record("checkpoint", output)

    @DBOS.step()
    async def publish(output: str) -> str:
        record("published", output)
        return output

    @DBOS.workflow()
    async def run() -> str:
        result = await agent.run(
            "Read source then summarize",
            timeout=1 if mode.startswith("deadline") else 30,
            usage_limits=UsageLimits(request_limit=1 if mode.startswith("budget") else 5),
        )
        await checkpointed(result.output)
        if mode in {"deadline", "budget"}:
            return result.output
        await DBOS.recv_async(topic="release", timeout_seconds=30)
        return await publish(result.output)

    DBOS.launch()
    with SetWorkflowID("aw01-proof-run"):
        handle = await DBOS.start_workflow_async(run)
    if mode in {"resume", "deadline-resume", "budget-resume"}:
        await DBOS.send_async("aw01-proof-run", "continue", topic="release")
    if mode == "cancel":
        for _ in range(100):
            if log.execute("SELECT count(*) FROM log WHERE kind='text'").fetchone()[0]:
                break
            await asyncio.sleep(0.02)
        await DBOS.cancel_workflow_async("aw01-proof-run")
        record("cancel_requested")
    try:
        output = await handle.get_result()
        record("result", output)
    except BaseException as error:
        record("exception", type(error).__name__)
    finally:
        record("status", (await DBOS.get_workflow_status_async("aw01-proof-run")).status)
        DBOS.destroy()
        log.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve(), sys.argv[2]))
