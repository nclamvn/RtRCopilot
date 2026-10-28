"""Explicit offline-first AW-04 capture runner. No network activity on import/plan.

Only an operator-supplied private profile and authority matching a frozen corpus
can enter execute. The runner does not retry a failed capture or reset a ledger.
"""
import argparse
import asyncio
from dataclasses import replace
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import time
import tomllib

from .budget import CampaignBudget, MODEL, ENDPOINT
from .corpus import DEFAULT_CORPUS, load_corpus, manifest, verify_frozen, deterministic_rubric


# References identify reproducible probes, NOT a claim those tests passed in a
# particular run. Root's consolidated test evidence records actual execution.
OPERATION_PROOFS = {
    "AW04-07": ["tests/test_workspace.py::test_tool_scope_same_owner_and_deadline"],
    "AW04-08": ["tests/test_aw04_backend.py::test_provider_unknown_has_no_hidden_retry",
                "docs/agent-workspace/evidence/test_aw04_independent.py::test_provider_error_makes_exactly_one_synthetic_dispatch"],
    "AW04-09": ["tests/test_workspace_recovery.py::test_product_recovers_receipt_without_duplicate_publication",
                "tests/test_aw03_connections.py::test_pending_approval_restart_and_receipt_crash_recover_same_run"],
    "AW04-10": ["tests/test_aw03_connections.py::test_unknown_effect_reconciles_without_resend_after_cancel",
                "tests/test_aw03_connections.py::test_grant_read_then_native_approval_same_run_no_duplicate_effect"],
    "AW04-11": ["tests/test_aw03_connections.py::test_rejection_revocation_expiry_and_resource_change",
                "tests/test_workspace_state.py::test_memory_owner_workspace_boundaries_and_bounds"],
    "AW04-12": ["tests/test_workspace_state.py::test_memory_explicit_revision_and_delete_does_not_resurrect",
                "tests/test_aw03_connections.py::test_memory_delete_during_approval_cancels_consumers_and_future_body"],
}


def license_inventory():
    """Installed metadata, not legal clearance or a complete frontend SBOM."""
    root = Path(__file__).resolve().parents[3]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    entries = []
    for requirement in project["project"]["dependencies"]:
        name = requirement.split("==")[0].split("[")[0]
        try:
            d = importlib.metadata.distribution(name)
            license_text = d.metadata.get("License-Expression") or d.metadata.get("License")
            entries.append(dict(name=d.metadata["Name"], version=d.version,
                license_metadata=license_text[:300] if license_text else None,
                license_classifiers=[c for c in d.metadata.get_all("Classifier", []) if "License" in c]))
        except importlib.metadata.PackageNotFoundError:
            entries.append(dict(name=name, installed=False))
    web = root.parent / "web" / "package.json"
    return dict(scope="Standalone Workspace direct Python requirements; installed distribution metadata only",
                packages=entries, frontend_manifest=str(web.relative_to(root.parents[2])) if web.exists() else None,
                caveat="Web still inherits legacy package/dependency scope; this is not a full transitive SBOM, license audit, attribution bundle or legal clearance. Font license is retained under assets/LICENSE-NOTO.txt.")


def plan(data):
    return dict(status="DRY_RUN_NO_PROVIDER_CALLS", manifest=manifest(data),
        real_model_status="NOT_RUN", semantic_quality="NOT_MEASURED", human_acceptance="NOT_REVIEWED",
        arms=["workspace", "direct-tool-agent"], baseline="Plain PydanticAI agent with same scoped deterministic tool ports; no DBOS, Workspace UI or durable agent-history recovery",
        comparability_limits=["Both arms retain identical deterministic Store artifact/version safety; this is not a tool-less LLM.",
            "Direct baseline exposes pending approval instead of a native durable wait; effect/recovery advantages require separate operational probes, not fabricated semantic scores.",
            "Offline fixture assertions do not measure real provider quality, latency, invoice cost or human productivity.",
            "Twelve assistant-authored journeys and public holdout assignments are not a hidden independent benchmark."],
        split_limitation="Dev is mostly creation/happy-path and holdout mostly operational faults. Their averages are not a generalization comparison; report journey-specific results.",
        metrics={"first_text_seconds": None, "first_useful_output_seconds": None, "usable_artifact_seconds": None,
                 "active_human_minutes": None, "measured_user_actions": None, "invoice_usd": None},
        journeys=[dict(id=c["id"], split=c["split"], domain=c["domain"], journey=c["journey"],
                       kind="deterministic-control-only" if c["id"] in {"AW04-10", "AW04-11"} else "language-task-and-optional-control-probe",
                       model_needed=c["id"] not in {"AW04-10", "AW04-11"},
                       control_proof_refs=OPERATION_PROOFS.get(c["id"], []),
                       operational_status="NOT_RUN" if c.get("operation") else "NOT_APPLICABLE") for c in data["cases"]],
        licenses=license_inventory())


def _limits(settings):
    return dict(deadline_seconds=settings.deadline_seconds, request_limit=settings.request_limit,
                tool_limit=settings.tool_limit, token_limit=settings.token_limit, output_bytes_limit=settings.output_bytes_limit)


def _snapshot(store, owner, wid):
    artifacts, versions = [], []
    for item in store.items(owner, wid, "artifacts"):
        artifacts.append(store.artifact(owner, item["id"]))
        versions.extend(store.artifact(owner, item["id"], v["version"]) for v in store.versions(owner, item["id"]))
    return artifacts, versions


async def capture(data, frozen_digest, authority, profile, output, *, semantic_only=False):
    from agent_workspace.config import Settings
    from agent_workspace.provider_config import build_model, readiness
    from agent_workspace.runtime import Runtime
    from agent_workspace.store import Store
    from .baseline import DirectToolAgent
    if not semantic_only:
        raise ValueError("explicit_semantic_capture_only_required")
    if set(authority.get("case_ids", [])) != {c["id"] for c in data["cases"]}:
        raise ValueError("campaign_authority_case_set_mismatch")
    output = Path(output).resolve()
    if authority.get("ledger_path") != str(output / "budget.sqlite"):
        raise ValueError("campaign_authority_ledger_path_mismatch")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings = Settings(data_dir=output / "workspace", model=profile["model"],
                        api_key=profile["api_key"], base_url=profile["base_url"],
                        external_processing=profile["external_processing"],
                        fixture_tools_enabled=profile["fixture_tools_enabled"])
    _, reason = readiness(settings)
    if reason or settings.model != MODEL or settings.base_url != ENDPOINT:
        raise ValueError("campaign_profile_not_approved_configuration")
    budget = CampaignBudget(output / "budget.sqlite", authority, frozen_digest,
                            endpoint=settings.base_url, model=settings.model)
    # Refuse blind replay of a started campaign, including after a lost ACK/crash.
    # The marker is written before ANY provider call. Never delete it to rerun.
    descriptor = os.open(output / "capture.started", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(descriptor, frozen_digest.encode())
    os.fsync(descriptor)
    os.close(descriptor)
    settings.data_dir.mkdir(exist_ok=True)
    store = Store(settings.data_dir / "catalogue.sqlite")
    runtime = Runtime(settings, store, campaign_budget=budget)
    direct_clients = []
    evidence = plan(data) | dict(status="RUNNING", manifest_digest=frozen_digest,
        evidence_kind="authorized-provider-capture", real_model_status="IN_PROGRESS", hardware=dict(platform=platform.platform(), machine=platform.machine()),
        captures=[], user_actions_method="Automation actions are counted separately; human active minutes remain null.")
    evidence_path = output / "capture.json"

    def persist():
        evidence["budget"] = budget.snapshot()
        # This output is synthetic and contains model/tool results, never profile/key.
        raw = json.dumps(evidence, ensure_ascii=False, indent=2)
        tmp = output / "capture.json.pending"
        with open(tmp, "w") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, evidence_path)

    persist()
    try:
        await runtime.start()
        if not runtime.started:
            raise ValueError("campaign_runtime_unavailable")
        for case in data["cases"]:
            for arm in ("workspace", "direct-tool-agent"):
                item = dict(case_id=case["id"], arm=arm, split=case["split"], turns=[],
                    operational_status="NOT_RUN" if case.get("operation") else "NOT_APPLICABLE",
                    operational_note="Natural-language capture alone does not inject a process/transport/approval fault. Consult independent operational E2E evidence.",
                    active_human_minutes=None, measured_user_actions=None, first_useful_output_seconds=None,
                    semantic_status="NOT_REVIEWED", human_status="NOT_REVIEWED")
                item["control_proof_refs"] = OPERATION_PROOFS.get(case["id"], [])
                evidence["captures"].append(item)
                if case["id"] in {"AW04-10", "AW04-11"}:
                    item.update(kind="deterministic-control-only", model_not_needed=True,
                                status="NOT_RUN_IN_THIS_CAPTURE", semantic_status="NOT_APPLICABLE",
                                reason="Authority/cancellation controls are proved with code, not paid model behavior. See separately executed operational probes.")
                    persist()
                    continue
                settings_arm = settings if arm == "workspace" else replace(settings, data_dir=output / "direct-tool-agent")
                settings_arm.data_dir.mkdir(exist_ok=True)
                arm_store = store if arm == "workspace" else Store(settings_arm.data_dir / "catalogue.sqlite")
                _, owner = arm_store.session(None)
                wid = arm_store.workspaces(owner, case["domain"] + " " + case["id"])["id"]
                for name in case["sources"]:
                    arm_store.upload(owner, wid, name, data["sources"][name], "text/csv" if name.endswith(".csv") else "text/plain")
                direct = DirectToolAgent(settings_arm, arm_store, build_model(settings_arm), budget) if arm != "workspace" else None
                if direct:
                    direct_clients.append(direct.model.client)
                state = direct.memory if direct else runtime.workspace_state
                saved_memory = state.save_memory(owner, wid, case["memory"], "aw04-memory-save") if case.get("memory") else None
                for turn, prompt in enumerate(case["turns"]):
                    if turn == 1 and saved_memory:
                        state.delete_memory(owner, wid, saved_memory["id"], saved_memory["version"], "aw04-memory-forget")
                        if direct:
                            direct.forget_history()
                    row = arm_store.create_run(owner, wid, prompt, f"aw04-{case['id']}-{turn}", _limits(settings_arm))
                    rid = row["id"]
                    budget.bind_run(owner, rid, case["id"], arm)
                    started = time.perf_counter()
                    result = dict(run_id=rid, duration_seconds=None, first_text_seconds=None, first_artifact_seconds=None)
                    item["turns"].append(result)
                    persist()
                    if direct:
                        await direct.run(owner, rid)
                        result.update(direct.metrics)
                    else:
                        await runtime.dispatch_pending()
                        while arm_store.run(owner, rid)["state"] not in {"completed", "failed", "cancelled"}:
                            events = arm_store.events(owner, rid, 0)
                            if result["first_text_seconds"] is None and any(e["type"] == "message.delta" for e in events):
                                result["first_text_seconds"] = time.perf_counter() - started
                            if result["first_artifact_seconds"] is None and any(e["type"] == "artifact.published" for e in events):
                                result["first_artifact_seconds"] = time.perf_counter() - started
                            if time.perf_counter() - started > settings_arm.deadline_seconds + 5:
                                raise TimeoutError("capture_runtime_deadline")
                            await asyncio.sleep(.05)
                    row = arm_store.run(owner, rid)
                    result.update(state=row["state"], error=row.get("error"), usage=row.get("usage"), duration_seconds=time.perf_counter()-started)
                    artifacts, versions = _snapshot(arm_store, owner, wid)
                    messages = arm_store.items(owner, wid, "messages")
                    item.update(artifacts=artifacts, versions=versions, messages=messages)
                    texts = [m.get("content", "") for m in messages if m.get("role") == "assistant"]
                    item["rubric"] = deterministic_rubric(case, data["sources"], text="\n".join(texts), artifacts=artifacts, versions=versions, evidence_kind="real-provider")
                    persist()
                    if row["state"] != "completed" or budget.snapshot()["stopped"]:
                        raise ValueError("campaign_stopped_on_failure_no_retry")
        evidence["status"] = "CAPTURED_REVIEW_PENDING"
        evidence["real_model_status"] = "CAPTURED"
        evidence["semantic_quality"] = "NOT_REVIEWED"
    except BaseException as exc:
        evidence["status"] = "STOPPED_NO_RETRY"
        evidence["real_model_status"] = "ATTEMPTED_OUTCOME_UNCERTAIN" if budget.snapshot()["calls"] else "NOT_RUN"
        evidence["failure_class"] = type(exc).__name__
        # Do not write provider exception strings, request headers or secrets.
        raise
    finally:
        persist()
        await runtime.close()
        for client in direct_clients:
            await client.close()
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--frozen", type=Path, default=DEFAULT_CORPUS.with_name("manifest.json"))
    parser.add_argument("--execute", action="store_true", help="Requires explicit authority, secure profile and fresh output; no retry")
    parser.add_argument("--semantic-capture-only", action="store_true", help="Explicitly acknowledges control-only cases use separate local probes, not paid model calls")
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    data = load_corpus(args.corpus)
    frozen_digest = verify_frozen(data, args.frozen)
    if not args.execute:
        print(json.dumps(plan(data) | {"manifest_digest": frozen_digest}, indent=2))
        return 0
    if not all((args.authority, args.profile, args.output)):
        parser.error("--execute requires --authority, --profile and --output; no credentials are discovered")
    if not args.semantic_capture_only:
        parser.error("--execute requires --semantic-capture-only; this capture does not inject process/approval/transport faults")
    # Secure loader checks owner, mode0600 and no symlink. Read ONLY the explicit
    # newly configured Workspace profile; no env/legacy-key fallback here.
    from agent_workspace.provider_config import load_profile
    authority = json.loads(args.authority.read_text())
    profile = load_profile(args.profile)
    try:
        asyncio.run(capture(data, frozen_digest, authority, profile, args.output, semantic_only=True))
    except Exception as exc:
        # Provider error repr/tracebacks may contain request data. Failure details
        # are classified in the synthetic capture; no raw request escapes here.
        print(json.dumps({"status": "STOPPED_NO_RETRY", "failure_class": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
