#!/usr/bin/env python3
"""Offline schema/coverage verifier. Does NOT execute acceptance scenarios."""
import argparse
import copy
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED_FIELDS = {
    "id", "workflow", "milestone", "priority", "persona", "input",
    "preconditions", "steps", "expected_state", "business_oracles",
    "fault_injection", "metrics", "fixture_ids", "status", "title", "language",
    "coverage_tags", "risk_class", "authorization", "integration_boundary",
    "evaluation_layers",
}
REQUIRED_TAGS = {
    "happy", "noisy", "ambiguous", "chat_followup", "acl_revoked",
    "approval_input_changed", "schema_drift", "prompt_injection", "timeout",
    "transient_network", "crash_before_effect", "crash_after_effect_before_receipt",
    "duplicate_submission", "unknown_side_effect_budget_exhausted", "upload_error",
    "restart_partial_completion", "accessibility_mobile", "missing_freshness",
}
COMMON_WORKFLOW_TAGS = {"happy", "chat_followup", "acl_revoked", "schema_drift", "prompt_injection", "timeout"}
APPROVAL_BINDING = {"identity", "target", "action", "arguments_or_content_hash", "source_or_context_version", "expiry"}
LAYERS = {"deterministic_regression", "llm_usefulness_review", "human_confirmation"}
TIP054_NODES = {"W1":"054.1", "W2":"054.5", "W3":"054.5", "W4":"054.7", "W5":"054.7", "W6":"054.7", "W7":"054.6", "W8":"054.8"}


def validate(catalog, fixtures):
    """Return errors; never modify inputs or contact a service."""
    errors = []
    if catalog.get("classification") != "synthetic_design_evidence_only":
        errors.append("catalog must be synthetic design evidence")
    if catalog.get("catalog_status") != "planned_not_executed":
        errors.append("catalog status must not imply execution")
    if fixtures.get("classification") != "synthetic_only_no_company_facts" or fixtures.get("execution") != "none":
        errors.append("fixture boundary must be synthetic and unexecuted")
    fixture_list = fixtures.get("fixtures", [])
    fixture_ids = [f.get("id") for f in fixture_list]
    if len(fixture_ids) != len(set(fixture_ids)) or len(fixture_ids) != 8:
        errors.append("expected eight unique fixture bundles")
    workflows = catalog.get("workflows", [])
    workflow_ids = [w.get("id") for w in workflows]
    if set(workflow_ids) != {f"W{i}" for i in range(1, 9)} or len(workflow_ids) != 8:
        errors.append("expected exactly W1-W8")
    workflow_by_id = {w["id"]: w for w in workflows if "id" in w}
    for workflow, node in TIP054_NODES.items():
        if workflow_by_id.get(workflow, {}).get("proposed_tip054_node") != node:
            errors.append(f"{workflow}: proposed TIP-054 mapping missing or incorrect")
    scenarios = catalog.get("scenarios", [])
    if not 80 <= len(scenarios) <= 100:
        errors.append("scenario count must be 80-100")
    ids, inputs, titles, counts, tag_counts, languages = set(), set(), set(), Counter(), Counter(), Counter()
    workflow_tags = {w: set() for w in workflow_ids}
    for index, case in enumerate(scenarios):
        label = case.get("id", f"index-{index}")
        missing = REQUIRED_FIELDS - case.keys()
        if missing:
            errors.append(f"{label}: missing fields {sorted(missing)}")
            continue
        for field in REQUIRED_FIELDS:
            if case[field] is None or case[field] == "" or case[field] == [] or case[field] == {}:
                errors.append(f"{label}: empty required field {field}")
        for field, seen in (("id", ids), ("input", inputs), ("title", titles)):
            value = case[field]
            if value in seen:
                errors.append(f"{label}: duplicated {field}")
            seen.add(value)
        workflow = case["workflow"]
        if workflow not in workflow_by_id:
            errors.append(f"{label}: unknown workflow {workflow}")
        else:
            if case["milestone"] != workflow_by_id[workflow]["milestone"]:
                errors.append(f"{label}: milestone mismatch")
            if case["fixture_ids"] != [workflow_by_id[workflow]["fixture_id"]]:
                errors.append(f"{label}: workflow fixture mismatch")
        counts[workflow] += 1
        tags = case["coverage_tags"]
        if not isinstance(tags, list) or not set(tags) <= REQUIRED_TAGS:
            errors.append(f"{label}: invalid coverage tags")
            tags = []
        tag_counts.update(tags)
        workflow_tags.setdefault(workflow, set()).update(tags)
        if case["status"] != "planned_not_executed":
            errors.append(f"{label}: status must be planned_not_executed, never pass/fail")
        if case["language"] not in {"vi", "en"}:
            errors.append(f"{label}: language must be vi or en")
        languages[case["language"]] += 1
        if case["priority"] not in {"P0", "P1", "P2"}:
            errors.append(f"{label}: invalid priority")
        if not set(case["fixture_ids"]) <= set(fixture_ids):
            errors.append(f"{label}: unknown fixture")
        if len(case["steps"]) < 3 or any(not {"given", "when", "then"} <= s.keys() or not all(s.values()) for s in case["steps"]):
            errors.append(f"{label}: steps need concrete Given/When/Then")
        expected = case["expected_state"]
        if not {"state", "assertions", "effect_ledger"} <= expected.keys() or not expected.get("assertions"):
            errors.append(f"{label}: expected state lacks assertions/ledger")
        oracles = case["business_oracles"]
        if not {"regression", "llm_usefulness", "human_confirmation"} <= oracles.keys() or any(not oracles.get(k) for k in ("regression", "llm_usefulness", "human_confirmation")):
            errors.append(f"{label}: evaluation oracle layers missing")
        if set(case["evaluation_layers"]) != LAYERS:
            errors.append(f"{label}: evaluation layers must remain separate")
        fault = case["fault_injection"]
        if fault.get("execution") != "specification_only_not_injected" or fault.get("enabled") != (fault.get("kind") != "none"):
            errors.append(f"{label}: fault must be an unexecuted specification")
        metrics = case["metrics"]
        if metrics.get("mode") != "planned_targets_not_observed" or metrics.get("observed") is not None:
            errors.append(f"{label}: metrics must not claim observations")
        targets = metrics.get("targets", {})
        if any(targets.get(k) != 0 for k in ("unapproved_real_effects", "acl_leaks", "fabricated_current_facts")):
            errors.append(f"{label}: safety targets must be zero")
        if targets.get("max_logical_effects_per_action_key") != 1:
            errors.append(f"{label}: idempotency target missing")
        if "transient_network" in tags and targets.get("max_read_attempts") != 2:
            errors.append(f"{label}: transient reads need bounded retry target")
        auth = case["authorization"]
        if auth.get("acl") != "deterministic_recheck" or auth.get("intent") != "contextual_explicit_request" or auth.get("execution_authorized_here") is not False:
            errors.append(f"{label}: authorization boundary invalid")
        risk = case["risk_class"]
        if label == "EOS-W5-010" and risk != "R1":
            errors.append(f"{label}: explicitly saved internal brief is an R1 artifact")
        if risk in {"R0", "R1"}:
            if auth.get("approval_mode") != "not_required_for_requested_internal_action" or auth.get("approval_binding") != [] or targets.get("unnecessary_approval_prompts") != 0:
                errors.append(f"{label}: R0/requested internal R1 must remain low-friction")
        elif risk in {"R2", "R3"}:
            if auth.get("approval_mode") != "explicit_exact_action" or set(auth.get("approval_binding", [])) != APPROVAL_BINDING:
                errors.append(f"{label}: R2/R3 needs exact-action approval binding")
        else:
            errors.append(f"{label}: unknown risk class")
        if "approval_input_changed" in tags and risk not in {"R2", "R3"}:
            errors.append(f"{label}: changed approval must concern an R2/R3 effect")
        boundary = case["integration_boundary"]
        expected_kind = "needs_actual_connector" if workflow in {"W5", "W6"} else "needs_isolated_fake_server_harness" if workflow == "W7" else "needs_actual_product_integration"
        if boundary.get("fixture_scope") != "synthetic_design_evidence_only" or boundary.get("executed") is not False or not boundary.get("required_real_integration") or boundary.get("kind") != expected_kind:
            errors.append(f"{label}: explicit synthetic/real integration boundary missing")
    if set(counts) != set(workflow_ids) or any(counts[w] != 12 for w in workflow_ids):
        errors.append("expected 12 distinct scenarios per workflow")
    if set(languages) != {"vi", "en"}:
        errors.append("both Vietnamese and English inputs are required")
    missing_tags = REQUIRED_TAGS - tag_counts.keys()
    if missing_tags:
        errors.append(f"missing cross-coverage: {sorted(missing_tags)}")
    for workflow, tags in workflow_tags.items():
        if not COMMON_WORKFLOW_TAGS <= tags:
            errors.append(f"{workflow}: missing common workflow axes {sorted(COMMON_WORKFLOW_TAGS - tags)}")
    return errors


def self_test(catalog, fixtures):
    """Negative mutations test verifier rules, not product behavior."""
    mutations = [
        ("duplicate_id", lambda c, f: c["scenarios"][1].update(id=c["scenarios"][0]["id"])),
        ("missing_required_field", lambda c, f: c["scenarios"][0].pop("steps")),
        ("fake_pass_status", lambda c, f: c["scenarios"][0].update(status="pass")),
        ("fake_observed_metric", lambda c, f: c["scenarios"][0]["metrics"].update(observed={"latency_ms":1})),
        ("unknown_fixture", lambda c, f: c["scenarios"][0].update(fixture_ids=["NOT-A-FIXTURE"])),
        ("missing_workflow", lambda c, f: c["scenarios"].__setitem__(slice(0,12), [])),
        ("missing_coverage", lambda c, f: [s.update(coverage_tags=[t for t in s["coverage_tags"] if t != "accessibility_mobile"]) for s in c["scenarios"]]),
        ("r0_approval_friction", lambda c, f: c["scenarios"][0]["authorization"].update(approval_mode="explicit_exact_action")),
        ("r2_missing_binding", lambda c, f: next(s for s in c["scenarios"] if s["risk_class"] == "R2")["authorization"].update(approval_binding=[])),
        ("real_effect_authorized", lambda c, f: c["scenarios"][0]["authorization"].update(execution_authorized_here=True)),
        ("boundary_claims_executed", lambda c, f: c["scenarios"][0]["integration_boundary"].update(executed=True)),
        ("fixture_not_synthetic", lambda c, f: f.update(classification="real_company_data")),
    ]
    undetected = []
    for name, mutate in mutations:
        c, f = copy.deepcopy(catalog), copy.deepcopy(fixtures)
        mutate(c, f)
        if not validate(c, f):
            undetected.append(name)
    return len(mutations), undetected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="also check negative schema mutations, offline")
    args = parser.parse_args()
    try:
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        fixtures = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
        errors = validate(catalog, fixtures)
        mutation_count, undetected = self_test(catalog, fixtures) if args.self_test and not errors else (0, [])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps({"structural_verification":"error", "error":str(exc), "product_scenarios_executed":0}, ensure_ascii=False))
        return 1
    scenarios = catalog.get("scenarios", [])
    report = {
        "structural_verification":"valid" if not errors and not undetected else "invalid",
        "scenarios":len(scenarios), "fixtures":len(fixtures.get("fixtures", [])),
        "workflow_counts":dict(sorted(Counter(s.get("workflow") for s in scenarios).items())),
        "language_counts":dict(sorted(Counter(s.get("language") for s in scenarios).items())),
        "status_counts":dict(Counter(s.get("status") for s in scenarios)),
        "coverage_tag_counts":dict(sorted(Counter(t for s in scenarios for t in s.get("coverage_tags", [])).items())),
        "negative_verifier_mutations_checked":mutation_count, "undetected_mutations":undetected,
        "errors":errors, "product_scenarios_executed":0,
        "llm_usefulness_assessments":0, "human_confirmations":0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(errors or undetected))


if __name__ == "__main__":
    raise SystemExit(main())
