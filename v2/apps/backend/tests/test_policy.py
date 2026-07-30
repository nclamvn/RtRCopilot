from datetime import UTC, datetime, timedelta

import pytest

from rtr_copilot.auth.audit import AuditEvent
from rtr_copilot.auth.models import (
    PolicyContext,
    ResourceAttributes,
    Role,
    Subject,
    SubjectStatus,
    TemporaryEntitlement,
)
from rtr_copilot.auth.policy import PolicyEngine


class MemoryAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def subject(role: Role, **overrides: object) -> Subject:
    values = {
        "user_id": "user-1",
        "issuer": "issuer",
        "sub": "sub",
        "email": "user@rtrobotics.com",
        "canonical_domain": "rtrobotics.com",
        "roles": {role},
    }
    values.update(overrides)
    return Subject(**values)  # type: ignore[arg-type]


CONTENT_MATRIX = [
    (role, classification, allowed)
    for role, clearance in [
        (Role.STAFF, 1),
        (Role.LEADER, 2),
        (Role.CURATOR, 2),
        (Role.ADMIN, 1),
    ]
    for classification, level in [
        ("public", 0),
        ("internal", 1),
        ("restricted", 2),
        ("classified", 3),
    ]
    for allowed in [level <= clearance]
]


@pytest.mark.parametrize(("role", "classification", "allowed"), CONTENT_MATRIX)
def test_content_classification_matrix(
    role: Role,
    classification: str,
    allowed: bool,
) -> None:
    decision = PolicyEngine(MemoryAudit()).decide(
        subject(role),
        "view",
        ResourceAttributes(classification=classification, owner_id="user-1"),
        PolicyContext(request_id="matrix"),
    )
    assert decision.allow is allowed


ROLE_MATRIX = [
    (role, action, allowed)
    for role in Role
    for action, required in [
        ("manage_users", Role.ADMIN),
        ("manage_policies", Role.ADMIN),
        ("curate", Role.CURATOR),
        ("approve", Role.LEADER),
    ]
    for allowed in [role == required]
]


@pytest.mark.parametrize(("role", "action", "allowed"), ROLE_MATRIX)
def test_role_action_matrix(role: Role, action: str, allowed: bool) -> None:
    decision = PolicyEngine(MemoryAudit()).decide(
        subject(role),
        action,
        ResourceAttributes(classification="internal"),
        PolicyContext(request_id="matrix"),
    )
    assert decision.allow is allowed


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        (ResourceAttributes(department="engineering"), True),
        (ResourceAttributes(department="finance"), False),
        (ResourceAttributes(project="atlas"), True),
        (ResourceAttributes(project="secret"), False),
        (ResourceAttributes(explicit_deny=True), False),
        (ResourceAttributes(classification="unknown"), False),
    ],
)
def test_resource_scope_matrix(resource: ResourceAttributes, expected: bool) -> None:
    decision = PolicyEngine(MemoryAudit()).decide(
        subject(
            Role.STAFF,
            departments={"engineering"},
            projects={"atlas"},
        ),
        "view",
        resource,
        PolicyContext(request_id="matrix"),
    )
    assert decision.allow is expected


@pytest.mark.parametrize("action", ["unknown", "delete", "", "superuser"])
def test_unknown_action_default_deny(action: str) -> None:
    decision = PolicyEngine(MemoryAudit()).decide(
        subject(Role.ADMIN),
        action,
        ResourceAttributes(classification="public"),
        PolicyContext(request_id="matrix"),
    )
    assert decision.allow is False
    assert decision.reason_code == "unknown_action"


def test_temporary_entitlement_expiry() -> None:
    now = datetime.now(UTC)
    active = TemporaryEntitlement(
        action="view",
        classification="classified",
        expires_at=now + timedelta(minutes=1),
    )
    expired = TemporaryEntitlement(
        action="download",
        classification="classified",
        expires_at=now - timedelta(seconds=1),
    )
    user = subject(Role.STAFF, temporary_entitlements=[active, expired])
    engine = PolicyEngine(MemoryAudit())
    assert engine.decide(
        user,
        "view",
        ResourceAttributes(classification="classified"),
        PolicyContext(request_id="entitlement", now=now),
    ).allow
    assert not engine.decide(
        user,
        "download",
        ResourceAttributes(classification="classified"),
        PolicyContext(request_id="entitlement", now=now),
    ).allow


def test_admin_content_non_bypass_and_disabled_user() -> None:
    engine = PolicyEngine(MemoryAudit())
    assert not engine.decide(
        subject(Role.ADMIN),
        "view",
        ResourceAttributes(classification="restricted"),
        PolicyContext(request_id="admin"),
    ).allow
    assert not engine.decide(
        subject(Role.ADMIN, status=SubjectStatus.DISABLED),
        "manage_users",
        ResourceAttributes(),
        PolicyContext(request_id="disabled"),
    ).allow


def test_curator_separation_of_duties_and_privileged_audit() -> None:
    sink = MemoryAudit()
    engine = PolicyEngine(sink)
    curator = subject(Role.CURATOR)
    denied = engine.decide(
        curator,
        "approve",
        ResourceAttributes(proposed_by=curator.user_id),
        PolicyContext(request_id="sod"),
    )
    assert not denied.allow
    assert denied.reason_code == "separation_of_duties"
    assert sink.events[0].request_id == "sod"
    serialized = sink.events[0].model_dump_json()
    for forbidden in ["token", "cookie", "secret"]:
        assert forbidden not in serialized.lower()


@pytest.mark.parametrize(
    ("action", "classification", "role", "allowed"),
    [
        ("view", "restricted", Role.LEADER, True),
        ("view", "classified", Role.LEADER, False),
        ("download", "restricted", Role.CURATOR, True),
        ("download", "classified", Role.CURATOR, False),
        ("render", "restricted", Role.STAFF, False),
        ("render", "classified", Role.ADMIN, False),
    ],
)
def test_privileged_content_allow_and_deny_are_audited_redacted(
    action: str,
    classification: str,
    role: Role,
    allowed: bool,
) -> None:
    sink = MemoryAudit()
    decision = PolicyEngine(sink).decide(
        subject(role),
        action,
        ResourceAttributes(
            resource_id="sensitive-record-name",
            classification=classification,
        ),
        PolicyContext(request_id="privileged-content"),
    )
    assert decision.allow is allowed
    assert len(sink.events) == 1
    assert sink.events[0].result == ("allow" if allowed else "deny")
    serialized = sink.events[0].model_dump_json()
    assert "sensitive-record-name" not in serialized
    for forbidden in ["token", "cookie", "secret", "payload"]:
        assert forbidden not in serialized.lower()
