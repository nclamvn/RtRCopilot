"""Explicit scripted transport fixture, NOT AI. Loaded only in WORKSPACE_TEST_MODE.

Commands fixture:chat/create/edit/slow/error are deterministic integration probes.
No natural-language intent or quality claim is made by this model.
"""
import asyncio
import json

from pydantic_ai.messages import UserPromptPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel


def build_model():
    async def stream(messages, info):
        latest, returned = "", []
        for message in messages:
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    latest, returned = str(part.content), []
                elif isinstance(part, ToolReturnPart):
                    returned.append(part)
        inventory = json.loads(latest.split("Workspace inventory (opaque IDs):\n", 1)[1])
        command = latest.splitlines()[0].strip()
        if command == "fixture:error":
            raise RuntimeError("synthetic_provider_outage")
        if command == "fixture:slow":
            yield "Simulation started. "
            await asyncio.sleep(8)
            yield "Simulation finished."
            return
        if command in {"fixture:create", "fixture:edit"}:
            editing = command == "fixture:edit"
            if not returned:
                collection = inventory["artifacts" if editing else "files"]
                if not collection:
                    yield "SIMULATION: no input is available."
                    return
                name = "read_artifact" if editing else "read_file"
                args = {"artifact_id" if editing else "file_id": collection[0]["id"]}
                yield {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id="fixture-read")}
                return
            if len(returned) == 1:
                source = returned[0].content
                if editing:
                    if isinstance(source, str):
                        source = json.loads(source)
                    content = source["content"] + "\n\n## Revision\n\nSynthetic follow-up edit retained the original numbers.\n"
                    args = dict(title=source["title"], filename=source["filename"], content=content,
                                artifact_id=source["id"], expected_version=source["version"])
                else:
                    args = dict(title="Synthetic source brief", filename="brief.md",
                                content="# Synthetic source brief\n\n" + str(source) + "\n\nFixture output, not AI analysis.\n")
                yield {0: DeltaToolCall(name="write_artifact", json_args=json.dumps(args), tool_call_id="fixture-write")}
                return
            yield "SIMULATION: the Markdown draft was saved using the scoped artifact tool."
            return
        for text in ["SIMULATION: ", "This scripted fixture validates live streaming, ", "not model quality or reasoning. ", "Use fixture:create or fixture:edit for artifact probes."]:
            yield text
            await asyncio.sleep(0.04)
    return FunctionModel(stream_function=stream, model_name="workspace-simulation-v1")
