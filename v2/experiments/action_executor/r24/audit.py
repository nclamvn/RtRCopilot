"""Offline closed producer ledger audit; never imports the measured program."""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
BASE = "v2/experiments/action_executor/"
CAP = 10 * 1024 * 1024
SPEC = {
    "frozen_copies": "fixed", "literal_controls": "fixed", "literal_scope": "fixed",
    "launch_review": "conditional", "journal": "conditional",
    "final_samples": "conditional", "summary_stdout": "conditional",
    "load_stderr": "unknown", "migration_streams": "unknown",
    "owner_process": "conditional", "supervisor_stop": "unknown",
    "source_cap_child": "conditional", "fixture": "unknown", "database_admin": "unknown",
    "disk": "unknown", "reconstruction": "conditional", "returncodes": "conditional",
    "ephemeral": "unknown", "future_observer": "model", "outer_transcript": "unknown",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts
            and name == path.as_posix(), "noncanonical path")
    require(not any((ROOT / Path(*path.parts[:i])).is_symlink()
                    for i in range(1, len(path.parts) + 1)), "input symlink")
    return (ROOT / path).read_bytes()


def fingerprint(data, expected):
    require(type(expected) is str and len(expected) == 64 and sha(data) == expected,
            "changed fingerprint")


def parse(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("nonfinite JSON constant: " + value)
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def preserve():
    binding = json.loads((HERE / "input-binding.json").read_bytes())
    pins = {}

    def add(items):
        for path, digest in items.items():
            require(path not in pins or pins[path] == digest, "conflicting pin")
            pins[path] = digest

    add(binding["anchors"])
    for path, digest in pins.items():
        fingerprint(read(path), digest)
    p23 = json.loads(read(BASE + "r23/input-binding.json"))
    p22 = json.loads(read(BASE + "r22/input-binding.json"))
    add(p23["direct"])
    add(p23["anchors"])
    add(p22["direct"])
    links = dict(p22["links"])
    links.update(p23["anchors"])
    links[BASE + "r23/main-evidence-binding.sha256"] = binding["anchors"][
        BASE + "r23/main-evidence-binding.sha256"]
    add(links)
    for path, digest in links.items():
        data = read(path)
        fingerprint(data, digest)
        if path.endswith(".sha256"):
            entries = {}
            for line in data.decode().splitlines():
                value, name = line.split("  ", 1)
                require(name not in entries, "duplicate sealed input")
                entries[name] = value
            add(entries)
        elif path != BASE + "r22/input-binding.json":
            add(json.loads(data)["files"])
    prior_count = len(pins)
    prior_bytes = sum(len(read(p)) for p in pins)
    add(binding["direct"])
    total = 0
    for path, digest in pins.items():
        data = read(path)
        total += len(data)
        require(total <= 32 * 1024 * 1024, "input byte cap")
        fingerprint(data, digest)
    source = json.loads(read(BASE + "r18/source-binding-e3.json"))
    ignored = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    for scope, paths in source["scopes"].items():
        dirs = ("src", "migrations") if scope == "product" else ("tests",)
        actual = []
        for directory in dirs:
            for path in (ROOT / "v2/apps/backend" / directory).rglob("*"):
                relative = path.relative_to(ROOT)
                if ignored.intersection(relative.parts) or path.suffix == ".pyc":
                    continue
                require(not path.is_symlink(), "source symlink")
                if path.is_file():
                    actual.append(relative.as_posix())
        actual += [p for p in paths if not any("/" + d + "/" in p for d in dirs)]
        require(sorted(actual) == paths, "source inventory changed")
        fingerprint("".join(pins[p] + "  " + p + "\n" for p in paths).encode(),
                    source["digests"][scope])
    return {"prior_pins": prior_count, "prior_bytes": prior_bytes,
            "total_pins": len(pins), "input_bytes": total, "digests": source["digests"]}


def fixed_bounds():
    """Derive three exact fixed-target contributions, not caller numeric proofs."""
    tree = ast.parse(read(BASE + "r/run_phase_baseline.py"))
    payload = next(node.args[0] for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "dumps")
    for node in ast.walk(payload):
        if isinstance(node, ast.Name):
            require(node.id == "mode", "unexpected control expression")
    class Off(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(ast.Constant("off"), node)
    controls = ast.literal_eval(Off().visit(payload))
    scope_lines = read(BASE + "r21/run-http-qualification.sh").decode().splitlines()
    line = next(s for s in scope_lines if '> "$evidence/executor-scope.txt"' in s)
    require(line.startswith("printf '") and "' > " in line, "literal scope source")
    scope = line.split("'", 2)[1].replace("\\n", "\n").encode()
    return {"frozen_copies": sum(len(read(BASE + "r21/" + name))
                                for name in ("source-binding-e1.json", "contract.json")),
            "literal_controls": len(json.dumps(controls, indent=2).encode()),
            "literal_scope": len(scope)}


def audit(ledger, fixed, source_pins):
    require(type(ledger) is dict, "ledger object")
    require(set(ledger) == {"schema", "cap_bytes", "producers", "boundary"}, "ledger shape")
    require(ledger["schema"] == "R24-closed-producers-v1"
            and type(ledger["cap_bytes"]) is int and ledger["cap_bytes"] == CAP, "fixed cap")
    require(type(ledger["boundary"]) is str and ledger["boundary"], "capture boundary")
    require(type(ledger["producers"]) is list, "producer list")
    seen, files, subtotal, blockers = set(), set(), 0, []
    for entry in ledger["producers"]:
        require(type(entry) is dict, "producer object")
        require(set(entry) == {"id", "classification", "max_bytes", "count_domain",
                              "byte_domain", "witnesses", "historical_files",
                              "historical_bytes", "assumptions"}, "producer shape")
        name = entry["id"]
        require(type(name) is str and name in SPEC and name not in seen, "unknown/duplicate producer")
        seen.add(name)
        require(entry["classification"] == SPEC[name], "unsupported proof promotion")
        for field in ("count_domain", "byte_domain", "assumptions"):
            require(type(entry[field]) is str and entry[field], "malformed domain")
        require(type(entry["witnesses"]) is list and entry["witnesses"], "missing source witness")
        for witness in entry["witnesses"]:
            require(type(witness) is dict and set(witness) == {"path", "line", "sha256"}
                    and type(witness["line"]) is int and witness["line"] > 0
                    and type(witness["path"]) is str
                    and witness["path"] in source_pins
                    and witness["sha256"] == source_pins[witness["path"]], "source witness drift")
        require(type(entry["historical_bytes"]) is int and entry["historical_bytes"] >= 0
                and type(entry["historical_files"]) is list, "malformed historical observation")
        for path in entry["historical_files"]:
            require(type(path) is str and path not in files, "duplicate historical channel")
            files.add(path)
        if SPEC[name] == "fixed":
            require(type(entry["max_bytes"]) is int
                    and entry["max_bytes"] == fixed[name], "unsupported numeric proof")
            subtotal += fixed[name]
        else:
            require(entry["max_bytes"] is None, "unproved numeric upper bound")
            blockers.append(name)
    require(seen == set(SPEC), "missing producer")
    require(subtotal <= CAP, "fixed components exceed cap")
    return {"capture_admission": "HOLD", "total_upper_bytes": None,
            "fixed_subtotal_bytes": subtotal, "blockers": blockers,
            "producer_groups": len(seen), "historical_files": len(files),
            "historical_bytes": sum(p["historical_bytes"] for p in ledger["producers"]),
            "observer_nominal_model_bytes": 1281810,
            "reason": "Unknown/conditional/all-error producers have no ex-ante complete bound."}


def model_fit(payloads):
    require(type(payloads) is list and all(type(p) is bytes for p in payloads),
            "model needs actual byte payloads, not caller numeric proofs")
    size = sum(len(p) for p in payloads)
    require(size <= CAP, "model exceeds cap")
    return {"model_bytes": size, "model_fit": True, "capture_admission": "HOLD"}


def historical_coverage(ledger, observed):
    covered = []
    for producer in ledger["producers"]:
        files = producer["historical_files"]
        require(all(f in observed for f in files), "missing historical file")
        require(sum(observed[f] for f in files) == producer["historical_bytes"],
                "historical byte mismatch")
        covered.extend(files)
    require(len(covered) == len(set(covered)) and set(covered) == set(observed),
            "historical coverage mismatch")


if __name__ == "__main__":
    before = preserve()
    binding = json.loads((HERE / "input-binding.json").read_bytes())
    ledger = parse((HERE / "ledger.json").read_bytes())
    result = audit(ledger, fixed_bounds(), binding["sources"])
    raw = ROOT / BASE / "raw/tip054-4b-full-20261007-r5qa1/r19/r21_http_e1"
    observed = {}
    for path in raw.rglob("*"):
        require(not path.is_symlink(), "historical symlink")
        if path.is_file():
            observed[path.relative_to(raw).as_posix()] = path.stat().st_size
    historical_coverage(ledger, observed)
    marker = BASE + "raw/tip054-4b-full-20261007-r5qa1/r19/r21-campaign-launch.json"
    result["historical_sibling_marker_bytes"] = len(read(marker))
    after = preserve()
    require(before == after, "before/after preservation changed")
    print(json.dumps({"before": before, "audit": result, "after": after}, indent=2, sort_keys=True))
