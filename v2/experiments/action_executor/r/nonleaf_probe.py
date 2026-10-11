"""Transparent observation of the independent real nonleaf scheduling repros."""
import hashlib
import json
import sys
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from rtr_copilot.actions import policy as policy_module
from rtr_copilot.actions.policy import ActionPolicy
from rtr_copilot.auth.policy import PolicyEngine

root = Path(sys.argv[1])
assert str(root).startswith("/evidence/")
active = ContextVar("r_nonleaf_actual_scope", default=None)
stream = (root / "actual-scope-observations.jsonl").open("x")
records = []


def retain(value):
    records.append(value)
    stream.write(json.dumps(value, separators=(",", ":")) + "\n")
    stream.flush()


def before(conn, cursor, statement, parameters, context, executemany):
    current = active.get()
    if current is not None:
        normalized = " ".join(statement.split())
        current["observed_statement_count"] += 1
        current["statement_static_sha256"].append(hashlib.sha256(normalized.encode()).hexdigest())


original_scope = ActionPolicy.session_resource
original_attributes = policy_module.current_effective_attributes
original_decide = PolicyEngine.decide


@wraps(original_scope)
async def scope(self, session, subject, resource_id, action, request_id, **kwargs):
    record = {"label": request_id, "observed_statement_count": 0,
              "statement_static_sha256": [], "fallback_tuple_observations": [],
              "candidate_policy_decisions": [], "error_type": None}
    token = active.set(record)
    try:
        result = await original_scope(
            self, session, subject, resource_id, action, request_id, **kwargs
        )
        record["completed_without_error"] = True
        return result
    except BaseException as exc:
        record["completed_without_error"] = False
        record["error_type"] = type(exc).__name__
        raise
    finally:
        retain(record)
        active.reset(token)


@wraps(original_attributes)
async def attributes(session, resource_id, **kwargs):
    result = await original_attributes(session, resource_id, **kwargs)
    current = active.get()
    if current is not None:
        current["fallback_tuple_observations"].append({
            "type": type(result).__name__, "arity": len(result) if result is not None else 0,
            "lineage_count": len(result[1]) if result is not None else 0,
            "leaf_in_lineage": resource_id in result[1] if result is not None else False,
            "explicit_deny": result[0].explicit_deny if result is not None else None,
        })
    return result


@wraps(original_decide)
def decide(self, subject, action, resource, context):
    result = original_decide(self, subject, action, resource, context)
    record = {"label": context.request_id, "allow": result.allow,
              "explicit_deny": resource.explicit_deny}
    if context.request_id == "RQB-independent-fallback-oracle":
        retain({"independent_fresh_sql_and_real_repo_policy_oracle": record})
    if active.get() is not None:
        active.get()["candidate_policy_decisions"].append(record)
    return result


event.listen(Engine, "before_cursor_execute", before)
ActionPolicy.session_resource = scope
policy_module.current_effective_attributes = attributes
PolicyEngine.decide = decide
try:
    code = pytest.main([
        "-q", "-rs", "-p", "no:cacheprovider", "-o",
        "asyncio_default_test_loop_scope=session",
        "--junitxml=" + str(root / "integration-1.xml"),
        "tests/test_action_nonleaf_checkpoint_integration.py",
    ])
finally:
    ActionPolicy.session_resource = original_scope
    policy_module.current_effective_attributes = original_attributes
    PolicyEngine.decide = original_decide
    event.remove(Engine, "before_cursor_execute", before)
    stream.close()
    (root / "actual-scope-observations.json").write_text(json.dumps(records, indent=2))
raise SystemExit(code)
