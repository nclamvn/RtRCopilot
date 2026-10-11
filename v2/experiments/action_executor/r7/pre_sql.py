"""R7-only finite static/collection/pure gate; never creates a DB or runs SQL tests.

Prepared during author HOLD. Execution requires separate Contractor approval,
exact frozen product/driver/scope hashes and an unused r7-prefixed gate ID.
Original mounted verification helpers are only called, never modified.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def product(repo):
    paths = subprocess.check_output(
        ["rg", "--files", "v2/apps/backend/src", "v2/apps/backend/migrations",
         "v2/apps/backend/pyproject.toml", "v2/apps/backend/uv.lock", "v2/.env.example"],
        cwd=repo, text=True,
    ).splitlines()
    content = subprocess.check_output(["shasum", "-a", "256", *sorted(paths)], cwd=repo)
    return hashlib.sha256(content).hexdigest()


def archive_map(repo):
    result = {}
    for name in ("_r2_source_archive", "_r3_source_archive", "_r7_source_archive"):
        root = repo / "v2/apps/backend/tests" / name
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[str(path.relative_to(repo))] = digest(path)
    return result


def nodeids(text):
    return [line.strip() for line in text.splitlines()
            if line.startswith("tests/") and "::" in line]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate_id")
    parser.add_argument("--product-sha256", required=True)
    parser.add_argument("--helper-sha256", required=True)
    parser.add_argument("--scope-sha256", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"r7_[a-z0-9_]{1,55}", args.gate_id), "unsafe gate ID"
    here = Path(__file__).resolve()
    repo = here.parents[4]
    scope_path = here.with_name("scope.json")
    assert digest(here) == args.helper_sha256, "driver not frozen"
    assert digest(scope_path) == args.scope_sha256, "scope not frozen"
    plan = read(scope_path)
    run = plan["fixture"]
    evidence = repo / "v2/experiments/action_executor/raw" / run / args.gate_id
    evidence.mkdir(exist_ok=False)
    manifest_path = repo / plan["archive_manifest"]
    assert digest(manifest_path) == plan["archive_manifest_sha256"]
    manifest = read(manifest_path)
    for entry in manifest["entries"]:
        assert digest(repo / entry["archive_path"]) == entry["sha256"]
    archives_before = archive_map(repo)
    write(evidence / "archives-before.json", archives_before)
    helpers_before = {str(here.relative_to(repo)): digest(here),
                      str(scope_path.relative_to(repo)): digest(scope_path)}
    write(evidence / "r7-helper-before.json", helpers_before)
    product_before = product(repo)
    assert product_before == args.product_sha256
    write(evidence / "product-before.json", {"sha256": product_before})

    # Explicit public synthetic configuration. No shell/private environment is
    # forwarded; the original admitted cache is used offline, never installed.
    clean = {
        "PATH": "/app/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "/qa/packages:/workspace/v2/apps/backend/src",
        "APP_ENV": "test",
        "POSTGRES_DSN": "postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_executor_verify",
        "REDIS_URL": "redis://tip054-redis:6379/0",
        "S3_ENDPOINT": "http://tip054-minio:9000",
        "S3_ACCESS_KEY": "rtr_tip054_local", "S3_SECRET_KEY": "rtr_tip054_synthetic_only",
        "S3_BUCKET": "rtr-tip054-synthetic", "RAG_EMBEDDING_PROVIDER": "offline",
        "RAG_PROVIDER_MODE": "local",
    }
    prefix = ["/usr/local/bin/docker", "exec", run + "-runner", "env", "-i"]
    prefix += [key + "=" + value for key, value in clean.items()]
    checks = {}

    def check(name, command, timeout=180):
        with (evidence / (name + ".stdout.txt")).open("wb") as out:
            with (evidence / (name + ".stderr.txt")).open("wb") as err:
                try:
                    status = subprocess.run(
                        prefix + command, cwd=repo, env={"PATH": os.defpath},
                        stdout=out, stderr=err, timeout=timeout, check=False,
                    ).returncode
                except subprocess.TimeoutExpired:
                    status = 124
        checks[name] = status
        write(evidence / "returncodes.json", checks)
        return status

    py = "/app/.venv/bin/python"
    ruff = "/app/.venv/bin/ruff"
    remote = "/evidence/" + args.gate_id + "/"
    assert check("source-before", [py, "/work/r/source_snapshot.py",
                                   remote + "source-before.json"]) == 0
    before = read(evidence / "source-before.json")
    baseline = read(evidence.parent / "r7_metadata/source-before-archive.json")
    changed = sorted(key for key in baseline if before.get(key) != baseline[key])
    additions = sorted(set(before) - set(baseline))
    allowed = set(plan["approved_product_paths"] + plan["approved_old_adaptations"])
    expected_additions = sorted(m["path"] for m in plan["modules"] if m["epoch"] == "new")
    assert set(changed) <= allowed, ("unapproved changes", changed)
    assert additions == expected_additions, ("unexpected new bindings", additions)
    assert len(before) == plan["expected_binding_entries"]
    write(evidence / "epoch-changes.json", {"changed": changed, "added": additions})
    # Historical adaptations retain their reviewed narrow semantic diffs; the
    # original gate did not require unrelated whole-file formatting repairs.
    format_paths = ["src/rtr_copilot/actions/request_connection.py", *expected_additions]
    commands = [
        ("ruff", [ruff, "check", "--no-cache", "src", "tests",
                  "migrations/versions/0019_action_executor.py"]),
        ("format", [ruff, "format", "--check", "--no-cache", *format_paths]),
        ("format-diff", [ruff, "format", "--diff", "--no-cache", *format_paths]),
        ("mypy", ["/app/.venv/bin/mypy", "--cache-dir=/tmp/" + args.gate_id]),
        ("imports", [py, "-c", "import dbos,sqlalchemy,psycopg,asyncpg,rtr_copilot.api.main,rtr_copilot.worker.main; from importlib.metadata import version; assert version('dbos')=='3.2.0' and sqlalchemy.__version__=='2.0.43' and psycopg.__version__=='3.2.9' and asyncpg.__version__=='0.30.0'; print('ACTUAL_SDK_APP_IMPORT_EXACT_PINS_PASS')"]),
        ("ordinary-collection", [py, "-m", "pytest", "--collect-only", "-q",
                                 "-p", "no:cacheprovider", "tests"]),
        ("scoped-collection", [py, "-m", "pytest", "--collect-only", "-q",
                               "-p", "no:cacheprovider",
                               *[m["path"] for m in plan["modules"]]]),
    ]
    for name, command in commands:
        check(name, command)
    collection = {}
    if checks["ordinary-collection"] == checks["scoped-collection"] == 0:
        ordinary = nodeids((evidence / "ordinary-collection.stdout.txt").read_text())
        scoped = nodeids((evidence / "scoped-collection.stdout.txt").read_text())
        old = {node for entry in manifest["entries"] for node in entry["cases"]}
        module_counts = {m["path"]: sum(n.split("::", 1)[0] == m["path"] for n in scoped)
                         for m in plan["modules"]}
        collection = {
            "ordinary_count": len(ordinary), "scoped_count": len(scoped),
            "old_ids_preserved": old <= set(scoped), "old_id_count": len(old),
            "unique_scoped_ids": len(set(scoped)) == len(scoped),
            "archive_collected": [n for n in ordinary if "_source_archive/" in n],
            "module_counts": module_counts,
            "new_ids": sorted(set(scoped) - old),
            "sql_ids": sum(module_counts[m["path"]] for m in plan["modules"] if m["kind"] == "sql"),
            "pure_ids": sum(module_counts[m["path"]] for m in plan["modules"] if m["kind"] == "pure"),
        }
        collection["pass"] = (
            len(old) == plan["old_ids"] and old <= set(scoped)
            and len(scoped) == len(set(scoped)) == plan["expected_scoped_ids"]
            and not collection["archive_collected"] and set(scoped) <= set(ordinary)
            and all(module_counts[m["path"]] == m["expected_cases"] for m in plan["modules"])
            and collection["sql_ids"] == plan["expected_sql_ids"]
            and collection["pure_ids"] == plan["expected_pure_ids"]
        )
        write(evidence / "scoped-nodeids.json", sorted(scoped))
    write(evidence / "collection-summary.json", collection)
    pure = {"status": "NOT_RUN"}
    if all(code == 0 for code in checks.values()) and collection.get("pass"):
        check("pure", [py, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
                       "--junitxml=" + remote + "pure.xml",
                       *[m["path"] for m in plan["modules"] if m["kind"] == "pure"]])
        if (evidence / "pure.xml").exists():
            root = ET.parse(evidence / "pure.xml").getroot()
            cases = list(root.iter("testcase"))
            pure = {"tests": len(cases),
                    "failures": sum(c.find("failure") is not None for c in cases),
                    "errors": sum(c.find("error") is not None for c in cases),
                    "skips": sum(c.find("skipped") is not None for c in cases)}
            pure["status"] = "PASS" if checks["pure"] == 0 and pure == {
                "tests": plan["expected_pure_ids"], "failures": 0, "errors": 0, "skips": 0,
            } else "FAIL"
        else:
            pure = {"status": "FAIL", "reason": "missing JUnit closure"}
    check("source-after", [py, "/work/r/source_snapshot.py", remote + "source-after.json"])
    after = read(evidence / "source-after.json")
    archives_after = archive_map(repo)
    write(evidence / "archives-after.json", archives_after)
    helpers_after = {str(here.relative_to(repo)): digest(here),
                     str(scope_path.relative_to(repo)): digest(scope_path)}
    write(evidence / "r7-helper-after.json", helpers_after)
    product_after = product(repo)
    top = subprocess.check_output(
        ["/usr/local/bin/docker", "top", run + "-runner", "-eo", "pid,comm"],
        text=True, timeout=30,
    )
    (evidence / "runner-processes.txt").write_text(top)
    idle = all(line.split()[-1] in {"sh", "sleep"} for line in top.splitlines()[1:])
    binding_ok = (before == after and archives_before == archives_after
                  and helpers_before == helpers_after
                  and product_before == product_after == args.product_sha256)
    result = {"status": "PASS" if binding_ok and idle and pure["status"] == "PASS"
              and all(code == 0 for code in checks.values()) else "FAIL",
              "product_sha256": product_after, "binding_entries": len(before),
              "source_archive_helper_product_bindings_pass": binding_ok,
              "collection": collection, "pure": pure, "returncodes": checks,
              "runner_idle": idle,
              "sql_tests_executed": 0, "databases_created": 0,
              "limits": "Static/import/collection and structural pure only. No SQL/CREATE or latency/native/build certification; original helpers unchanged. Host timeout is not proof of container-child termination; any timeout/nonidle requires CLOSE/HOLD and owner inspection, never retry/SQL progression."}
    write(evidence / "summary.json", result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
