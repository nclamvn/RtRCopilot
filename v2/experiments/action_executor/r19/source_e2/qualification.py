"""R19 finite source/admission and original OFF raw reconstruction; stdlib only."""

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

_gate_path = Path(__file__).resolve().parent.parent / "r18/gate.py"
if (
    hashlib.sha256(_gate_path.read_bytes()).hexdigest()
    != "b44cf3781dc5afd307e4908c5801089167413d46dd53f4723012a40ee8d8f4a1"
):
    raise ValueError("immutable R18 gate drift")
_spec = importlib.util.spec_from_file_location("r19_frozen_r18_gate", _gate_path)
r18 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r18)

HERE = Path(__file__).resolve().parent
ROOT = Path("/workspace") if Path("/work/r19") == HERE else HERE.parents[3]
AREA = "v2/experiments/action_executor/r19"
RAW = r18.RAW + "/r19"
R18_BINDING = "v2/experiments/action_executor/r18/source-binding-e3.json"
R18_SHA = "5bb847ef6bee176454cc14ae4bd35024b847aef8f969d7f12f0c877a87f7b0f5"
RAW_BINDING = "v2/experiments/action_executor/r18/main-raw-binding.sha256"
RAW_SHA = "baf98899e8c67ad1a9acfeb3039c80444518e28f2613586b1ea5d9633763fd6a"
PRODUCT = "b28e70d1905930fd517576b7df73edc6710cf4bae273f137da5e75ffd155c641"
TESTS = "5039c2a6a47fa1566f84b1acf766c5d212f731e6c9127aeec08576c7663fadc1"
PROFILES = (1, 10, 25, 50)
OPERATIONS = ("admission", "submit", "status", "cancel")
STATUS = dict(zip(OPERATIONS, (201, 202, 200, 202), strict=True))
STATES = dict(zip(OPERATIONS, ("contract_ready", "queued", "queued", "cancelled"), strict=True))
DATABASES = ("rtr_tip054_r19_local_e1", "rtr_tip054_r19_engine_e1")
CAPS = {
    "pre_evidence_bytes": 10485760,
    "http_evidence_bytes": 10485760,
    "child_seconds": 120,
    "http_seconds": 190,
    "kill_grace_seconds": 10,
}
NAMES = tuple(
    sorted(
        (
            "test_contract_source_and_one_shot_admission",
            "test_raw_schema_identity_and_corruption",
            "test_cell_quantile_and_missing_conservation",
            "test_oracle_abort_and_original_summary_agreement",
            "test_owned_process_deadline_cap_and_shell_failclosed",
            "test_fixture_db_cleanup_and_readiness_ledger",
        )
    )
)
SELECTORS = ["/work/r19/test_r19_offline.py::OfflineControls::" + name for name in NAMES]
SOURCES = (
    "qualification.py",
    "bounded.py",
    "test_r19_offline.py",
    "run-http-qualification.sh",
    "contract.json",
    "expected-identities.json",
)
EXTRAS = (
    "vibecode_v2/R19_SCAN_REPORT.md",
    "vibecode_v2/TIP-054.4b-R19_DESIGN_PROPOSAL.md",
    "vibecode_v2/TIP-054.4b-R19_MANDATORY_OBSERVER_OFF_HTTP.md",
    "vibecode_v2/TIP-054.4b-R18_VERIFY_REPORT.md",
    "vibecode_v2/TIP-054.4b-R18_FINAL_RESULT_REVIEW.md",
    "v2/experiments/action_executor/r18/main-final-closure.json",
    RAW_BINDING,
    R18_BINDING,
    r18.RAW + "/r12_off_r1/run/r-controls.json",
    r18.RAW + "/r12_off_r1/run/samples.json",
    r18.RAW + "/r12_off_r1/run/latency-summary.json",
    r18.RAW + "/r12_off_r1/closure-returncodes.json",
)
require = r18.require
digest = r18.digest


def expected():
    return [
        (profile, case, operation)
        for profile in PROFILES
        for case in range(100)
        for operation in OPERATIONS
    ]


def load_json(path):
    return json.loads(
        Path(path).read_bytes(),
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError("nonfinite JSON constant: " + value)
        ),
    )


def contract(path=HERE / "contract.json"):
    require(Path(path).stat().st_size <= 65536, "contract cap")
    packet = load_json(path)
    http = load_json(HERE.parent / "r18/qualification.json")["http"]
    wanted = {
        "schema": "R19-finite-v1",
        "http": http,
        "databases": list(DATABASES),
        "product_digest": PRODUCT,
        "test_digest": TESTS,
        "controls": SELECTORS,
        "stages": ["pre", "http"],
        "http_epoch": "http_e1",
        "source_packet_bytes": 1048576,
        "pre_bytes": 10485760,
        "candidate": "NOT_READY",
        "serving_executor": "OFF",
        "tip054_5": "BLOCKED",
    }
    require(
        json.dumps(packet, sort_keys=True) == json.dumps(wanted, sort_keys=True),
        "exact immutable R18 HTTP/R19 admission contract",
    )
    require(
        json.dumps(load_json(HERE / "expected-identities.json"))
        == json.dumps([list(key) for key in expected()]),
        "fixed 1600 identities",
    )
    return packet


def snapshot():
    require(Path("/workspace") != ROOT, "complete source gate is host-only")
    require(digest(r18.content(ROOT, R18_BINDING)) == R18_SHA, "R18 binding pin")
    prior = r18.binding(ROOT / R18_BINDING)
    require(prior["digests"] == {"product": PRODUCT, "tests": TESTS}, "current source digests")
    hashes = dict(prior["files"])
    seal = r18.content(ROOT, RAW_BINDING)
    require(digest(seal) == RAW_SHA, "protected R18 raw seal")
    lines = seal.decode().splitlines()
    require(len(lines) == 385, "protected 385 raw pins")
    for line in lines:
        sha, path = line.split("  ", 1)
        require(digest(r18.content(ROOT, path)) == sha, "protected raw drift: " + path)
        hashes[path] = sha
    for path in (*EXTRAS, *(f"{AREA}/{name}" for name in SOURCES)):
        hashes[path] = digest(r18.content(ROOT, path))
    return {
        "schema": "R19-source-v1",
        "recipe": prior["recipe"],
        "scopes": prior["scopes"],
        "digests": prior["digests"],
        "files": dict(sorted(hashes.items())),
    }


def source(path):
    saved = load_json(path)
    require(saved == snapshot(), "current source/set/protected history drift")
    size = Path(path).stat().st_size + sum((HERE / name).stat().st_size for name in SOURCES)
    require(size <= 1048576, "source packet cap")
    return saved


def cap(root, stage):
    require(stage in {"pre", "http"}, "finite stages")
    size = sum(path.stat().st_size for path in Path(root).rglob("*") if path.is_file())
    require(size <= CAPS[stage + "_evidence_bytes"], "cap STOP; retain all bytes")
    return size


def evidence_cap(root, stage):
    return cap(root, stage)


def stage(stage_name, epoch):
    require(stage_name in {"pre", "http"}, "no native/ON stage")
    if stage_name == "pre":
        require(r18.re.fullmatch(r"pre_e[1-9][0-9]*", epoch) is not None, "fresh pre epoch")
    else:
        require(epoch == "http_e1", "only one fixed campaign epoch")


def database(target, owned=False):
    require(target in DATABASES and type(owned) is bool, "exact isolated DB identity")
    return target


def mark(path, binding):
    require(not Path(path).exists(), "campaign allowance consumed or unknown")
    packet = {
        "epoch": "http_e1",
        "binding_sha256": digest(Path(binding).read_bytes()),
        "contract_sha256": digest((HERE / "contract.json").read_bytes()),
        "consumed": True,
        "meaning": "created immediately before spawn; unknown launch consumed",
    }
    with Path(path).open("x") as stream:
        json.dump(packet, stream, sort_keys=True)
        stream.flush()
    return packet


def row_key(row):
    require(isinstance(row, dict), "raw object")
    common = {"profile", "case", "operation", "elapsed_ms", "okay"}
    require(
        set(row) in (common | {"http_status", "state", "error_code"}, common | {"exception_type"}),
        "original raw field schema",
    )
    require(type(row["profile"]) is int and row["profile"] in PROFILES, "typed profile")
    require(type(row["case"]) is int and 0 <= row["case"] < 100, "typed case")
    require(row["operation"] in OPERATIONS and type(row["okay"]) is bool, "operation/okay")
    elapsed = row["elapsed_ms"]
    require(
        type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0, "finite timer"
    )
    if "http_status" in row:
        require(type(row["http_status"]) is int and 100 <= row["http_status"] <= 599, "HTTP status")
        require(
            row["okay"] == (row["http_status"] == STATUS[row["operation"]]), "HTTP okay agreement"
        )
        require(row["state"] is None or type(row["state"]) is str, "state type")
        require(row["error_code"] is None or type(row["error_code"]) is str, "error code type")
        if row["okay"]:
            require(row["state"] == STATES[row["operation"]], "successful HTTP wrong state")
    else:
        require(
            row["okay"] is False and type(row["exception_type"]) is str and row["exception_type"],
            "exception outcome",
        )
    return row["profile"], row["case"], row["operation"]


def quantile(values, q):
    return sorted(values)[math.ceil(len(values) * q) - 1] if values else None


def reconstruct(rows):
    require(isinstance(rows, list) and len(rows) <= 1600, "bounded original observations")
    seen = {}
    order = {}
    profile_position = -1
    for row in rows:
        key = row_key(row)
        require(key not in seen, "duplicate slot; never repair/de-duplicate")
        position = PROFILES.index(key[0])
        require(position >= profile_position, "sequential profile blocks")
        profile_position = position
        prefix = key[:2]
        operation = OPERATIONS.index(key[2])
        require(operation > order.get(prefix, -1), "per-case chronology")
        if operation:
            require(
                seen.get((*prefix, "admission"), {}).get("okay") is True, "no admission predecessor"
            )
        if operation > 1:
            require(seen.get((*prefix, "submit"), {}).get("okay") is True, "no submit predecessor")
        if operation == 3:
            require(
                (*prefix, "status") in seen, "cancel follows observed status, even status failure"
            )
        seen[key] = row
        order[prefix] = operation
    cells = []
    for profile in PROFILES:
        for operation in OPERATIONS:
            samples = [
                row for key, row in seen.items() if key[0] == profile and key[2] == operation
            ]
            values = [row["elapsed_ms"] for row in samples]
            limit = 500 if operation == "admission" else 1000
            cell = {
                "concurrency": profile,
                "operation": operation,
                "samples": len(samples),
                "failures": sum(not row["okay"] for row in samples),
                "p50_ms": quantile(values, 0.5),
                "p95_ms": quantile(values, 0.95),
                "p99_ms": quantile(values, 0.99),
                "p95_limit_ms": limit,
            }
            cell["pass"] = len(samples) == 100 and cell["failures"] == 0 and cell["p95_ms"] <= limit
            cells.append(cell)
    missing = [list(key) for key in expected() if key not in seen]
    return {
        "observed": len(seen),
        "failed": sum(not row["okay"] for row in rows),
        "missing": missing,
        "missing_count": len(missing),
        "cells": cells,
        "status": "PASS" if all(cell["pass"] for cell in cells) else "FAIL",
    }


def packet(root):
    root = Path(root)
    marker = load_json(root.parent / "campaign-launch.json")
    require(
        marker
        == {
            "epoch": "http_e1",
            "binding_sha256": digest((root / "binding.json").read_bytes()),
            "contract_sha256": digest((HERE / "contract.json").read_bytes()),
            "consumed": True,
            "meaning": "created immediately before spawn; unknown launch consumed",
        },
        "fixed consumed campaign/source identity",
    )
    require(
        (root / "contract.json").read_bytes() == (HERE / "contract.json").read_bytes(),
        "retained campaign contract identity",
    )
    raw = (root / "run/samples.jsonl").read_bytes()
    require(not raw or raw.endswith(b"\n"), "partial trailing journal; retain without repair")
    rows = [
        json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        for line in raw.decode().splitlines()
    ]
    require(rows == load_json(root / "run/samples.json"), "parsed JSON/JSONL exact list equality")
    result = reconstruct(rows)
    summary = load_json(root / "run/latency-summary.json")
    require(
        summary["cells"] == result["cells"] and summary["status"] == result["status"],
        "unchanged original summary/value/verdict disagreement",
    )
    controls = load_json(root / "run/r-controls.json")
    require(
        controls
        == {
            "observer": "off",
            "pool_size": 5,
            "max_overflow": 5,
            "pre_ping": True,
            "operation_timeout_seconds": 0.9,
            "old_load_helper": "/work/latency_probe.py",
            "provider": False,
            "worker": False,
            "authority_override": "Existing current synthetic subject dependency ONLY",
        },
        "original OFF controls",
    )
    process = r18.child_record(
        root / "load.process.json", load_json(root / "load.process.json")["exit_code"]
    )
    expected_code = 0 if result["status"] == "PASS" else 1
    require(
        process["reason"] == "completed"
        and process["exit_code"] == expected_code
        and process["original_exit_code"] == expected_code,
        "driver/oracle exit disagrees with complete original helper verdict",
    )
    result["oracle_complete_pass"] = expected_code == 0
    require(len(rows) == 1600 or result["status"] == "FAIL", "full original population")
    return result


def analyze(root):
    try:
        result = packet(root)
        result["integrity"] = "PASS"
    except (ValueError, KeyError, OSError, TypeError) as error:
        result = {
            "integrity": "FAIL",
            "status": "FAIL",
            "error_type": type(error).__name__,
            "error": str(error),
            "requested": 1600,
            "limits": "malformed/partial evidence is not salvaged as a passing population",
        }
    return result


def collection(path):
    require(
        r18.collected(path) == [r18.normalized_nodeid(node) for node in SELECTORS],
        "exact six collection",
    )


def prior(root, binding):
    root = Path(root)
    require((root / "binding.json").read_bytes() == Path(binding).read_bytes(), "same binding pre")
    collection(root / "collection.stdout.txt")
    codes = (root / "returncodes.txt").read_text().splitlines()
    for label in ("syntax", "pins", "ruff", "format", "collection", "inventory", "offline", "xml"):
        require(codes.count(label + " 0") == 1, "actual passing pre child: " + label)
        child = r18.child_record(root / f"{label}.process.json", 0)
        require(child["reason"] == "completed", "pre child reason")
    require(codes.count("stage pre exit 0") == 1, "actual passing pre stage")
    r18.junit(root / "offline.xml", SELECTORS)
    cap(root, "pre")


if __name__ == "__main__":
    command, *arguments = sys.argv[1:]
    if command == "snapshot":
        print(json.dumps(snapshot(), indent=2, sort_keys=True))
        sys.exit(0)
    contract()
    if command == "source":
        saved = source(arguments[0])
        print(json.dumps({"files": len(saved["files"]), "digests": saved["digests"]}))
    elif command == "stage":
        stage(*arguments)
    elif command == "cap":
        print(cap(*arguments))
    elif command == "collection":
        collection(*arguments)
    elif command == "xml":
        r18.junit(arguments[0], SELECTORS)
    elif command == "prior":
        prior(*arguments)
    elif command == "mark":
        print(json.dumps(mark(*arguments)))
    elif command == "selectors":
        print("\n".join(SELECTORS))
        sys.exit(0)
    elif command == "child":
        r18.child_record(arguments[0], arguments[1])
    elif command == "drained":
        r18.child_record(arguments[0], load_json(arguments[0])["exit_code"])
    elif command == "fixture":
        r18.fixture(*arguments)
    elif command == "review":
        require(
            digest(Path(arguments[0]).read_bytes()) == arguments[1]
            and "SOURCE ACCEPTED" in Path(arguments[0]).read_text(),
            "accepted pinned source review",
        )
    elif command == "analyze":
        result = analyze(arguments[0])
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["integrity"] == "PASS" and result["status"] == "PASS" else 1)
    else:
        raise ValueError("unknown finite gate")
    print("R19_ADMISSION_PASS", command)
