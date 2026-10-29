"""Deterministic synthetic context-path measurement; no semantic/AI benchmark."""
import json
from pathlib import Path
import tempfile
import time

from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, UserPromptPart

from agent_workspace.continuity import Continuity, MAX_CONTEXT, render_prompt
from agent_workspace.store import Store
from agent_workspace.workspace_state import WorkspaceState

LIMITS = dict(deadline_seconds=120, request_limit=8, tool_limit=24, token_limit=32000, output_bytes_limit=256000)


def main():
    started = time.perf_counter()
    root = Path(__file__).resolve().parents[3] / "v2/apps/workspace"
    with tempfile.TemporaryDirectory(prefix=".aw06-root-measure-", dir=root) as scratch:
        store = Store(Path(scratch) / "catalogue.sqlite")
        state = WorkspaceState(store)
        continuity = Continuity(store)
        _, owner = store.session(None)
        wid = store.workspaces(owner, "Synthetic glacier observations")["id"]
        sources = []
        for number in range(12):
            source = store.upload(owner, wid, f"synthetic-{number:02d}.txt", (f"Synthetic station {number:02d}; reading 008291 and 73.875 mm.\n" * 1500), "text/plain")
            sources.append(source)
        brief = continuity.save_brief(owner, wid, 0, "Update synthetic station 08 only.", "Retain both original and corrected observations.", "Read the complete selected source before claiming complete coverage.", "root-measure-brief")
        # Explicitly authored synthetic protocol, not real model use or a run cost.
        large_protocol = []
        for number in range(20):
            large_protocol.extend([ModelRequest(parts=[UserPromptPart(f"Synthetic historical turn {number}: " + "A" * 14000)]), ModelResponse(parts=[TextPart("Synthetic historical answer: " + "B" * 14000)])])
        protocol = ModelMessagesTypeAdapter.dump_json(large_protocol).decode()
        previous = store.create_run(owner, wid, "Synthetic historical placeholder.", "root-measure-historical", LIMITS)
        state.bind_run_epoch(owner, previous["id"])
        store.finish(owner, previous["id"], "completed", content="Synthetic visible historical answer, retained.", history=protocol)
        query = "Update synthetic station 08 only, using the selected source."
        options = dict(references=[dict(kind="file", id=sources[8]["id"])], target=None)
        run = store.create_run(owner, wid, query, "root-measure-current", LIMITS, context=options)
        state.bind_run_epoch(owner, run["id"])
        before = len(store.items(owner, wid, "messages"))
        legacy_history, legacy_files, legacy_outputs = store.context(owner, run["id"])
        baseline_bytes = len(legacy_history.encode())
        times = []
        manifest = None
        for _ in range(20):
            tick = time.perf_counter()
            manifest = continuity.preview(owner, wid, query, options)
            times.append((time.perf_counter() - tick) * 1000)
        prompt_bytes = len(render_prompt(query, manifest).encode())
        assert baseline_bytes > 512000
        assert prompt_bytes <= MAX_CONTEXT
        assert manifest["context_bytes"] == prompt_bytes
        assert manifest["references"] == options["references"]
        assert manifest["brief"]["goal"] == brief["goal"]
        assert manifest["selections"][0]["has_more"]
        assert manifest["omissions"] and len(store.items(owner, wid, "messages")) == before
        result = dict(status="PASS", provenance="Contractor deterministic SQLite/service measurement on assistant-authored synthetic inputs; not model evaluation",
            input=dict(files=12, original_source_bytes=sum(s["bytes"] for s in sources), synthetic_prior_protocol_bytes=baseline_bytes, historical_pairs=20),
            baseline=dict(path="retained AW-05 Store.context + 512000-byte Runtime threshold from checkpoint683aebc", history_bytes=baseline_bytes, inventory_files=len(legacy_files), inventory_outputs=len(legacy_outputs), would_exceed_old_history_guard=True),
            aw06=dict(selected_sources=1, prompt_bytes=prompt_bytes, limit_bytes=MAX_CONTEXT, excerpt_characters=len(manifest["selections"][0]["content"]), source_characters=manifest["selections"][0]["total_characters"], recent_pairs=len(manifest["recent_messages"]) // 2, omissions=manifest["omissions"], preview_samples=len(times), preview_ms_median=round(sorted(times)[len(times) // 2 - 1] / 2 + sorted(times)[len(times) // 2] / 2, 3), preview_ms_max=round(max(times), 3)),
            limitations=["Not a like-for-like semantic comparison: AW-05 full protocol and unselected resources are deliberately excluded.", "An excerpt is not complete reading; additional bounded tools/read budget are required.", "No claimed token/API cost saving, real-provider latency, human effort or direct-agent superiority.", "Twenty repeated warm previews on one small declared local dataset do not establish capacity or latency-tail guarantees."],
            real_ai_acceptance="NOT_MEASURED", elapsed_seconds=round(time.perf_counter() - started, 3), scratch_removed=True)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
