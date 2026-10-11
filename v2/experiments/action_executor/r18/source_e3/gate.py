"""Finite R18 source, inventory and evidence gates; no product or load runner."""

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

BACKEND = "v2/apps/backend"
AREA = "v2/experiments/action_executor/r18"
FIXTURE = "tip054-4b-full-20261007-r5qa1"
RAW = f"v2/experiments/action_executor/raw/{FIXTURE}"
OLD = f"{RAW}/r15/pre_e1/collection.stdout.txt"
OLD_SHA = "3e1690f7fd8cf81a0c219223bea94e46b5e575e65bee764563cbf3d5bd250f70"
R17_BINDING = "v2/experiments/action_executor/r17/source-binding-e5.sha256"
R17_SHA = "b6133d5bb71b5b64a3927d0e718ff5af22c8670782da17e6977acc98c519715e"
HISTORICAL = "4a0bb4921ed0e310e6064070d945aab16837ab3de5ac525eb14bc15f8fc88708"
HERE = Path(__file__).resolve().parent
ROOT = Path("/workspace") if Path("/work/r18") == HERE else HERE.parents[3]
PYTEST_ROOT = Path("/workspace/v2/apps/backend")
DATABASES = ("rtr_tip054_r15_local_e1", "rtr_tip054_r18_local_e1")
PURE_ADD = ["tests/test_action_execution_unit.py::test_isolated_configuration_and_output_schema"]
LEASE_NAMES = (
    "test_old_connection_same_physical_final_inert_same_and_child",
    "test_old_sessions_started_unstarted_tx_same_physical_final_inert",
    "test_source_revision_after_commit_denies_fresh_final_disclosure",
    "test_final_source_fence_role_expiry_denies_after_actual_wait",
    "test_postcommit_evidence_lifecycle_change_denies_final",
    "test_repeated_cancel_transition_joins_cleanup_no_final",
)
CONTRACT_NAMES = (
    "test_real_http_read_domain_and_no_public_effect_accounting",
    "test_parent_budget_reservation_is_atomic_and_idempotent",
    "test_private_reads_and_redacted_receipts_do_not_leak_payload",
    "test_denied_purpose_unknown_scope_and_unpriced_work_fail_admission",
    "test_small_pool_concurrent_duplicate_plan_does_not_nest_checkout",
    "test_maintenance_and_admin_drift_block_mutations",
)
SQL_ADD = [f"tests/test_action_two_lease_review_integration.py::{name}" for name in LEASE_NAMES]
SQL_ADD += [f"tests/test_action_contracts_integration.py::{name}" for name in CONTRACT_NAMES]
CONTROL_NAMES = tuple(
    sorted(
        (
            "test_manifest_schema_caps_and_malformed_rejection",
            "test_source_paths_hashes_scope_and_drift_rejection",
            "test_exact_old_plus_added_selection_and_collection",
            "test_exact_xml_identity_and_zero_skip_conservation",
            "test_owned_stage_epoch_and_process_group_contract",
            "test_pending_ledger_and_immutable_http_contract",
        )
    )
)
OFFLINE = [f"/work/r18/test_r18_offline.py::AdmissionControls::{name}" for name in CONTROL_NAMES]
CAPS = {
    "manifest_bytes": 65536,
    "source_packet_bytes": 1048576,
    "pre_evidence_bytes": 10485760,
    "sql_evidence_bytes": 20971520,
    "child_seconds": 120,
    "kill_grace_seconds": 10,
    "host_free_kib": 20971520,
    "pg_free_kib": 524288,
}
HTTP = {
    "status": "pending_separate_admission",
    "allowance_consumed": 0,
    "observer": "OFF_not_R17_M",
    "profiles": [1, 10, 25, 50],
    "cases_per_profile": 100,
    "operations": ["admission", "submit", "status", "cancel"],
    "cells": 16,
    "requested_observations": 1600,
    "samples_per_cell": 100,
    "errors_per_cell": 0,
    "quantile": "nearest_rank_ceiling_n_times_q",
    "p95_admission_ms": 500,
    "p95_other_ms": 1000,
    "pool_size": 5,
    "max_overflow": 5,
    "pre_ping": True,
    "route_timeout_seconds": 0.9,
    "synthetic_rate_quotas": 5000,
    "seconds": 190,
    "kill_grace_seconds": 10,
    "raw_bytes": 10485760,
    "synthetic_executor_flag": True,
    "serving_executor_flag": False,
    "worker_native_provider": False,
    "missing_downstream": "explicit_missing_not_invented_latency",
    "historical_r12_off": "FAIL_preserved_not_current_source_proof",
}
LEDGER = {
    "EXE-001": "partial_config_only_native_DBOS_admission_pending",
    "EXE-002": "partial_submit_domain_native_dispatch_restart_pending",
    "EXE-003": "partial_current_authority_domain_durable_restart_pending",
    "EXE-004": "pending_real_worker_process_death_and_recovery",
    "EXE-005": "partial_handle_fencing_native_competing_owner_effects_pending",
    "EXE-006": "partial_domain_cancel_cleanup_native_remaining_work_pending",
    "EXE-007": "partial_domain_budget_immutability_native_retry_recovery_pending",
    "EXE-008": "partial_contract_privacy_real_R0_R1_source_effects_pending",
    "EXE-009": "pending_current_source_mandatory_observer_OFF_HTTP",
    "EXE-010": "pending_populated_migration_and_joint_restore_native_resume",
    "EXE-011": "partial_finite_regressions_broad_backend_type_build_package_pending",
}
PRODUCT_EXTRAS = (
    "v2/.env.example",
    f"{BACKEND}/pyproject.toml",
    f"{BACKEND}/uv.lock",
    f"{BACKEND}/alembic.ini",
)
HELPERS = (
    "v2/experiments/action_executor/latency_probe.py",
    "v2/experiments/action_executor/r/run_phase_baseline.py",
    "v2/experiments/action_executor/r12/preflight_e1/fixture-preflight.json",
    "vibecode_v2/TIP-054.4b-R12_VERIFY_REPORT.md",
    "vibecode_v2/TIP-054.4b-R17_VERIFY_REPORT.md",
    "v2/experiments/action_executor/r17/main-final-closure.json",
    R17_BINDING,
    OLD,
    "vibecode_v2/R18_SCAN_REPORT.md",
    "vibecode_v2/TIP-054.4b-R18_CANDIDATE_QUALIFICATION_PREPARATION.md",
    f"{AREA}/host_e1.json",
    f"{AREA}/style_e1.json",
    f"{AREA}/source-binding-e1.json",
    f"{AREA}/host_e2.json",
    f"{AREA}/style_e2.json",
    f"{AREA}/source-binding-e2.json",
    f"{AREA}/repair_e3_admission.json",
    f"{AREA}/host_e3_before_format.json",
)
SOURCE_NAMES = (
    "gate.py",
    "bounded.py",
    "test_r18_offline.py",
    "run-local-qualification.sh",
    "qualification.json",
    "COVERAGE_LEDGER.md",
)
RECIPE = "sha256(UTF8 sorted 'content_sha256  repo_relative_path\\n'); no Git metadata"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, relative):
    path = PurePosixPath(relative)
    require(isinstance(relative, str) and path.as_posix() == relative, "noncanonical path")
    require(not path.is_absolute() and ".." not in path.parts and path.parts, "unsafe path")
    parts = path.parts
    if root == Path("/workspace"):
        if relative.startswith(RAW + "/"):
            root = Path("/evidence")
            parts = parts[5:]
        elif relative.startswith("v2/experiments/action_executor/"):
            root = Path("/work")
            parts = parts[3:]
    item = root
    for part in parts:
        item = item / part
        require(not item.is_symlink(), "symlink source or parent")
    require(item.is_file(), "missing/nonfile source")
    return item


def content(root, relative):
    return safe_path(root, relative).read_bytes()


def normalized_nodeid(nodeid):
    path, *selectors = nodeid.split("::")
    source = Path(path)
    if path and source.is_absolute():
        path = (
            source.relative_to(PYTEST_ROOT).as_posix() if source.is_relative_to(PYTEST_ROOT) else ""
        )
    return "::".join([path, *selectors])


def collected(path):
    lines = Path(path).read_text().splitlines()
    return [line.strip() for line in lines if "::" in line and ": " not in line]


def expected_groups(root=ROOT):
    raw = content(root, OLD)
    require(digest(raw) == OLD_SHA, "old inventory pin")
    old = [line.strip() for line in raw.decode().splitlines() if "::" in line and ": " not in line]
    require(len(old) == len(set(old)) == 33, "old inventory count")
    require(
        old[-1] == "::test_real_r0_admission_and_submit_keep_queries_leases_and_durable_outputs",
        "old external identity",
    )
    selectors = old[:32] + ["/work/r12/test_minimal_observer_builder_integration.py" + old[-1]]
    return {
        "pure": selectors[:16] + PURE_ADD,
        "old_sql": selectors[16:],
        "new_sql": SQL_ADD,
        "offline": OFFLINE,
    }


def manifest(path, root=ROOT):
    raw = Path(path).read_bytes()
    require(len(raw) <= CAPS["manifest_bytes"], "manifest cap")
    packet = json.loads(raw)
    require(
        set(packet) == {"schema", "groups", "caps", "ledger", "http", "scope", "fixture"},
        "manifest schema keys",
    )
    require(packet["schema"] == "R18-finite-v1", "schema version")
    require(packet["groups"] == expected_groups(root), "exact fixed selectors")
    ids = [normalized_nodeid(node) for group in packet["groups"].values() for node in group]
    require(len(ids) == len(set(ids)) == 52, "unique fixed 52")
    require(packet["caps"] == CAPS and packet["http"] == HTTP, "finite immutable budgets")
    require(packet["ledger"] == LEDGER, "honest pending EXE ledger")
    require(
        packet["scope"]
        == {
            "stages": ["pre", "sql"],
            "serving_executor": "OFF",
            "tip054_5": "BLOCKED",
            "candidate": "NOT_READY",
        },
        "scope",
    )
    require(
        packet["fixture"]
        == {"name": FIXTURE, "databases": list(DATABASES), "migration": "0019_action_executor"},
        "fixture",
    )
    return packet


def file_scope(root, directory):
    base = root / directory
    require(base.is_dir() and not base.is_symlink(), "source root")
    ignored = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    paths = []
    for path in base.rglob("*"):
        relative = path.relative_to(root)
        if ignored.intersection(relative.parts) or path.suffix == ".pyc":
            continue
        require(not path.is_symlink(), "symlink in scope")
        if path.is_file():
            paths.append(relative.as_posix())
    return sorted(paths)


def inventories(root):
    product = file_scope(root, f"{BACKEND}/src") + file_scope(root, f"{BACKEND}/migrations")
    product += list(PRODUCT_EXTRAS)
    tests = file_scope(root, f"{BACKEND}/tests")
    prior = content(root, R17_BINDING)
    require(digest(prior) == R17_SHA, "R17 binding pin")
    protected = {}
    for line in prior.decode().splitlines():
        sha, path = line.split("  ", 1)
        require(digest(content(root, path)) == sha, "selected prior pin changed: " + path)
        protected[path] = sha
    required = set(product + tests + list(HELPERS) + [f"{AREA}/{name}" for name in SOURCE_NAMES])
    required.update(
        f"{AREA}/source_e1/{name}" for name in (*SOURCE_NAMES, "source-binding-e1.json")
    )
    required.update(
        f"{AREA}/source_e2/{name}"
        for name in (*SOURCE_NAMES, "source-binding-e2.json", "BUILDER_COMPLETION_REPORT.md")
    )
    required.update(protected)
    hashes = {path: digest(content(root, path)) for path in sorted(required)}
    return {"product": sorted(product), "tests": tests}, hashes


def inventory_digest(paths, hashes):
    return digest("".join(f"{hashes[path]}  {path}\n" for path in paths).encode())


def snapshot(root=ROOT):
    scopes, hashes = inventories(root)
    return {
        "schema": "R18-source-v1",
        "recipe": RECIPE,
        "scopes": scopes,
        "files": hashes,
        "digests": {name: inventory_digest(paths, hashes) for name, paths in scopes.items()},
        "historical_r17_product_label": HISTORICAL,
    }


def binding(path, root=ROOT):
    saved = json.loads(Path(path).read_bytes())
    require(saved == snapshot(root), "source set/content/recipe drift")
    size = (
        sum((root / AREA / name).stat().st_size for name in SOURCE_NAMES)
        + Path(path).stat().st_size
    )
    require(size <= CAPS["source_packet_bytes"], "source packet cap")
    return saved


def collection(path, packet):
    expected = [normalized_nodeid(node) for node in combined_selectors(packet)]
    observed = collected(path)
    require(observed == expected, "exact ordered collection differs")
    require(len(observed) == len(set(observed)) == 52, "collection duplicate/count")
    return observed


def combined_selectors(packet):
    groups = packet["groups"]
    return (
        groups["pure"][:16]
        + groups["old_sql"]
        + groups["pure"][16:]
        + groups["new_sql"]
        + groups["offline"]
    )


def xml_identity(nodeid):
    address, bracket, parameter = normalized_nodeid(nodeid).partition("[")
    parts = address.split("::")
    parts[0] = parts[0].replace("/", ".").removesuffix(".py")
    parts[-1] += bracket + parameter
    return ".".join(parts[:-1]), parts[-1]


def junit(path, selectors):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    actual = [(item.attrib["classname"], item.attrib["name"]) for item in cases]
    expected = [xml_identity(node) for node in selectors]
    require(len(actual) == len(set(actual)) == len(expected), "XML unique count")
    require(set(actual) == set(expected), "XML executed identities")
    require(not any(list(item) for item in cases), "XML failure/error/skip/output")
    for suite in root.iter("testsuite"):
        require(
            all(int(suite.attrib.get(key, 0)) == 0 for key in ("failures", "errors", "skipped")),
            "XML aggregate failures/errors/skips",
        )
    return actual


def stage_contract(stage, epoch, database=None, owned=False):
    require(stage in {"pre", "sql"}, "no HTTP/native stage")
    require(re.fullmatch(stage + r"_e[1-9][0-9]*", epoch) is not None, "fresh named epoch")
    if database is not None:
        require(stage == "sql" and database in DATABASES and owned is True, "owned exact SQL DB")


def evidence_cap(root, stage):
    cap = CAPS[f"{stage}_evidence_bytes"]
    size = sum(path.stat().st_size for path in Path(root).rglob("*") if path.is_file())
    require(size <= cap, f"evidence cap exceeded: {size} > {cap}; retain all bytes")
    return size


def child_record(path, code):
    path = Path(path)
    result = json.loads(path.read_bytes())
    owner_path = path.with_name(path.name.removesuffix(".process.json") + ".owner.json")
    require(result["owner"] == json.loads(owner_path.read_bytes()), "exact child owner record")
    require(
        result["group_drained"] is True and result["exit_code"] == int(code),
        "actual child exit and drain required before clearing ownership",
    )
    return result


def prior(root, source_binding, packet):
    root = Path(root)
    require(
        (root / "binding.json").read_bytes() == Path(source_binding).read_bytes(), "prior binding"
    )
    collection(root / "collection.stdout.txt", packet)
    codes = (root / "returncodes.txt").read_text().splitlines()
    for label in (
        "syntax",
        "pins",
        "ruff",
        "format",
        "collection",
        "inventory",
        "pure",
        "offline",
        "pure-xml",
        "offline-xml",
    ):
        require(codes.count(f"{label} 0") == 1, "prior phase: " + label)
        result = json.loads((root / f"{label}.process.json").read_bytes())
        require(
            result["exit_code"] == 0
            and result["reason"] == "completed"
            and result["group_drained"] is True,
            "prior child closure",
        )
    require(codes.count("stage pre exit 0") == 1, "prior actual passing pre")
    junit(root / "pure.xml", packet["groups"]["pure"])
    junit(root / "offline.xml", packet["groups"]["offline"])
    evidence_cap(root, "pre")


def fixture(baseline_path, docker):
    import subprocess

    baseline = json.loads(Path(baseline_path).read_bytes())

    def call(*arguments):
        return subprocess.check_output([docker, *arguments], text=True, timeout=20)

    def mounts(rows):
        return sorted(
            [
                {
                    key: row.get(key)
                    for key in ("Type", "Source", "Destination", "RW", "Propagation")
                }
                for row in rows
            ],
            key=lambda row: row["Destination"],
        )

    selected = (
        '{"Id":{{json .Id}},"Image":{{json .Image}},'
        '"Config":{"Image":{{json .Config.Image}},'
        '"Labels":{"tip054.executor":{{json (index .Config.Labels "tip054.executor")}}}},'
        '"Mounts":{{json .Mounts}},"State":{{json .State}},'
        '"RestartCount":{{json .RestartCount}},'
        '"NetworkSettings":{"Ports":{{json .NetworkSettings.Ports}},'
        '"Networks":{{json .NetworkSettings.Networks}}},'
        '"Caps":{"Memory":{{json .HostConfig.Memory}},'
        '"NanoCpus":{{json .HostConfig.NanoCpus}},"PidsLimit":{{json .HostConfig.PidsLimit}},'
        '"ReadonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},'
        '"CapDrop":{{json .HostConfig.CapDrop}},"SecurityOpt":{{json .HostConfig.SecurityOpt}},'
        '"Tmpfs":{{json .HostConfig.Tmpfs}}}}'
    )
    for old in baseline["containers"]:
        now = json.loads(call("inspect", "--format", selected, old["Id"]))
        require(
            now["Id"] == old["Id"] and now["Config"]["Labels"]["tip054.executor"] == FIXTURE,
            "fixture identity",
        )
        require(
            now["Image"] == old["ImageId"] and now["Config"]["Image"] == old["ImageRef"],
            "fixed image",
        )
        require(mounts(now["Mounts"]) == mounts(old["Mounts"]), "unchanged mounts")
        require(now["Caps"] == old["Caps"], "unchanged resource/security caps")
        require(now["NetworkSettings"]["Ports"] == old["Ports"], "unchanged ports")
        require(
            now["State"]["Running"]
            and not any(now["State"][key] for key in ("Paused", "Restarting", "OOMKilled"))
            and now["RestartCount"] == 0,
            "fixture state",
        )
        networks = now["NetworkSettings"]["Networks"]
        require(
            set(networks) == set(old["Networks"])
            and all(
                networks[key]["NetworkID"] == old["Networks"][key]["NetworkID"] for key in networks
            ),
            "unchanged internal network membership",
        )
        if old["Name"].endswith("-runner"):
            require(now["Config"]["Image"] == "rtr-tip054-local-qa:20261006", "runner image")
            top = call("top", old["Id"], "-eo", "pid,comm")
            require(
                all(
                    line.split()[1] in {"sh", "sleep", "ps"}
                    for line in top.strip().splitlines()[1:]
                ),
                "runner idle",
            )
    network = baseline["network"]
    now = json.loads(call("network", "inspect", network["Id"]))[0]
    require(
        now["Id"] == network["Id"]
        and now["Internal"] is True
        and now["Labels"]["tip054.executor"] == FIXTURE
        and set(now["Containers"]) == set(network["Containers"]),
        "exact internal network",
    )


def main():
    command, *args = sys.argv[1:]
    if command == "snapshot":
        print(json.dumps(snapshot(), indent=2, sort_keys=True))
        return
    packet = manifest(HERE / "qualification.json")
    if command == "source":
        saved = binding(args[0])
        print(json.dumps({"digests": saved["digests"], "files": len(saved["files"])}))
    elif command == "collection":
        collection(args[0], packet)
    elif command == "junit":
        junit(args[0], packet["groups"][args[1]])
    elif command == "prior":
        prior(args[0], args[1], packet)
    elif command == "selectors":
        selected = combined_selectors(packet) if args[0] == "all" else packet["groups"][args[0]]
        print("\n".join(selected))
        return
    elif command == "stage":
        stage_contract(*args)
    elif command == "cap":
        print(evidence_cap(*args))
    elif command == "child":
        child_record(*args)
    elif command == "fixture":
        fixture(*args)
    elif command == "review":
        require(
            digest(Path(args[0]).read_bytes()) == args[1]
            and "SOURCE ACCEPTED" in Path(args[0]).read_text(),
            "accepted pinned source review",
        )
    else:
        raise ValueError("unknown admission command")
    print("R18_ADMISSION_PASS", command)


if __name__ == "__main__":
    main()
