"""Small fail-closed projection tests; real SQL and races are separate gates."""

import uuid
from typing import Any

import pytest

from rtr_copilot.actions.authority import (
    LeafRequest,
    batch_leaf_attributes,
    leaf_attributes,
    projection,
)
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.models import Role


def identity(**updates: Any) -> Any:
    actor = uuid.uuid4()
    return {"identity": {"user_id": str(actor), "issuer": "synthetic", "provider_sub": "subject",
                         "email": None, "canonical_domain": None, "display_name": "",
                         "status": "active", "security_version": 4, "roles": [], "groups": [],
                         "scopes": [], "entitlements": [], **updates},
            "principal_ids": [actor]}


def test_projection_staff_fallback_does_not_invent_role_principal() -> None:
    row = identity(scopes=[{"type": "department", "key": "non-uuid"},
                           {"type": "project", "key": str(uuid.uuid4())}])
    frame = projection(row)
    assert frame.subject.roles == {Role.STAFF}
    assert frame.subject.departments == {"non-uuid"}
    assert frame.principal_ids == frozenset(row["principal_ids"])


@pytest.mark.parametrize("updates", [{"status": "disabled"}, {"roles": ["invented"]},
                                    {"security_version": -1}])
def test_invalid_actual_subject_denies(updates: Any) -> None:
    with pytest.raises(ActionError):
        projection(identity(**updates))


@pytest.mark.parametrize("deny_tx,deny_current,allow_tx,allow_current,denied", [
    (False, False, True, True, False), (True, False, True, True, True),
    (False, True, True, True, True), (False, False, True, False, True),
    (False, False, False, True, True),
])
def test_private_leaf_conservative_transaction_and_fresh_allow(
    deny_tx: bool, deny_current: bool, allow_tx: bool, allow_current: bool, denied: bool,
) -> None:
    body = {"resource": {"resource_id": str(uuid.uuid4()), "resource_type": "template_version",
                         "owner_subject_id": str(uuid.uuid4()), "classification": "internal",
                         "source_zone": "private_context", "lifecycle_state": "active"},
            "deny_tx": deny_tx, "deny_current": deny_current,
            "allow_tx": allow_tx, "allow_current": allow_current}
    attributes = leaf_attributes(body, frozenset({uuid.uuid4()}))
    assert attributes is not None and attributes.explicit_deny is denied


@pytest.mark.asyncio
async def test_conflicting_bound_types_deny_before_sql() -> None:
    resource = uuid.uuid4()
    with pytest.raises(ActionError):
        await batch_leaf_attributes(None, uuid.uuid4(), [  # type: ignore[arg-type]
            LeafRequest(resource, "view", "record"),
            LeafRequest(resource, "view", "template_version"),
        ])


@pytest.mark.asyncio
async def test_internal_capacity_stays_bounded_before_sql() -> None:
    with pytest.raises(ActionError):
        await batch_leaf_attributes(None, uuid.uuid4(), [  # type: ignore[arg-type]
            LeafRequest(uuid.uuid4(), "view") for _ in range(81)
        ])
