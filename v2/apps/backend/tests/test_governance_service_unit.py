import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.governance.api import governance_subject
from rtr_copilot.governance.models import Gap, ReviewTask
from rtr_copilot.governance.queues import (
    QueueEntry,
    aggregate_entries,
    conflict_status,
    freshness_status,
    review_status,
)
from rtr_copilot.governance.service import (
    SETTING_REGISTRY,
    GovernanceService,
    decode_signed_cursor,
    encode_signed_cursor,
    validate_setting_bounds,
)
from rtr_copilot.repositories.governance import GovernanceError

SECRET = "unit-test-cursor-secret"


def subject(role: Role, user_id: uuid.UUID | None = None) -> Subject:
    return Subject(
        user_id=str(user_id or uuid.uuid4()),
        issuer="test",
        sub=uuid.uuid4().hex,
        email="person@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


def gap(**overrides: object) -> Gap:
    payload: dict[str, object] = {
        "gap_id": uuid.uuid4(),
        "question_fingerprint": "a" * 64,
        "sanitized_question": "What is the export state?",
        "sanitized_summary": "export state",
        "reason_category": "manual_entry",
        "classification": "internal",
        "requester_id": uuid.uuid4(),
        "routing_key": "curator:sot",
        "occurrence_count": 1,
        "lifecycle": "open",
        "origin": "manual",
        "priority": "normal",
        "first_seen_at": datetime.now(UTC),
        "last_seen_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return Gap(**payload)  # type: ignore[arg-type]


def entry(
    status: str,
    task_state: str | None = None,
) -> QueueEntry:
    version_id = uuid.uuid4()
    task = None
    if task_state is not None:
        now = datetime.now(UTC)
        task = ReviewTask(
            task_id=uuid.uuid4(),
            queue_kind="freshness",
            record_version_id=version_id,
            assignee_subject_id=uuid.uuid4(),
            assigned_by=uuid.uuid4(),
            state=task_state,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
            completed_at=now if task_state == "completed" else None,
        )
    return QueueEntry(
        queue_kind="freshness",
        record_id=uuid.uuid4(),
        record_key=f"REC.{version_id.hex}",
        record_version_id=version_id,
        owner_subject_id=uuid.uuid4(),
        classification="internal",
        status=status,  # type: ignore[arg-type]
        sort_at=datetime.now(UTC),
        task=task,
    )


def test_signed_cursor_round_trip_tamper_and_kind_binding() -> None:
    sort_at = datetime(2026, 7, 31, 12, 30, 45, 123456, tzinfo=UTC)
    item_id = uuid.uuid4()
    cursor = encode_signed_cursor("gaps", sort_at, item_id, SECRET)
    assert encode_signed_cursor("gaps", sort_at, item_id, SECRET) == cursor
    assert decode_signed_cursor("gaps", cursor, SECRET) == (sort_at, item_id)
    with pytest.raises(GovernanceError, match="invalid_cursor"):
        decode_signed_cursor("gaps", cursor[:-2] + "AA", SECRET)
    with pytest.raises(GovernanceError, match="invalid_cursor"):
        decode_signed_cursor("gaps", cursor, "other-secret")
    with pytest.raises(GovernanceError, match="invalid_cursor"):
        decode_signed_cursor("queue:freshness", cursor, SECRET)
    for malformed in ("", "garbage", "AAAA"):
        with pytest.raises(GovernanceError, match="invalid_cursor"):
            decode_signed_cursor("gaps", malformed, SECRET)


def test_setting_registry_is_typed_and_bounded() -> None:
    assert set(SETTING_REGISTRY) == {
        "gap.sla.triage_hours",
        "gap.sla.assign_hours",
        "queue.freshness.expiring_hours",
        "queue.owner_review.upcoming_hours",
        # TIP-012 Task 2 — cost budgets and job concurrency caps.
        "limits.budget.subject_daily_units",
        "limits.budget.global_daily_units",
        "limits.jobs.ingestion_max_inflight",
        "limits.jobs.render_max_inflight",
        "limits.jobs.index_max_backlog",
    }
    spec = validate_setting_bounds("gap.sla.assign_hours", 48)
    assert spec.value_type == "duration_hours"
    # New integer limit settings are typed and bounded like the rest.
    budget_spec = validate_setting_bounds("limits.budget.subject_daily_units", 500)
    assert budget_spec.value_type == "integer"
    with pytest.raises(GovernanceError, match="setting_out_of_bounds"):
        validate_setting_bounds("limits.budget.subject_daily_units", 0)
    with pytest.raises(GovernanceError, match="setting_value_type_mismatch"):
        validate_setting_bounds("limits.jobs.ingestion_max_inflight", 1.5)
    with pytest.raises(GovernanceError, match="setting_unknown"):
        validate_setting_bounds("gap.sla.unregistered", 1)
    with pytest.raises(GovernanceError, match="setting_out_of_bounds"):
        validate_setting_bounds("gap.sla.assign_hours", 0)
    with pytest.raises(GovernanceError, match="setting_out_of_bounds"):
        validate_setting_bounds("gap.sla.assign_hours", 999_999)
    with pytest.raises(GovernanceError, match="setting_value_type_mismatch"):
        validate_setting_bounds("gap.sla.assign_hours", "48")
    with pytest.raises(GovernanceError, match="setting_value_type_mismatch"):
        validate_setting_bounds("gap.sla.assign_hours", True)


def test_queue_status_boundaries_are_exact() -> None:
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    assert freshness_status(now, now=now) == "expired"
    assert freshness_status(now - timedelta(seconds=1), now=now) == "expired"
    assert freshness_status(now + timedelta(seconds=1), now=now) == "expiring"
    assert review_status(now, now=now) == "overdue"
    assert review_status(now + timedelta(hours=1), now=now) == "due"
    assert conflict_status(2, False) == "disputed"
    assert conflict_status(1, True) == "superseded_ambiguous"
    assert conflict_status(3, True) == "disputed"
    with pytest.raises(ValueError, match="not_a_conflict"):
        conflict_status(1, False)


def test_queue_aggregates_count_only_visible_entries() -> None:
    aggregates = aggregate_entries([
        entry("expired", task_state="assigned"),
        entry("expired", task_state="completed"),
        entry("expiring", task_state="reopened"),
        entry("expiring"),
    ])
    assert aggregates.total == 4
    assert aggregates.by_status == {"expired": 2, "expiring": 2}
    assert aggregates.assigned == 2
    assert aggregates.unassigned == 2
    empty = aggregate_entries([])
    assert empty.total == 0
    assert empty.by_status == {}


def test_gap_visibility_binds_identity_and_classification() -> None:
    service = GovernanceService()
    requester = uuid.uuid4()
    owner = uuid.uuid4()
    item = gap(requester_id=requester, owner_subject_id=owner)
    assert service.gap_visible(subject(Role.STAFF, requester), item, "req-1")
    assert service.gap_visible(subject(Role.STAFF, owner), item, "req-2")
    assert not service.gap_visible(subject(Role.STAFF), item, "req-3")
    assert service.gap_visible(subject(Role.CURATOR), item, "req-4")
    restricted = gap(requester_id=requester, classification="highly_restricted")
    assert not service.gap_visible(subject(Role.CURATOR), restricted, "req-5")
    assert not service.gap_visible(subject(Role.STAFF, requester), restricted, "req-6")
    restricted_mid = gap(requester_id=requester, classification="restricted")
    assert not service.gap_visible(
        subject(Role.STAFF, requester), restricted_mid, "req-7",
    )
    assert service.gap_visible(subject(Role.CURATOR), restricted_mid, "req-8")


def test_gap_mutation_requires_curator_or_admin_scope() -> None:
    service = GovernanceService()
    requester = uuid.uuid4()
    item = gap(requester_id=requester)
    assert not service.gap_mutation_allowed(
        subject(Role.STAFF, requester), item, "req-1",
    )
    assert not service.gap_mutation_allowed(subject(Role.LEADER), item, "req-2")
    assert service.gap_mutation_allowed(subject(Role.CURATOR), item, "req-3")
    assert service.gap_mutation_allowed(subject(Role.ADMIN), item, "req-4")


def override_subject(identity: Subject | None) -> None:
    async def resolve() -> Subject | None:
        return identity

    app.dependency_overrides[governance_subject] = resolve


def test_anonymous_probes_are_rejected_without_existence_leak() -> None:
    override_subject(None)
    try:
        with TestClient(app) as client:
            probes = [
                client.get("/api/v1/gaps"),
                client.get(f"/api/v1/gaps/{uuid.uuid4()}"),
                client.post(
                    f"/api/v1/gaps/{uuid.uuid4()}/triage",
                    json={"reason": "probe"},
                ),
                client.get("/api/v1/governance/queues/freshness"),
                client.post(
                    "/api/v1/governance/queues/freshness/assign",
                    json={
                        "record_version_id": str(uuid.uuid4()),
                        "assignee_subject_id": str(uuid.uuid4()),
                    },
                ),
                client.post(
                    f"/api/v1/governance/review-tasks/{uuid.uuid4()}/complete",
                ),
            ]
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    for response in probes:
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"
        assert response.json()["request_id"]


def test_unknown_queue_and_operation_paths_return_typed_404() -> None:
    override_subject(subject(Role.CURATOR))
    try:
        with TestClient(app) as client:
            unknown_queue = client.get("/api/v1/governance/queues/backlog")
            unknown_operation = client.post(
                f"/api/v1/gaps/{uuid.uuid4()}/promote",
                json={"reason": "probe"},
            )
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    assert unknown_queue.status_code == 404
    assert unknown_queue.json()["error"]["code"] == "not_found"
    assert unknown_operation.status_code == 404
    assert unknown_operation.json()["error"]["code"] == "not_found"


def test_tampered_cursors_fail_before_any_data_access() -> None:
    override_subject(subject(Role.CURATOR))
    try:
        with TestClient(app) as client:
            gaps = client.get("/api/v1/gaps", params={"cursor": "tampered"})
            queue = client.get(
                "/api/v1/governance/queues/freshness",
                params={"cursor": "tampered"},
            )
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    assert gaps.status_code == 400
    assert gaps.json()["error"]["code"] == "invalid_cursor"
    assert queue.status_code == 400
    assert queue.json()["error"]["code"] == "invalid_cursor"
