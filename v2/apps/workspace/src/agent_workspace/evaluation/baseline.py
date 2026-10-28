"""Direct tool-enabled PydanticAI agent comparator, not a bare LLM.

It shares source parsing/tool catalogue/policy with Workspace, but has no DBOS,
UI, durable agent history or automatic restart recovery. The deterministic store
is retained for equal tool safety/version semantics, not as another executor.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
import time

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.usage import UsageLimits

from agent_workspace.connections import Connections
from agent_workspace.research import OfflineResearch
from agent_workspace.store import WorkspaceError
from agent_workspace.workspace_state import WorkspaceState


@dataclass
class Scope:
    owner: str
    run_id: str


class BudgetModel(WrapperModel):
    """Same monetary boundary without Workspace's DBOS dispatch wrapper."""
    def __init__(self, model, budget, scope):
        super().__init__(model)
        self.budget, self.scope = budget, scope

    async def request(self, messages, model_settings, model_request_parameters):
        ticket = await self.budget.reserve(self.scope, messages, model_settings, model_request_parameters)
        try:
            result = await self.wrapped.request(messages, model_settings, model_request_parameters)
            await self.budget.settle(ticket, result.usage.input_tokens, result.usage.output_tokens)
            return result
        except BaseException:
            await self.budget.unknown(ticket)
            raise

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        ticket = await self.budget.reserve(self.scope, messages, model_settings, model_request_parameters)
        try:
            async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as stream:
                yield stream
                usage = stream.usage
                await self.budget.settle(ticket, usage.input_tokens, usage.output_tokens)
        except BaseException:
            await self.budget.unknown(ticket)
            raise


class DirectToolAgent:
    def __init__(self, settings, store, model, budget=None):
        if not settings.test_mode and budget is None:
            raise WorkspaceError("direct_agent_campaign_budget_required")
        self.settings, self.store, self.model, self.budget = settings, store, model, budget
        self.memory = WorkspaceState(store)
        self.connections = Connections(store, settings.data_dir, settings.fixture_tools_enabled or settings.test_mode)
        self.research = OfflineResearch(settings.test_mode or settings.fixture_tools_enabled)
        self.history = []
        self.metrics = {}

    def tools(self):
        store, memory, connections, research = self.store, self.memory, self.connections, self.research

        async def read_file(ctx: RunContext[Scope], file_id: str, offset: int = 0, limit: int = 16000) -> dict:
            """Read extracted text by opaque ID. Follow next_offset while has_more; offsets are characters."""
            return store.read_file(ctx.deps.owner, ctx.deps.run_id, file_id, offset, limit)

        async def read_artifact(ctx: RunContext[Scope], artifact_id: str) -> dict:
            """Read the current draft and version within this run's workspace."""
            return store.read_artifact(ctx.deps.owner, ctx.deps.run_id, artifact_id)

        async def write_artifact(ctx: RunContext[Scope], title: str, filename: str, content: str,
                                 artifact_id: str | None = None, expected_version: int | None = None) -> dict:
            """Create a Markdown document (.md) or CSV table (.csv), or revise its exact version.

            Content must be complete, not a patch. Previous versions remain available.
            """
            result = store.publish(ctx.deps.owner, ctx.deps.run_id, ctx.tool_call_id or "missing", title, filename, content, artifact_id, expected_version)
            if self.metrics.get("first_artifact_seconds") is None:
                self.metrics["first_artifact_seconds"] = time.perf_counter() - self.started
            return result

        async def edit_artifact(ctx: RunContext[Scope], artifact_id: str, expected_version: int, old_text: str, new_text: str) -> dict:
            """Replace one exact unique text region, preserving all surrounding content and old versions."""
            return store.patch(ctx.deps.owner, ctx.deps.run_id, ctx.tool_call_id or "missing", artifact_id, expected_version, old_text, new_text)

        async def read_memory(ctx: RunContext[Scope]) -> dict:
            """Read current user-authored workspace memory. Never infer or write memory."""
            return memory.read_memories(ctx.deps.owner, ctx.deps.run_id)

        async def mcp_read_status(ctx: RunContext[Scope]) -> dict:
            """Read fixed synthetic MCP status using current workspace permission."""
            return await connections.read(ctx.deps.owner, ctx.deps.run_id)

        async def mcp_send_note(ctx: RunContext[Scope], note: str, artifact_id: str | None = None, expected_version: int | None = None) -> dict:
            """Propose a synthetic local outbox note; requires server approval. No real message/account exists."""
            approval = connections.prepare(ctx.deps.owner, ctx.deps.run_id, ctx.tool_call_id or "missing", note, artifact_id, expected_version)
            # Direct baseline returns the pending receipt to the human; it does not
            # auto-approve or add a second durable wait/executor to win the comparison.
            return {"pending_approval": True, "approval_id": approval["id"], "effect_sent": False}

        async def search_web(ctx: RunContext[Scope], query: str) -> dict:
            """Search explicit offline fixtures only, not the real internet. Results are fixture-labelled."""
            store.check(ctx.deps.owner, ctx.deps.run_id)
            return research.search(query)

        async def read_web(ctx: RunContext[Scope], source_id: str) -> dict:
            """Read a fixture search result by opaque ID. No URLs or arbitrary fetch exist."""
            store.check(ctx.deps.owner, ctx.deps.run_id)
            return research.read(source_id)

        async def import_web_source(ctx: RunContext[Scope], source_id: str) -> dict:
            """Import an offline fixture snapshot with URL, digest and as-of provenance into this workspace."""
            row = store.check(ctx.deps.owner, ctx.deps.run_id)
            return research.import_source(store, ctx.deps.owner, row["workspace_id"], source_id, run_id=ctx.deps.run_id)

        return [read_file, read_artifact, write_artifact, edit_artifact, search_web, read_web, import_web_source, read_memory, mcp_read_status, mcp_send_note]

    async def run(self, owner, run_id):
        # Backend exports this same instruction string; no tuned baseline prompt.
        from agent_workspace.runtime import AGENT_INSTRUCTIONS
        from agent_workspace.provider_config import MODEL_SETTINGS
        scope = Scope(owner, run_id)
        self.store.running(owner, run_id)
        self.memory.bind_run_epoch(owner, run_id)
        self.connections.bind_run(owner, run_id)
        row = self.store.check(owner, run_id)
        _, files, artifacts = self.store.context(owner, run_id)
        import json
        prompt = row["message"] + "\n\nWorkspace inventory (opaque IDs):\n" + json.dumps({"files": files, "artifacts": artifacts}, ensure_ascii=False)
        model = BudgetModel(self.model, self.budget, scope) if self.budget else self.model
        started = time.perf_counter()
        self.started = started
        self.metrics = dict(first_artifact_seconds=None, first_text_seconds=None,
                            first_useful_output_seconds=None)
        agent = Agent(model, deps_type=Scope, instructions=AGENT_INSTRUCTIONS, tools=self.tools(), retries=0,
                      model_settings=MODEL_SETTINGS)
        try:
            result = await agent.run(prompt, deps=scope, message_history=self.history,
                usage_limits=UsageLimits(request_limit=self.settings.request_limit, tool_calls_limit=self.settings.tool_limit, total_tokens_limit=self.settings.token_limit),
                timeout=self.settings.deadline_seconds)
            self.history = result.all_messages()
            self.store.finish(owner, run_id, "completed", content=result.output)
            self.metrics.update(duration_seconds=time.perf_counter()-started,
                                requests=result.usage.requests, tool_calls=result.usage.tool_calls,
                                input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens)
            return result.output
        except BaseException:
            self.store.finish(owner, run_id, "failed", error="direct_agent_execution_failed")
            raise

    def forget_history(self):
        """Explicit memory deletion clears ephemeral model history in this arm."""
        self.history = []
