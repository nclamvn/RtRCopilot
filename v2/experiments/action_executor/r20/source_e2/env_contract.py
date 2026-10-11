"""Finite R20 stdlib environment/source gates. No product imports or workload."""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_path = HERE.parent / "r19/qualification.py"
if (
    hashlib.sha256(_path.read_bytes()).hexdigest()
    != "77df7d23f11daccd49ee755ddea9f49ca0e2fec48907a46f95465761abc48b11"
):
    raise ValueError("immutable R19 qualification drift")
_spec = importlib.util.spec_from_file_location("r20_prior_qualification", _path)
prior = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prior)
require = prior.require
digest = prior.digest
ROOT = prior.ROOT
AREA = "v2/experiments/action_executor/r20"
DATABASE = "rtr_tip054_r20_local_e1"
DSN = "postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/" + DATABASE
RAW = prior.RAW + "/r20_bootstrap_e1"
BINDING = "v2/experiments/action_executor/r19/source-binding-e5.json"
BINDING_SHA = "ebab6389b79674cd6a90110227ed02f9dce019c45b2ee299091ca337bebb21f4"
SEAL = "v2/experiments/action_executor/r19/main-evidence-binding.sha256"
SEAL_SHA = "f99638aa32e497220eb6240f9e9147184bf93d350014ab40801c49e4d7e771cd"
NAMES = tuple(
    sorted(
        (
            "test_exact_domain_environment_and_import_order",
            "test_missing_mismatch_and_unsafe_rejected_before_effects",
            "test_protected_source_raw_marker_and_drift_rejection",
            "test_exact_selection_records_and_zero_skip_conservation",
            "test_owned_fixture_budget_cap_and_cleanup_contract",
            "test_seed_only_scope_and_truthful_readiness_ledger",
        )
    )
)
GROUPS = {
    "offline": ["/work/r20/test_r20_offline.py::EnvironmentControls::" + name for name in NAMES],
    "negative": [
        "/work/r20/test_r20_bootstrap.py::"
        "test_missing_integration_import_capture_rejected_without_sql"
    ],
    "positive": [
        "/work/r20/test_r20_bootstrap.py::test_same_unchanged_dependency_chain_owned_seed_bootstrap"
    ],
}
FILES = (
    "env_contract.py",
    "test_r20_offline.py",
    "test_r20_bootstrap.py",
    "run-bootstrap-closure.sh",
    "manifest.json",
)
DOCS = (
    "vibecode_v2/R20_SCAN_REPORT.md",
    "vibecode_v2/TIP-054.4b-R20_DESIGN_PROPOSAL.md",
    "vibecode_v2/TIP-054.4b-R20_SYNTHETIC_FIXTURE_BOOTSTRAP_CLOSURE.md",
    "vibecode_v2/TIP-054.4b-R19_VERIFY_REPORT.md",
    "vibecode_v2/TIP-054.4b-R19_FINAL_RESULT_REVIEW.md",
)


def domain_environment(mapping, expected_dsn=DSN):
    require(expected_dsn == DSN, "only the admitted R20 domain")
    for key in ("POSTGRES_DSN", "INTEGRATION_DATABASE_DSN"):
        require(
            type(mapping.get(key)) is str and mapping[key] == expected_dsn,
            "missing/mismatched/unsafe " + key,
        )
    return expected_dsn


def environment(mapping):
    domain_environment(mapping)
    fixed = {
        "ACTION_EXECUTOR_ENABLED": "false",
        "RAG_EMBEDDING_PROVIDER": "offline",
        "RAG_PROVIDER_MODE": "local",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "LIMITS_RATE_RENDER_MAX": "30",
        "LIMITS_RATE_DEFAULT_READ_MAX": "120",
        "LIMITS_RATE_WINDOW_SECONDS": "60",
        "ACTION_EXECUTOR_OPERATION_TIMEOUT_SECONDS": "0.9",
    }
    require(all(mapping.get(key) == value for key, value in fixed.items()), "seed-only envelope")
    require("ACTION_WORKFLOW_DSN" not in mapping, "no engine identity/database")
    return DATABASE


def selectors(group="all"):
    require(group in {*GROUPS, "all"}, "finite selection")
    return sum(GROUPS.values(), []) if group == "all" else GROUPS[group]


def manifest(path=HERE / "manifest.json"):
    require(Path(path).stat().st_size <= 65536, "manifest cap")
    packet = prior.load_json(path)
    require(
        packet
        == {
            "schema": "R20-seed-only-v1",
            "groups": GROUPS,
            "database": DATABASE,
            "evidence": "/evidence/r19/r20_bootstrap_e1",
            "supervisor_stage": "pre",
            "child_seconds": 120,
            "cleanup_seconds": 10,
            "raw_bytes": 10485760,
            "executor": "OFF",
            "candidate": "NOT_READY",
            "tip054_5": "BLOCKED",
        },
        "exact finite manifest",
    )
    return packet


def preservation():
    require(digest(prior.r18.content(ROOT, BINDING)) == BINDING_SHA, "R19 source seal")
    prior.source(ROOT / BINDING)
    raw = prior.r18.content(ROOT, SEAL)
    require(digest(raw) == SEAL_SHA and len(raw.decode().splitlines()) == 220, "R19 raw seal")
    for line in raw.decode().splitlines():
        sha, path = line.split("  ", 1)
        require(digest(prior.r18.content(ROOT, path)) == sha, "R19 evidence drift: " + path)


def snapshot():
    preservation()
    paths = (*DOCS, BINDING, SEAL, *(AREA + "/" + name for name in FILES))
    return {
        "schema": "R20-linked-source-v1",
        "prior_source_sha256": BINDING_SHA,
        "prior_evidence_sha256": SEAL_SHA,
        "digests": {"product": prior.PRODUCT, "tests": prior.TESTS},
        "files": {path: digest(prior.r18.content(ROOT, path)) for path in sorted(paths)},
    }


def source(path):
    require(prior.load_json(path) == snapshot(), "source/preservation drift")
    require(
        Path(path).stat().st_size + sum((HERE / name).stat().st_size for name in FILES) <= 1048576,
        "source packet cap",
    )


def collection(path):
    require(
        prior.r18.collected(path) == [prior.r18.normalized_nodeid(node) for node in selectors()],
        "exact eight identities",
    )


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    if command == "snapshot":
        print(json.dumps(snapshot(), indent=2, sort_keys=True))
        sys.exit(0)
    manifest()
    if command == "environment":
        environment(os.environ)
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
        prior.cap(args[0], "pre")
    elif command == "child":
        prior.r18.child_record(*args)
    elif command == "drained":
        prior.r18.child_record(args[0], prior.load_json(args[0])["exit_code"])
    elif command == "review":
        require(
            digest(Path(args[0]).read_bytes()) == args[1]
            and "SOURCE ACCEPTED" in Path(args[0]).read_text(),
            "accepted pinned review",
        )
    else:
        raise ValueError("unknown seed-only gate")
    print("R20_PASS", command)
