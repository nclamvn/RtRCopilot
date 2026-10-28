"""Offline contract/budget tests. No live provider and no semantic certification."""
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time

from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, TextPart
import pytest

from agent_workspace.config import Settings
from agent_workspace.store import Store, WorkspaceError
from agent_workspace.evaluation.budget import CampaignBudget, ENDPOINT, MODEL, digest
from agent_workspace.evaluation.corpus import load_corpus, manifest, verify_frozen, deterministic_rubric, DEFAULT_CORPUS
from agent_workspace.evaluation.cli import main, plan
from agent_workspace.evaluation.baseline import DirectToolAgent, Scope


def authority(**overrides):
    return dict(approved=True, data_scope="synthetic-public-non-rtr", endpoint=ENDPOINT, model=MODEL,
                manifest_digest="a" * 64, case_ids=["AW04-01"], concurrency=1,
                limit_usd=10, max_calls=100, max_input_tokens=100000, max_output_tokens=2048,
                repair_rounds=0, approval_reference="SYNTHETIC TEST AUTHORITY, not human approval",
                expires_at=time.time()+3600) | overrides


def setup_budget(tmp_path, **overrides):
    a = authority(**overrides)
    b = CampaignBudget(tmp_path / "budget.sqlite", a, "a" * 64)
    b.bind_run("synthetic-owner", "run-one", "AW04-01", "workspace")
    b.bind_run("synthetic-owner", "run-two", "AW04-01", "direct-tool-agent")
    return b, a


def request():
    return [ModelRequest(parts=[UserPromptPart("SYNTHETIC sensitive body never written to ledger")])], {"max_tokens": 2048}, ModelRequestParameters()


async def test_shared_budget_serial_persistent_and_private(tmp_path):
    b, a = setup_budget(tmp_path)
    t = await b.reserve(Scope("synthetic-owner", "run-one"), *request())
    with pytest.raises(WorkspaceError, match="uncertain_or_concurrent"):
        await b.reserve(Scope("synthetic-owner", "run-two"), *request())
    await b.settle(t, 1000, 100)
    restarted = CampaignBudget(b.path, a, "a" * 64)
    t2 = await restarted.reserve(Scope("synthetic-owner", "run-two"), *request())
    await restarted.settle(t2, 500, 50)
    snap = restarted.snapshot()
    assert snap["calls"] == 2 and snap["conservative_charged_or_reserved_usd"] == .009
    assert snap["invoice_usd"] is None
    assert b"sensitive body" not in b.path.read_bytes()
    assert b.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("unknown", [False, True])
async def test_crash_or_unknown_never_refund_or_replay(tmp_path, unknown):
    b, a = setup_budget(tmp_path)
    t = await b.reserve(Scope("synthetic-owner", "run-one"), *request())
    before = b.snapshot()["conservative_charged_or_reserved_usd"]
    if unknown:
        await b.unknown(t)
    restarted = CampaignBudget(b.path, a, "a" * 64)
    with pytest.raises(WorkspaceError):
        await restarted.reserve(Scope("synthetic-owner", "run-two"), *request())
    assert restarted.snapshot()["conservative_charged_or_reserved_usd"] == before
    assert restarted.snapshot()["calls"] == 1


async def test_total_call_and_dollar_caps_not_per_arm(tmp_path):
    b, _ = setup_budget(tmp_path, max_calls=1)
    t = await b.reserve(Scope("synthetic-owner", "run-one"), *request())
    await b.settle(t, 100, 100)
    with pytest.raises(WorkspaceError, match="budget_exhausted"):
        await b.reserve(Scope("synthetic-owner", "run-two"), *request())
    c, _ = setup_budget(tmp_path / "low-cap", limit_usd=.001)
    with pytest.raises(WorkspaceError, match="budget_exhausted"):
        await c.reserve(Scope("synthetic-owner", "run-one"), *request())
    assert c.snapshot()["calls"] == 0


async def test_usage_overrun_persistently_stops_without_free_refund(tmp_path):
    b, a = setup_budget(tmp_path)
    t = await b.reserve(Scope("synthetic-owner", "run-one"), *request())
    with pytest.raises(WorkspaceError, match="usage_unbounded"):
        await b.settle(t, 999999, 999999)
    restarted = CampaignBudget(b.path, a, "a" * 64)
    assert restarted.snapshot()["stopped"] == "usage_exceeded_reservation"
    assert restarted.snapshot()["dispatches"][0]["status"] == "unknown"
    with pytest.raises(WorkspaceError, match="stopped"):
        await restarted.reserve(Scope("synthetic-owner", "run-two"), *request())


async def test_authority_scope_and_bounded_requests_fail_before_dispatch(tmp_path):
    for override in [dict(approved=False), dict(limit_usd=11), dict(concurrency=2), dict(expires_at=time.time()-1), dict(model="openai:other"), dict(data_scope="legacy")]:
        with pytest.raises(WorkspaceError):
            CampaignBudget(tmp_path / "deny.sqlite", authority(**override), "a"*64)
    b, a = setup_budget(tmp_path)
    with pytest.raises(WorkspaceError, match="binding_changed"):
        CampaignBudget(b.path, a | {"limit_usd": 9}, "a"*64)
    with pytest.raises(WorkspaceError, match="out_of_scope"):
        b.bind_run("o", "r", "OTHER", "workspace")
    with pytest.raises(WorkspaceError, match="not_bound"):
        await b.reserve(Scope("other", "run-one"), *request())
    msgs, _, params = request()
    for settings in [{}, {"max_tokens": 2049}, {"max_tokens": 2048, "openai_service_tier": "fast"}, {"max_tokens": 2048, "extra_body": {}}]:
        with pytest.raises(WorkspaceError):
            await b.reserve(Scope("synthetic-owner", "run-one"), msgs, settings, params)
    assert b.snapshot()["calls"] == 0


def test_frozen_corpus_and_localized_rubrics_are_not_semantic_certification(tmp_path):
    data = load_corpus()
    assert len(data["cases"]) == 12
    assert {c["domain"] for c in data["cases"]} == {"community-garden", "makerspace"}
    assert len(data["sources"]["harbor-handbook.txt"]) > 16000
    frozen = DEFAULT_CORPUS.with_name("manifest.json")
    assert len(verify_frozen(data, frozen)) == 64
    changed = dict(data, campaign="changed")
    with pytest.raises(ValueError, match="frozen_manifest_mismatch"):
        verify_frozen(changed, frozen)
    case = data["cases"][3]
    result = deterministic_rubric(case, data["sources"], artifacts=[dict(filename="costs.csv", content=data["sources"]["maker-costs.csv"])])
    assert result["contract_status"] == "PASS"
    assert result["semantic_status"] == "NOT_MEASURED"
    assert result["human_status"] == "NOT_REVIEWED"
    edited = data["cases"][4]
    old = "Start\nRegistration closes 2026-11-07.\nKeep this byte."
    new = old.replace("2026-11-07", "2026-11-09")
    result = deterministic_rubric(edited, data["sources"], artifacts=[dict(filename="event.md", content=new)], versions=[dict(content=old), dict(content=new)], evidence_kind="real-provider")
    assert result["contract_status"] == "PASS" and result["semantic_status"] == "NOT_REVIEWED"
    result = deterministic_rubric(data["cases"][0], data["sources"], text="Capacity24 fallback18 cap1850.00")
    assert result["contract_status"] == "REVIEW_REQUIRED"  # locale is not false critical failure


def test_cli_defaults_dry_run_no_credentials_or_provider_calls(capsys, monkeypatch):
    # A hostile key/profile environment must remain irrelevant to dry-run.
    monkeypatch.setenv("WORKSPACE_CONFIG", "/does-not-exist-legacy-secret")
    monkeypatch.setenv("WORKSPACE_API_KEY", "DO_NOT_DISCOVER")
    assert main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "DRY_RUN_NO_PROVIDER_CALLS"
    assert output["semantic_quality"] == "NOT_MEASURED"
    assert "DO_NOT_DISCOVER" not in json.dumps(output)
    with pytest.raises(SystemExit):
        main(["--execute"])


async def test_direct_comparator_uses_real_tools_but_function_model_is_not_quality(tmp_path):
    """One tool-enabled mock probe proves interface wiring, not task semantics."""
    async def response(messages, info):
        from pydantic_ai.messages import ToolCallPart, ToolReturnPart
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[TextPart("SIMULATED completed read; not semantic evidence")])
        tool = next(t for t in info.function_tools if t.name == "read_memory")
        return ModelResponse(parts=[ToolCallPart(tool.name, {}, "mock-tool")])
    s = Store(tmp_path / "catalogue.sqlite")
    _, owner = s.session(None)
    wid = s.workspaces(owner, "Synthetic comparator")["id"]
    settings = Settings(tmp_path, test_mode=True)
    baseline = DirectToolAgent(settings, s, FunctionModel(response))
    baseline.memory.save_memory(owner, wid, "Synthetic preference: short summaries", "memory-create")
    run = s.create_run(owner, wid, "Read my saved preference", "baseline-mock", dict(deadline_seconds=30, request_limit=8, tool_limit=16, token_limit=32000, output_bytes_limit=256000))
    await baseline.run(owner, run["id"])
    assert s.run(owner, run["id"])["state"] == "completed"
    assert baseline.metrics["requests"] == 2 and baseline.metrics["tool_calls"] == 1
    assert baseline.metrics["first_useful_output_seconds"] is None
    baseline.forget_history()
    assert baseline.history == []
    with pytest.raises(WorkspaceError, match="budget_required"):
        DirectToolAgent(Settings(tmp_path, test_mode=False), s, FunctionModel(response))


async def test_actual_streamed_model_usage_property_settles_one_ticket(tmp_path):
    from pydantic_ai import Agent
    from agent_workspace.evaluation.baseline import BudgetModel
    async def stream(messages, info):
        yield "Synthetic "
        yield "stream only"
    b, _ = setup_budget(tmp_path)
    model = BudgetModel(FunctionModel(stream_function=stream), b, Scope("synthetic-owner", "run-one"))
    async with Agent(model, model_settings={"max_tokens": 2048}, retries=0).run_stream("Synthetic public data") as result:
        assert await result.get_output() == "Synthetic stream only"
    snapshot = b.snapshot()
    assert snapshot["calls"] == 1 and snapshot["dispatches"][0]["status"] == "settled"


def test_authority_ledger_path_cannot_silently_create_fresh_cap(tmp_path):
    first = tmp_path / "one.sqlite"
    a = authority(ledger_path=str(first.resolve()))
    CampaignBudget(first, a, "a" * 64)
    with pytest.raises(WorkspaceError, match="ledger_path_mismatch"):
        CampaignBudget(tmp_path / "two.sqlite", a, "a" * 64)


async def test_real_capture_requires_explicit_semantic_scope_and_ledger_before_any_provider(tmp_path, monkeypatch):
    from agent_workspace.evaluation.cli import capture
    def forbidden(*args, **kwargs):
        pytest.fail("provider construction before authority preflight")
    monkeypatch.setattr("agent_workspace.provider_config.build_model", forbidden)
    data = load_corpus()
    a = authority(case_ids=[c["id"] for c in data["cases"]])
    with pytest.raises(ValueError, match="semantic_capture_only"):
        await capture(data, "a" * 64, a, {}, tmp_path / "capture")
    with pytest.raises(ValueError, match="ledger_path_mismatch"):
        await capture(data, "a" * 64, a, {}, tmp_path / "capture", semantic_only=True)
    assert not (tmp_path / "capture").exists()
