"""Pure final inherited metadata parsing; actual path queries have SQL tests."""

import uuid
from typing import Any

import pytest

from rtr_copilot.actions.lineage_overlay import inherited_attributes


def member(kind: str, **updates: Any) -> dict[str, Any]:
    return {"resource_id": str(uuid.uuid4()), "resource_type": kind,
            "owner_subject_id": str(uuid.uuid4()), "classification": "internal",
            "source_zone": "private_context", "lifecycle_state": "active", **updates}


def body(members: Any, **updates: Any) -> Any:
    path = [r["resource_id"] for r in members]
    return {"path_present": True, "lineage": path, "current_path": path,
            "members": members, "old_deny": False, "deny_tx": False, "deny_current": False,
            "allow_tx": True, "allow_current": True, **updates}


def test_last_source_precedes_last_ancestor_with_worst_class_and_leaf_scope() -> None:
    department = uuid.uuid4()
    leaf = member("document_version", department_id=str(department))
    source = member("source", source_zone="sot")
    parent = member("template_version", classification="highly_restricted")
    result = inherited_attributes(body([leaf, source, parent]), frozenset())
    assert result is not None
    assert result[0].owner_id == source["owner_subject_id"] and result[0].source_zone == "sot"
    assert result[0].classification == "classified" and result[0].department == str(department)


@pytest.mark.parametrize("changes", [{"old_deny": True}, {"deny_current": True},
                                     {"allow_current": False}, {"allow_tx": False}])
def test_old_deny_and_current_private_absence_never_promote(changes: Any) -> None:
    result = inherited_attributes(body([member("object")], **changes), frozenset())
    assert result is not None and result[0].explicit_deny


@pytest.mark.parametrize("fault", ["missing_path", "changed_order", "missing_member", "quarantine"])
def test_invalid_actual_path_or_member_denies(fault: str) -> None:
    current = body([member("document_version"), member("document")])
    if fault == "missing_path":
        current["path_present"] = False
    elif fault == "changed_order":
        current["current_path"] = list(reversed(current["current_path"]))
    elif fault == "missing_member":
        current["members"] = current["members"][:-1]
    else:
        current["members"][1]["lifecycle_state"] = "quarantined"
    assert inherited_attributes(current, frozenset()) is None
