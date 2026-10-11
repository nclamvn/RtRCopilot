"""R21 finite adapter; immutable prior supervisor and raw reconstruction."""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_path = HERE.parent / "r20/env_contract.py"
if hashlib.sha256(_path.read_bytes()).hexdigest() != "b347e161a7c3a255c4bb2efeda3eff2bd6df5e0f12f72739d3d204a46418859c":
    raise ValueError("immutable R20 gate drift")
_spec = importlib.util.spec_from_file_location("r21_frozen_r20", _path)
old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(old)
prior = old.prior
require, digest, ROOT = prior.require, prior.digest, prior.ROOT
AREA = "v2/experiments/action_executor/r21"
DATABASES = ("rtr_tip054_r21_local_e1", "rtr_tip054_r21_engine_e1")
DSN = "postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/" + DATABASES[0]
WORKFLOW = "postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/" + DATABASES[1]
R20_BINDING = "v2/experiments/action_executor/r20/source-binding-e4.json"
R20_SHA = "9ee11e8257402c9038abcc8d07d5b4e3d9a09efa146a1e62b2f52702a65333ae"
SEAL = "v2/experiments/action_executor/r20/main-evidence-binding.sha256"
SEAL_SHA = "f8c3f11790ec4c624845e8151c0ee9beebb709b26d00acdef2f732ca011fb1af"
NAMES = tuple(sorted((
    "test_exact_caller_and_derived_envelopes_before_effects",
    "test_linked_source_history_and_one_use_admission",
    "test_original_rows_order_missing_and_quantile_conservation",
    "test_packet_summary_controls_oracle_and_corruption",
    "test_supervisor_dispatch_and_shell_ownership_failclosed",
    "test_fixture_db_closure_and_readiness_scope",
)))
GROUPS = {
    "offline": ["/work/r21/test_r21_offline.py::R21Controls::" + name for name in NAMES],
    "envelope": ["/work/r21/test_r21_envelope.py::test_captured_load_envelope_without_sql"],
}
FILES = ("qualification.py", "test_r21_offline.py", "test_r21_envelope.py", "run-http-qualification.sh", "contract.json")
EXTRAS = (
    "vibecode_v2/R21_SCAN_DESIGN.md",
    "vibecode_v2/TIP-054.4b-R21_MANDATORY_OFF_QUALIFICATION.md",
    "vibecode_v2/TIP-054.4b-R20_VERIFY_REPORT.md",
    "vibecode_v2/TIP-054.4b-R20_FINAL_RESULT_REVIEW.md",
    "v2/experiments/action_executor/r20/main-final-closure.json",
    "v2/experiments/action_executor/r20/main-bootstrap-closure.json",
    R20_BINDING, SEAL,
)
PROFILE = {
    "runner_cpus": 4, "runner_memory_gib": 4, "postgres_cpus": 2,
    "postgres_memory_mib": 4096, "postgres_data_tmpfs_gib": 3,
    "samples_per_operation_load": 100, "corpus": "one permitted signed synthetic SOT reference",
    "auth": "synthetic current subject dependency only; real API middleware/router/policy/domain paths",
    "rate_limits_enabled": True, "finite_test_window_render_quota": 5000,
    "finite_test_window_read_quota": 5000, "rate_window_seconds": 60,
    "no_worker": True, "no_provider": True,
    "recorder": "per_observation_host_backed_JSONL_append_flush_final_JSON",
}
LIMITS = (
    "Request service time includes pool contention while an acquired case slot is held; "
    "semaphore queue excluded. Declared finite synthetic rate quotas cover burst samples, "
    "not serving default30 writes/120reads per minute certification. Local ASGI not "
    "network/UI/mobile/OIDC latency, provider/render time or production load certification."
)
CONTROLS = {
    "observer": "off", "pool_size": 5, "max_overflow": 5, "pre_ping": True,
    "operation_timeout_seconds": 0.9, "old_load_helper": "/work/latency_probe.py",
    "provider": False, "worker": False,
    "authority_override": "Existing current synthetic subject dependency ONLY",
}


def caller(mapping):
    for key, value in (("POSTGRES_DSN", DSN), ("INTEGRATION_DATABASE_DSN", DSN), ("ACTION_WORKFLOW_DSN", WORKFLOW)):
        require(type(mapping.get(key)) is str and mapping[key] == value, "exact explicit caller " + key)


def environment(mapping, mode):
    require(mode in {"pre", "load"}, "finite envelope")
    for key in ("POSTGRES_DSN", "INTEGRATION_DATABASE_DSN"):
        require(mapping.get(key) == DSN, "captured domain " + key)
    fixed = {
        "ACTION_EXECUTOR_ENABLED": "true" if mode == "load" else "false",
        "RAG_EMBEDDING_PROVIDER": "offline", "RAG_PROVIDER_MODE": "local",
        "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
        "LIMITS_RATE_RENDER_MAX": "5000" if mode == "load" else "30",
        "LIMITS_RATE_DEFAULT_READ_MAX": "5000" if mode == "load" else "120",
        "LIMITS_RATE_WINDOW_SECONDS": "60", "ACTION_EXECUTOR_OPERATION_TIMEOUT_SECONDS": "0.9",
    }
    require(all(mapping.get(key) == value for key, value in fixed.items()), "exact " + mode + " envelope")
    require(mapping.get("ACTION_WORKFLOW_DSN") == WORKFLOW if mode == "load" else "ACTION_WORKFLOW_DSN" not in mapping, "workflow envelope")


def envelopes(mapping):
    caller(mapping)
    base = dict(mapping)
    base.pop("ACTION_WORKFLOW_DSN")
    base.update(ACTION_EXECUTOR_ENABLED="false", LIMITS_RATE_RENDER_MAX="30", LIMITS_RATE_DEFAULT_READ_MAX="120")
    environment(base, "pre")
    base.update(ACTION_EXECUTOR_ENABLED="true", ACTION_WORKFLOW_DSN=WORKFLOW, LIMITS_RATE_RENDER_MAX="5000", LIMITS_RATE_DEFAULT_READ_MAX="5000")
    environment(base, "load")


def selectors(group="all"):
    require(group in {*GROUPS, "all"}, "finite selection")
    return sum(GROUPS.values(), []) if group == "all" else GROUPS[group]


def wanted_contract():
    return {
        "schema": "R21-one-shot-OFF-v1", "http": prior.load_json(prior.HERE.parent / "r18/qualification.json")["http"],
        "databases": list(DATABASES), "groups": GROUPS,
        "roots": {"pre": "/evidence/r19/r21_pre_e1", "http": "/evidence/r19/r21_http_e1"},
        "product_digest": prior.PRODUCT, "test_digest": prior.TESTS,
        "candidate": "NOT_READY", "serving_executor": "OFF", "tip054_5": "BLOCKED",
        "source_packet_bytes": 1048576,
    }


def contract(path=HERE / "contract.json"):
    require(Path(path).stat().st_size <= 65536, "contract cap")
    result = prior.load_json(path)
    require(json.dumps(result, sort_keys=True) == json.dumps(wanted_contract(), sort_keys=True), "exact R21 contract")
    return result


def snapshot():
    require(digest(prior.r18.content(ROOT, R20_BINDING)) == R20_SHA, "R20 source seal")
    old.source(ROOT / R20_BINDING)
    seal = prior.r18.content(ROOT, SEAL)
    require(digest(seal) == SEAL_SHA and len(seal.decode().splitlines()) == 202, "R20 evidence seal")
    for line in seal.decode().splitlines():
        sha, path = line.split("  ", 1)
        require(digest(prior.r18.content(ROOT, path)) == sha, "protected R20 drift: " + path)
    paths = (*EXTRAS, *(AREA + "/" + name for name in FILES))
    return {
        "schema": "R21-linked-source-v1", "prior_source_sha256": R20_SHA,
        "prior_evidence_sha256": SEAL_SHA, "digests": {"product": prior.PRODUCT, "tests": prior.TESTS},
        "files": {path: digest(prior.r18.content(ROOT, path)) for path in sorted(paths)},
    }


def source(path):
    require(prior.load_json(path) == snapshot(), "source/preservation drift")
    require(Path(path).stat().st_size + sum((HERE / name).stat().st_size for name in FILES) <= 1048576, "source packet cap")


def collection(path):
    require(prior.r18.collected(path) == [prior.r18.normalized_nodeid(node) for node in selectors()], "exact seven IDs")


def marker(binding):
    return {
        "epoch": "r21_http_e1", "binding_sha256": digest(Path(binding).read_bytes()),
        "contract_sha256": digest((HERE / "contract.json").read_bytes()), "consumed": True,
        "meaning": "created immediately before spawn; unknown launch consumed",
    }


def mark(path, binding):
    with Path(path).open("x") as stream:
        json.dump(marker(binding), stream, sort_keys=True)
        stream.flush()


def exact(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def journal_rows(root):
    raw = (Path(root) / "run/samples.jsonl").read_bytes()
    require(not raw or raw.endswith(b"\n"), "partial journal; no repair")
    return [json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))) for line in raw.decode().splitlines()]


def packet(root):
    root = Path(root)
    require(exact(prior.load_json(root.parent / "r21-campaign-launch.json"), marker(root / "binding.json")), "new consumed campaign/source identity")
    require((root / "contract.json").read_bytes() == (HERE / "contract.json").read_bytes(), "retained contract identity")
    rows = journal_rows(root)
    require(exact(rows, prior.load_json(root / "run/samples.json")), "JSON/JSONL exact list equality")
    result = prior.reconstruct(rows)
    summary = prior.load_json(root / "run/latency-summary.json")
    require(exact(summary, {"status": result["status"], "cells": result["cells"], "profile": PROFILE, "limits": LIMITS}), "full original summary/profile/oracle agreement")
    require(exact(prior.load_json(root / "run/r-controls.json"), CONTROLS), "original OFF controls")
    process = prior.r18.child_record(root / "load.process.json", prior.load_json(root / "load.process.json")["exit_code"])
    code = 0 if result["status"] == "PASS" else 1
    require(type(process["exit_code"]) is int and type(process["original_exit_code"]) is int, "typed original driver exit")
    require(process["reason"] == "completed" and process["exit_code"] == process["original_exit_code"] == code, "completed original driver/oracle exit")
    result.update(integrity="PASS", oracle_complete_pass=code == 0)
    return result


def analyze(root):
    try:
        return packet(root)
    except (ValueError, KeyError, OSError, TypeError, UnicodeError) as error:
        # Retain identity/missing counts for valid partial rows; never salvage a PASS.
        result = {"requested": 1600}
        try:
            result.update(prior.reconstruct(journal_rows(root)))
            result["population_origin"] = "valid whole journal only; packet integrity still FAIL"
        except (ValueError, KeyError, OSError, TypeError, UnicodeError):
            pass
        result.update(integrity="FAIL", status="FAIL", error_type=type(error).__name__, error=str(error))
        return result


def passing_pre(root, binding):
    root = Path(root)
    require((root / "binding.json").read_bytes() == Path(binding).read_bytes(), "same binding PRE")
    require((root / "contract.json").read_bytes() == (HERE / "contract.json").read_bytes(), "same PRE contract")
    collection(root / "collection.stdout.txt")
    codes = (root / "returncodes.txt").read_text().splitlines()
    for label in ("syntax", "pins", "ruff", "format", "collection", "inventory", "offline", "offline-xml", "envelope", "envelope-xml"):
        require(codes.count(label + " 0") == 1, "passing PRE child " + label)
        require(prior.r18.child_record(root / f"{label}.process.json", 0)["reason"] == "completed", "PRE completed")
    require(codes.count("stage pre exit 0") == 1, "passing PRE stage")
    for group in GROUPS:
        prior.r18.junit(root / (group + ".xml"), selectors(group))
    prior.cap(root, "pre")


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    if command == "snapshot":
        print(json.dumps(snapshot(), indent=2, sort_keys=True))
        sys.exit(0)
    contract()
    if command == "environment":
        envelopes(os.environ)
    elif command == "source":
        source(args[0])
    elif command == "selectors":
        print("\n".join(selectors(*args)))
        sys.exit(0)
    elif command == "collection":
        collection(*args)
    elif command == "xml":
        prior.r18.junit(args[0], selectors(args[1]))
    elif command == "fixture":
        prior.r18.fixture(*args)
    elif command == "cap":
        print(prior.cap(*args))
    elif command == "child":
        prior.r18.child_record(*args)
    elif command == "drained":
        prior.r18.child_record(args[0], prior.load_json(args[0])["exit_code"])
    elif command == "prior":
        passing_pre(*args)
    elif command == "mark":
        mark(*args)
    elif command == "analyze":
        result = analyze(args[0])
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["integrity"] == result["status"] == "PASS" else 1)
    elif command == "review":
        require(digest(Path(args[0]).read_bytes()) == args[1] and "SOURCE ACCEPTED" in Path(args[0]).read_text(), "accepted pinned review")
    else:
        raise ValueError("unknown finite gate")
    print("R21_PASS", command)
