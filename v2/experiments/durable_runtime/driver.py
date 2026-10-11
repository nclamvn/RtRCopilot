"""Bounded real-process bake-off. Every failed attempt is retained, never waived."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import sqlite3
import subprocess
import sys
import time
from shared import MANIFEST, MANIFEST_SHA256, ROOT, connection, initialize, make_case, oracle, snapshot


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def quantiles(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "p50": None, "p95": None, "p99": None}
    return {"n": len(values), **{f"p{p}": values[max(0, math.ceil(len(values) * p / 100) - 1)] for p in (50, 95, 99)}}


def invoke(engine, cases, state_dir, trial_dir, concurrency, attempt=0, extra=None):
    requests = Path(trial_dir) / "requests.json"
    output = Path(trial_dir) / f"records-{attempt}.json"
    if not requests.exists():
        write_json(requests, cases)
    command = [sys.executable, str(ROOT / f"{engine}_adapter.py"), "--state-dir", str(state_dir),
               "--requests", str(requests), "--output", str(output), "--concurrency", str(concurrency), "--version", "v1"]
    command += extra or []
    started = time.perf_counter()
    with (Path(trial_dir) / f"stdout-{attempt}.txt").open("w") as stdout, (Path(trial_dir) / f"stderr-{attempt}.txt").open("w") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        peak_rss_kb = 0
        timeout = False
        deadline = time.monotonic() + MANIFEST["invocation_timeout_seconds"]
        while process.poll() is None:
            try:
                status = Path(f"/proc/{process.pid}/status").read_text()
                for line in status.splitlines():
                    if line.startswith("VmRSS:"):
                        peak_rss_kb = max(peak_rss_kb, int(line.split()[1]))
            except OSError:
                pass
            if time.monotonic() >= deadline:
                os.killpg(process.pid, signal.SIGKILL)
                timeout = True
                break
            time.sleep(0.05)
        code = process.wait()
    meta = {"command": command, "pid": process.pid, "returncode": code, "timeout": timeout,
            "elapsed_ms": (time.perf_counter() - started) * 1000, "peak_process_rss_kb": peak_rss_kb,
            "peak_scope": "adapter parent only; not engine service, aggregate, or idle footprint"}
    write_json(Path(trial_dir) / f"attempt-{attempt}.json", meta)
    records = json.loads(output.read_text()) if output.exists() else []
    return records, meta


def source_metrics(state_dir):
    with connection(str(state_dir)) as conn:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("requests", "budgets", "calls", "effects", "receipts", "faults", "audit", "unsupported_intents", "unsupported_effects")}
        size = conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]
    return {"rows": counts, "sqlite_database_bytes": size,
            "files_bytes": sum(p.stat().st_size for p in Path(state_dir).glob("source.sqlite*")),
            "write_observation": "logical rows, NOT physical writes/WAL amplification or engine writes"}


def engine_observation(engine):
    observed = {"scope": "local fixture cumulative logical rows/size; stats may lag and are NOT physical writes, cost, or production load"}
    try:
        if engine == "dbos":
            import psycopg
            from psycopg import sql
            with psycopg.connect(os.environ["DBOS_SYSTEM_DATABASE_URL"], connect_timeout=3) as conn:
                observed["database_stats"] = list(conn.execute("SELECT pg_database_size(current_database()),tup_inserted,tup_updated,tup_deleted FROM pg_stat_database WHERE datname=current_database()").fetchone())
                tables = [row[0] for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='dbos'")]
                observed["table_rows"] = {table: conn.execute(sql.SQL("SELECT COUNT(*) FROM dbos.{}").format(sql.Identifier(table))).fetchone()[0] for table in tables}
        elif engine == "temporal":
            path = Path("/bakeoff/temporal.sqlite")
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3) as conn:
                tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                observed["table_rows"] = {table: conn.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables}
                observed["page_bytes"] = conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]
            observed["database_files_bytes"] = sum(p.stat().st_size for p in path.parent.glob("temporal.sqlite*"))
        else:
            observed["engine"] = "none"
    except Exception as exc:
        observed["error"] = repr(exc)
    return observed


def run_trial(engine, cases, trial_dir, concurrency, crash=False):
    trial_dir.mkdir(parents=True, exist_ok=False)
    state_dir = Path(os.environ.get("BKO_RUNTIME_ROOT", "/bakeoff/runtime")) / trial_dir.parent.name / trial_dir.name
    initialize(cases, str(state_dir))
    engine_before = engine_observation(engine)
    records, first = invoke(engine, cases, state_dir, trial_dir, concurrency)
    attempts = [first]
    before_recovery = {case["id"]: snapshot(case, str(state_dir)) for case in cases}
    write_json(trial_dir / "source-after-first-attempt.json", before_recovery)
    if crash and first["returncode"] == -signal.SIGKILL:
        records, recovery = invoke(engine, cases, state_dir, trial_dir, concurrency, 1)
        attempts.append(recovery)
    by_id = {record["id"]: record for record in records}
    checks = [{"id": case["id"], **oracle(case, str(state_dir), by_id.get(case["id"], {}).get("result"))} for case in cases]
    summary = {"engine": engine, "scenario": cases[0]["scenario"], "concurrency": concurrency,
               "manifest_sha256": MANIFEST_SHA256, "requested_samples": len(cases),
               "records": len(records), "checks": checks, "attempts": attempts,
               "latency_ms": quantiles([r["elapsed_ms"] for r in records if not r.get("error")]),
               "errors": sum(bool(r.get("error")) for r in records),
               "pass": all(c["pass"] for c in checks) and all(not a["timeout"] for a in attempts),
               "source_metrics": source_metrics(state_dir)}
    summary["engine_before"] = engine_before
    summary["engine_after"] = engine_observation(engine)
    if crash:
        with connection(str(state_dir)) as conn:
            summary["fault_events"] = [dict(row) for row in conn.execute("SELECT * FROM faults")]
        summary["pass"] = summary["pass"] and len(attempts) == 2 and len(summary["fault_events"]) == 1
        if cases[0]["scenario"] == "ambiguous":
            initial = before_recovery[cases[0]["id"]]
            final = snapshot(cases[0], str(state_dir))
            summary["pass"] = summary["pass"] and initial["unsupported_effect_count"] == 1 and initial["receipt"] is None and initial["spent"] == 1 and final["unsupported_effect_count"] == 1 and final["spent"] == 1
    backup_dir = trial_dir / "state"
    backup_dir.mkdir()
    with connection(str(state_dir)) as src, sqlite3.connect(backup_dir / "source.sqlite") as dst:
        src.backup(dst)
    summary["runtime_state_dir"] = str(state_dir)
    summary["source_snapshot_sha256"] = hashlib.sha256((backup_dir / "source.sqlite").read_bytes()).hexdigest()
    write_json(trial_dir / "summary.json", summary)
    return summary


def digest_tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and p.name not in ("digests.json",)
            and not p.name.endswith(("-wal", "-shm"))}


def matched_comparison(out, engines):
    comparisons = []
    if "direct" not in engines:
        return comparisons
    for engine in engines:
        if engine == "direct":
            continue
        for concurrency in MANIFEST["concurrency"]:
            def records(candidate):
                p = out / f"{candidate}-load-{concurrency}" / "records-0.json"
                return {r["id"]: r for r in json.loads(p.read_text())} if p.exists() else {}
            direct = records("direct")
            candidate = records(engine)
            shared = sorted(set(direct) & set(candidate))
            differences = [candidate[i]["elapsed_ms"] - direct[i]["elapsed_ms"] for i in shared
                           if not candidate[i].get("error") and not direct[i].get("error")]
            q = quantiles(differences)
            comparisons.append({"engine": engine, "concurrency": concurrency,
                "paired_service_time_extra_ms": q,
                "p95_extra_target_ms": 1000, "p95_extra_met": q["p95"] is not None and q["p95"] <= 1000,
                "provider_delay_ms": MANIFEST["provider_delay_ms"],
                "metric": "same case service slot start-to-result, queue excluded; includes common source/provider, engine startup excluded",
                "scope": "single local shared source SQLite; DBOS PG vs Temporal CLI devSQLite; no production extrapolation"})
    return comparisons


def run(out, engines):
    out.mkdir(parents=True, exist_ok=False)
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("*.py")}
    write_json(out / "provenance.json", {"python": sys.version, "platform": platform.platform(),
        "manifest_sha256": MANIFEST_SHA256, "source_hashes": source_hashes,
        "scope": "synthetic isolated experiment; not Action Kernel or serving application"})
    summaries = []
    for engine in engines:
        # cold startup and recovery are separately retained, not mixed into sample percentiles.
        for scenario in MANIFEST["scenarios"]:
            case = make_case(f"case-{scenario}", scenario)
            if scenario == "ambiguous":
                case["fault_point"] = "crash_after_effect"
            cases = [case]
            if scenario in ("duplicate", "competing"):
                cases = [case, dict(case)]
            summaries.append(run_trial(engine, cases, out / f"{engine}-scenario-{scenario}", 2 if scenario == "competing" else 1, scenario.startswith("crash_") or scenario == "ambiguous"))
        for concurrency in MANIFEST["concurrency"]:
            cases = [make_case(f"load-{concurrency}-{i}") for i in range(MANIFEST["samples_per_profile"])]
            summaries.append(run_trial(engine, cases, out / f"{engine}-load-{concurrency}", concurrency))
    write_json(out / "comparison.json", matched_comparison(out, engines))
    write_json(out / "index.json", {"manifest_sha256": MANIFEST_SHA256, "engines": engines,
        "trials": [{"path": f"{s['engine']}-load-{s['concurrency']}" if s["requested_samples"] == MANIFEST["samples_per_profile"] else f"{s['engine']}-scenario-{s['scenario']}", "pass": s["pass"]} for s in summaries],
        "native_proofs": {"wait_restart": "missing", "cancel": "missing", "compatible_version": "missing", "backup_restore": "not_certified"},
        "eligibility": "UNRESOLVED: native proof, service idle/engine writes and security checks require independent verification"})
    write_json(out / "digests.json", digest_tree(out))
    return 0 if all(s["pass"] for s in summaries) else 1


def validate(out):
    errors = []
    try:
        index = json.loads((out / "index.json").read_text())
        if set(index["engines"]) != {"direct", "dbos", "temporal"}:
            errors.append("incomplete_candidate_set")
        expected = json.loads((out / "digests.json").read_text())
        actual = digest_tree(out)
        if expected != actual:
            errors.append("digest_mismatch_or_missing_file")
        if index["manifest_sha256"] != MANIFEST_SHA256:
            errors.append("manifest_mismatch")
        provenance = json.loads((out / "provenance.json").read_text())
        for name, digest in provenance["source_hashes"].items():
            if not (ROOT / name).exists() or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                errors.append("source_code_mismatch:" + name)
        for engine in index["engines"]:
            required = {f"{engine}-scenario-{s}" for s in MANIFEST["scenarios"]} | {f"{engine}-load-{c}" for c in MANIFEST["concurrency"]}
            found = {trial["path"] for trial in index["trials"] if trial["path"].startswith(engine + "-")}
            if required != found:
                errors.append("missing_or_extra_trials:" + engine)
        for trial in index["trials"]:
            path = out / trial["path"]
            summary = json.loads((path / "summary.json").read_text())
            requests = json.loads((path / "requests.json").read_text())
            last = len(summary["attempts"]) - 1
            records = json.loads((path / f"records-{last}.json").read_text())
            if len(records) != len(requests):
                errors.append("missing_samples:" + trial["path"])
            if "-load-" in trial["path"] and len(records) != MANIFEST["samples_per_profile"]:
                errors.append("missing_load_samples:" + trial["path"])
            by_id = {r["id"]: r for r in records}
            if len(by_id) != len({c["id"] for c in requests}):
                errors.append("identity_mismatch:" + trial["path"])
            checks = [oracle(c, str(path / "state"), by_id.get(c["id"], {}).get("result")) for c in requests]
            actual_pass = all(c["pass"] for c in checks) and not any(a["timeout"] for a in summary["attempts"])
            if summary["scenario"].startswith("crash_") or summary["scenario"] == "ambiguous":
                actual_pass = actual_pass and len(summary["attempts"]) == 2 and summary["attempts"][0]["returncode"] == -9
                if summary["scenario"] == "ambiguous":
                    initial = json.loads((path / "source-after-first-attempt.json").read_text())[requests[0]["id"]]
                    final = snapshot(requests[0], str(path / "state"))
                    actual_pass = actual_pass and initial["unsupported_effect_count"] == 1 and initial["receipt"] is None and initial["spent"] == 1 and final["unsupported_effect_count"] == 1 and final["spent"] == 1
            claimed_snapshot = summary.get("source_snapshot_sha256")
            if claimed_snapshot and claimed_snapshot != hashlib.sha256((path / "state" / "source.sqlite").read_bytes()).hexdigest():
                errors.append("source_snapshot_mismatch:" + trial["path"])
            if summary["pass"] != actual_pass or trial["pass"] != summary["pass"]:
                errors.append("false_success_or_summary_mismatch:" + trial["path"])
            recalculated = quantiles([r["elapsed_ms"] for r in records if not r.get("error")])
            if recalculated != summary["latency_ms"]:
                errors.append("quantile_mismatch:" + trial["path"])
    except (OSError, ValueError, KeyError) as exc:
        errors.append("invalid_evidence:" + repr(exc))
    return {"pass": not errors, "errors": errors, "selection_eligible": False,
            "limitation": "Integrity/local source checks only; native engine proofs and independent fresh rerun not inferred"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("run", "validate"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--engines", nargs="+", default=["direct", "dbos", "temporal"])
    args = parser.parse_args()
    if args.mode == "run":
        return run(args.out, args.engines)
    report = validate(args.out)
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
