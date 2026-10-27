"""Explicit scripted transport fixture, NOT AI. Loaded only in WORKSPACE_TEST_MODE.

Commands fixture:chat/create/edit/brief/table/patch/research/slow/error are integration probes.
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
        def payload(part):
            value = part.content
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except ValueError:
                    return value
            return value

        if command in {"fixture:brief", "fixture:table"}:
            reads = [payload(part) for part in returned if part.tool_name == "read_file"]
            if any(part.tool_name == "write_artifact" for part in returned):
                yield "SIMULATION: all requested source chunks were read and the draft was saved."
                return
            pending = []
            for source in inventory["files"]:
                chunks = [r for r in reads if isinstance(r, dict) and r["id"] == source["id"]]
                last = max(chunks, key=lambda r: r["offset"]) if chunks else None
                if last is None or last["has_more"]:
                    pending.append((source["id"], last["next_offset"] if last else 0))
            if pending:
                yield {i: DeltaToolCall(name="read_file", json_args=json.dumps(dict(file_id=file_id, offset=offset, limit=32000)), tool_call_id=f"fixture-read-{file_id}-{offset}") for i, (file_id, offset) in enumerate(pending)}
                return
            if command == "fixture:table":
                csv_files = [f for f in inventory["files"] if f["filename"].lower().endswith(".csv")]
                if not csv_files:
                    yield "SIMULATION: fixture:table requires an uploaded CSV; no invented source table was created."
                    return
                content = "".join(r["content"] for r in sorted(reads, key=lambda r: (r["id"], r["offset"])) if r["id"] == csv_files[0]["id"])
                args = dict(title="Synthetic preserved source table", filename="table.csv", content=content)
            else:
                sections = []
                for source in inventory["files"]:
                    text = "".join(r["content"] for r in sorted(reads, key=lambda r: r["offset"]) if r["id"] == source["id"])
                    sections.append("## Source: " + source["filename"] + "\n\n" + text)
                args = dict(title="Synthetic multi-source brief", filename="brief.md", content="# Synthetic multi-source brief\n\n" + "\n\n".join(sections) + "\n\nFixture copy-through, not AI synthesis.\n")
            yield {0: DeltaToolCall(name="write_artifact", json_args=json.dumps(args), tool_call_id="fixture-write")}
            return
        if command == "fixture:patch":
            if not inventory["artifacts"]:
                yield "SIMULATION: no artifact to patch."
                return
            if not returned:
                yield {0: DeltaToolCall(name="read_artifact", json_args=json.dumps({"artifact_id": inventory["artifacts"][0]["id"]}), tool_call_id="fixture-read")}
                return
            if len(returned) == 1:
                item = payload(returned[0])
                marker = "Fixture output, not AI analysis."
                if item["content"].count(marker) != 1:
                    marker = "Fixture copy-through, not AI synthesis."
                args = dict(artifact_id=item["id"], expected_version=item["version"], old_text=marker, new_text="Fixture localized revision, not AI analysis.")
                yield {0: DeltaToolCall(name="edit_artifact", json_args=json.dumps(args), tool_call_id="fixture-patch")}
                return
            yield "SIMULATION: one exact text region was revised; surrounding content was retained."
            return
        if command == "fixture:research":
            if not returned:
                yield {0: DeltaToolCall(name="search_web", json_args=json.dumps({"query": "Harbor"}), tool_call_id="fixture-search")}
                return
            results = payload(returned[0])["results"]
            if len(returned) == 1:
                yield {i: DeltaToolCall(name="read_web", json_args=json.dumps({"source_id": source["id"]}), tool_call_id="fixture-web-read-" + source["id"]) for i, source in enumerate(results)}
                return
            if not any(p.tool_name == "import_web_source" for p in returned):
                yield {i: DeltaToolCall(name="import_web_source", json_args=json.dumps({"source_id": source["id"]}), tool_call_id="fixture-import-" + source["id"]) for i, source in enumerate(results)}
                return
            if not any(p.tool_name == "write_artifact" for p in returned):
                sources = [payload(part)["source"] for part in returned if part.tool_name == "read_web"]
                content = "# OFFLINE FIXTURE research brief\n\nNot real internet research or AI synthesis. Conflicting dated estimates remain distinct.\n\n" + "\n\n".join(s["content"] + f"\nSource: {s['url']} (as of {s['as_of']}; SHA256 {s['sha256']}; offline_fixture)" for s in sources)
                yield {0: DeltaToolCall(name="write_artifact", json_args=json.dumps(dict(title="Offline fixture research brief", filename="research.md", content=content)), tool_call_id="fixture-write")}
                return
            yield "SIMULATION: offline fixture research was saved with dated source snapshots; no real internet was used."
            return
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
                source = payload(returned[0])
                if editing:
                    if isinstance(source, str):
                        source = json.loads(source)
                    content = source["content"] + "\n\n## Revision\n\nSynthetic follow-up edit retained the original numbers.\n"
                    args = dict(title=source["title"], filename=source["filename"], content=content,
                                artifact_id=source["id"], expected_version=source["version"])
                else:
                    if isinstance(source, dict):
                        if source["has_more"]:
                            yield "SIMULATION: fixture:create is a small-source probe; use fixture:brief to read complete multi-chunk sources."
                            return
                        source = source["content"]
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
