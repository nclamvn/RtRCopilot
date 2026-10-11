"""Identical synthetic source for direct/DBOS/Temporal; NOT the product kernel."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import time

ROOT = Path(__file__).parent
MANIFEST_BYTES = (ROOT / "manifest.json").read_bytes()
MANIFEST = json.loads(MANIFEST_BYTES)
MANIFEST_SHA256 = hashlib.sha256(MANIFEST_BYTES).hexdigest()


def make_case(case_id: str, scenario: str = "success", **overrides) -> dict:
    case = {"id": case_id, "effect_key": f"effect:{case_id}",
            "parent_id": f"parent:{case_id}", "scenario": scenario,
            "provider_delay_ms": MANIFEST["provider_delay_ms"],
            "budget_limit": MANIFEST["budget_limit"], "fence": 1,
            "version": "v1", "max_attempts": 3, "activity_timeout_seconds": 5,
            "approval_revision": 1, "input_digest": "synthetic-input-v1",
            "schema_digest": "synthetic-schema-v1"}
    case.update(overrides)
    return case


@contextlib.contextmanager
def connection(state_dir: str):
    conn = sqlite3.connect(str(Path(state_dir) / "source.sqlite"), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        yield conn
    finally:
        conn.close()


def initialize(cases: list[dict], state_dir: str) -> None:
    cases = [expanded for case in cases for expanded in ([case, *partial_cases(case)] if case.get("native_partial") else [case])]
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    with connection(state_dir) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS requests (
          id TEXT PRIMARY KEY, effect_key TEXT NOT NULL, parent_id TEXT NOT NULL,
          fence INTEGER NOT NULL, allowed INTEGER NOT NULL, version TEXT NOT NULL,
          approval_revision INTEGER NOT NULL DEFAULT 1,
          input_digest TEXT NOT NULL DEFAULT 'synthetic-input-v1',
          schema_digest TEXT NOT NULL DEFAULT 'synthetic-schema-v1');
        CREATE TABLE IF NOT EXISTS budgets (parent_id TEXT PRIMARY KEY,
          limit_units INTEGER NOT NULL, spent INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS calls (effect_key TEXT PRIMARY KEY,
          parent_id TEXT NOT NULL, units INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS effects (effect_key TEXT PRIMARY KEY,
          fence INTEGER NOT NULL, outcome TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ownership (effect_key TEXT PRIMARY KEY, fence INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS unsupported_intents (effect_key TEXT PRIMARY KEY,
          timestamp REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS unsupported_effects (seq INTEGER PRIMARY KEY AUTOINCREMENT,
          effect_key TEXT NOT NULL, timestamp REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS receipts (effect_key TEXT PRIMARY KEY,
          receipt_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL, fence INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS faults (id TEXT PRIMARY KEY, point TEXT NOT NULL,
          pid INTEGER NOT NULL, timestamp REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT,
          id TEXT NOT NULL, event TEXT NOT NULL, pid INTEGER NOT NULL, timestamp REAL NOT NULL);
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
        for name, declaration in (("approval_revision", "INTEGER NOT NULL DEFAULT 1"),
                                  ("input_digest", "TEXT NOT NULL DEFAULT 'synthetic-input-v1'"),
                                  ("schema_digest", "TEXT NOT NULL DEFAULT 'synthetic-schema-v1'")):
            if name not in columns:
                conn.execute(f"ALTER TABLE requests ADD COLUMN {name} {declaration}")
        for case in cases:
            scenario = case["scenario"]
            conn.execute("INSERT OR IGNORE INTO requests(id,effect_key,parent_id,fence,allowed,version,approval_revision,input_digest,schema_digest) VALUES (?,?,?,?,?,?,?,?,?)",
                         (case["id"], case["effect_key"], case["parent_id"],
                          2 if scenario == "stale_owner" else case.get("fence", 1),
                          0 if scenario == "acl_drift" else 1,
                          "v2" if scenario == "incompatible_version" else "v1",
                          2 if scenario == "approval_drift" else 1,
                          "synthetic-input-v2" if scenario == "input_drift" else "synthetic-input-v1",
                          "synthetic-schema-v2" if scenario == "schema_drift" else "synthetic-schema-v1"))
            conn.execute("INSERT OR IGNORE INTO ownership VALUES (?,?)", (case["effect_key"], 2 if scenario == "stale_owner" else case.get("fence", 1)))
            conn.execute("INSERT OR IGNORE INTO budgets VALUES (?,?,0)",
                         (case["parent_id"], 0 if scenario == "budget_exhausted" else case["budget_limit"]))
        conn.commit()


def partial_cases(case: dict) -> tuple[dict, dict]:
    return tuple({**case, "id": case["id"] + ":" + step,
                  "effect_key": case["effect_key"] + ":" + step,
                  "native_partial": False, "native_wait": False, "scenario": "success"}
                 for step in ("first", "second"))


def audit(conn, case, event):
    conn.execute("INSERT INTO audit(id,event,pid,timestamp) VALUES (?,?,?,?)",
                 (case["id"], event, os.getpid(), time.time()))


def crash_once(case: dict, state_dir: str, point: str):
    if case.get("fault_point", case["scenario"]) != point:
        return
    with connection(state_dir) as conn:
        conn.execute("BEGIN IMMEDIATE")
        fresh = conn.execute("INSERT OR IGNORE INTO faults VALUES (?,?,?,?)",
                             (case["id"], point, os.getpid(), time.time())).rowcount
        if fresh:
            audit(conn, case, "sigkill:" + point)
        conn.commit()
    if fresh:
        os.kill(os.getpid(), signal.SIGKILL)


def snapshot(case: dict, state_dir: str) -> dict:
    with connection(state_dir) as conn:
        effect = conn.execute("SELECT * FROM effects WHERE effect_key=?", (case["effect_key"],)).fetchone()
        receipt = conn.execute("SELECT * FROM receipts WHERE effect_key=?", (case["effect_key"],)).fetchone()
        budget = conn.execute("SELECT * FROM budgets WHERE parent_id=?", (case["parent_id"],)).fetchone()
        return {"effect": dict(effect) if effect else None,
                "receipt": dict(receipt) if receipt else None,
                "spent": budget["spent"] if budget else None,
                "unsupported_effect_count": conn.execute("SELECT COUNT(*) FROM unsupported_effects WHERE effect_key=?", (case["effect_key"],)).fetchone()[0]}


def result(case, state_dir, status):
    state = snapshot(case, state_dir)
    receipt = state["receipt"]
    if receipt and receipt["fence"] != case["fence"]:
        receipt = None
    return {"status": status, "effect_key": case["effect_key"],
            "receipt_id": receipt["receipt_id"] if receipt else None,
            "spent": state["spent"]}


def authorized(conn, current, case):
    owner = conn.execute("SELECT fence FROM ownership WHERE effect_key=?", (case["effect_key"],)).fetchone()
    return (current["fence"] == case["fence"] and current["allowed"]
            and owner and owner["fence"] == case["fence"]
            and current["version"] == case["version"]
            and current["approval_revision"] == case.get("approval_revision", 1)
            and current["input_digest"] == case.get("input_digest", "synthetic-input-v1")
            and current["schema_digest"] == case.get("schema_digest", "synthetic-schema-v1"))


def execute(case: dict, state_dir: str) -> dict:
    """Every effect attempt checks current source fence/authorization atomically.

    Fixed synthetic priced units, not currency/LLM estimates. Calls deduplicate
    across retries and share parent budgets; ambiguous effects are never retried.
    """
    crash_once(case, state_dir, "crash_before_dispatch")
    scenario = case["scenario"]
    with connection(state_dir) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM requests WHERE id=?", (case["id"],)).fetchone()
        if not current:
            raise ValueError("request was not initialized")
        if not authorized(conn, current, case):
            audit(conn, case, "blocked_current_guard")
            conn.commit()
            return result(case, state_dir, "blocked")
        receipt = conn.execute("SELECT status FROM receipts WHERE effect_key=?", (case["effect_key"],)).fetchone()
        if receipt:
            conn.commit()
            return result(case, state_dir, receipt["status"])
        if scenario == "ambiguous" and conn.execute("SELECT 1 FROM unsupported_intents WHERE effect_key=?", (case["effect_key"],)).fetchone():
            # There is deliberately no source-status/idempotency API for this
            # provider. Persisted may-have-effect intent forbids a blind retry.
            conn.execute("INSERT OR IGNORE INTO receipts VALUES (?,?,?,?)",
                         (case["effect_key"], "receipt:" + case["effect_key"], "needs_review", case["fence"]))
            audit(conn, case, "ambiguous_refuse_blind_retry")
            conn.commit()
            return result(case, state_dir, "needs_review")
        if scenario == "unpriced":
            conn.commit()
            return result(case, state_dir, "blocked")
        known_effect = conn.execute("SELECT 1 FROM effects WHERE effect_key=?", (case["effect_key"],)).fetchone()
        if not known_effect:
            changed = conn.execute("UPDATE budgets SET spent=spent+1 WHERE parent_id=? AND spent+1<=limit_units", (case["parent_id"],)).rowcount
            if not changed:
                conn.commit()
                return result(case, state_dir, "blocked")
            attempt = conn.execute("SELECT spent FROM budgets WHERE parent_id=?", (case["parent_id"],)).fetchone()[0]
            conn.execute("INSERT INTO calls VALUES (?,?,1)", (case["effect_key"] + ":call:" + str(attempt), case["parent_id"]))
            audit(conn, case, "priced_call")
        if scenario == "ambiguous":
            # Intent is durable BEFORE the separate unsupported provider
            # transaction. Crash now can mean zero OR one unknown effect.
            # A later worker cannot distinguish those and must not retry.
            conn.execute("INSERT INTO unsupported_intents VALUES (?,?)", (case["effect_key"], time.time()))
            audit(conn, case, "unsupported_may_have_effect_intent")
        conn.commit()
    crash_once(case, state_dir, "crash_during_work")
    if not known_effect:
        time.sleep(case["provider_delay_ms"] / 1000)
    if scenario == "timeout":
        return result(case, state_dir, "failed")
    if case.get("hold_before_effect"):
        marker = Path(state_dir) / (case["id"] + ".before-effect")
        marker.write_text(json.dumps({"pid": os.getpid(), "case_id": case["id"], "timestamp": time.time()}))
        release = Path(state_dir) / (case["id"] + ".release-effect")
        deadline = time.monotonic() + 15
        while not release.exists():
            if time.monotonic() > deadline:
                raise TimeoutError("bounded supervisor effect pause not released")
            time.sleep(0.02)
    with connection(state_dir) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM requests WHERE id=?", (case["id"],)).fetchone()
        if not authorized(conn, current, case):
            audit(conn, case, "blocked_final_guard")
            conn.commit()
            return result(case, state_dir, "blocked")
        outcome = "partial" if scenario == "cancel_partial" else "known"
        if scenario == "ambiguous":
            # This fake API is append-only WITHOUT unique-effect protection.
            conn.execute("INSERT INTO unsupported_effects(effect_key,timestamp) VALUES (?,?)", (case["effect_key"], time.time()))
            inserted = 1
        else:
            inserted = conn.execute("INSERT OR IGNORE INTO effects VALUES (?,?,?)", (case["effect_key"], case["fence"], outcome)).rowcount
        if inserted:
            audit(conn, case, "source_effect")
        conn.commit()
    crash_once(case, state_dir, "crash_after_effect")
    status = "needs_review" if scenario == "ambiguous" else "cancelled" if scenario == "cancel_partial" else "succeeded"
    with connection(state_dir) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM requests WHERE id=?", (case["id"],)).fetchone()
        if not authorized(conn, current, case):
            conn.commit()
            return result(case, state_dir, "needs_review")
        conn.execute("INSERT OR IGNORE INTO receipts VALUES (?,?,?,?)",
                     (case["effect_key"], "receipt:" + case["effect_key"], status, case["fence"]))
        audit(conn, case, "receipt:" + status)
        conn.commit()
    return result(case, state_dir, status)


def expected_status(case):
    scenario = case["scenario"]
    if scenario.endswith("_drift") or scenario in ("stale_owner", "incompatible_version", "budget_exhausted", "unpriced"):
        return "blocked"
    return {"timeout": "failed", "cancel_partial": "cancelled", "ambiguous": "needs_review"}.get(scenario, "succeeded")


def oracle(case: dict, state_dir: str, observed: dict | None) -> dict:
    state = snapshot(case, state_dir)
    errors = []
    status = expected_status(case)
    if not observed or observed.get("status") != status:
        errors.append("incorrect_or_missing_outcome")
    expects_effect = status in ("succeeded", "cancelled")
    if bool(state["effect"]) != expects_effect:
        errors.append("effect_state_mismatch")
    if status in ("succeeded", "cancelled", "needs_review") and (not state["receipt"] or state["receipt"]["status"] != status):
        errors.append("receipt_state_mismatch")
    if status == "needs_review" and state["unsupported_effect_count"] not in (0, 1):
        errors.append("unsupported_blind_retry_or_missing_effect")
    if observed and observed.get("receipt_id") != (state["receipt"]["receipt_id"] if state["receipt"] else None):
        errors.append("fabricated_receipt")
    if state["spent"] is None or state["spent"] > case["budget_limit"]:
        errors.append("budget_violation")
    if observed and observed.get("spent") != state["spent"]:
        errors.append("reported_budget_mismatch")
    with connection(state_dir) as conn:
        count = conn.execute("SELECT COUNT(*) FROM audit WHERE id=? AND event='source_effect'", (case["id"],)).fetchone()[0]
        if count > 1:
            errors.append("duplicate_known_effect")
    return {"pass": not errors, "errors": errors, "expected_status": status, "source": state}
