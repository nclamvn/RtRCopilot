"""TIP-011 Task 3 backend unit tests: zone labels, pickers, scope, list.

Covers the additive contract package without infrastructure: literal-typed
``zone_label`` fields on governance and citation payloads (AC-07), picker
edge behavior before any data access (AC-06), the content-free research-scope
capability, the conversation-list boundary, and the new dashboard tiles.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject, SubjectStatus
from rtr_copilot.governance.api import STATUS_BY_CODE, governance_subject
from rtr_copilot.governance.dashboard import ConflictTile, OwnerReviewTile
from rtr_copilot.governance.models import Gap, ReviewTask
from rtr_copilot.governance.queues import QueueEntry, QueuePage, aggregate_entries
from rtr_copilot.governance.service import (
    GovernanceService,
    escape_like,
    validate_picker_query,
)
from rtr_copilot.rag.api import rag_subject
from rtr_copilot.rag.models import Citation
from rtr_copilot.repositories.governance import GovernanceError
from rtr_copilot.research.service import ResearchService


def subject(
    role: Role,
    user_id: uuid.UUID | None = None,
    *,
    status: SubjectStatus = SubjectStatus.ACTIVE,
) -> Subject:
    return Subject(
        user_id=str(user_id or uuid.uuid4()),
        issuer="tip011-unit",
        sub=uuid.uuid4().hex,
        email="person@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
        status=status,
    )


def gap_payload() -> dict[str, object]:
    return {
        "gap_id": uuid.uuid4(),
        "question_fingerprint": "a" * 64,
        "sanitized_question": "What is missing?",
        "sanitized_summary": "missing",
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


def citation_payload() -> dict[str, object]:
    return {
        "marker": "C1",
        "chunk_id": uuid.uuid4(),
        "record_key": "company.warranty",
        "record_version_id": uuid.uuid4(),
        "evidence_key": None,
        "record_checksum": "a" * 64,
        "evidence_checksum": None,
        "source_key": "rtr.specs",
        "source_revision": 1,
        "provenance_level": "verified_primary",
        "verification_state": "verified",
        "freshness_state": "current",
        "source_label": "Company specification",
        "locator": {"page": 4},
    }


def test_governance_payloads_carry_literal_sot_zone_labels() -> None:
    """AC-07: gap, review-task, queue-entry and queue-page payloads are
    structurally zone-labeled with the server constant."""
    gap = Gap(**gap_payload())  # type: ignore[arg-type]
    assert gap.zone_label == "sot"
    assert gap.model_dump()["zone_label"] == "sot"
    now = datetime.now(UTC)
    task = ReviewTask(
        task_id=uuid.uuid4(),
        queue_kind="freshness",
        record_version_id=uuid.uuid4(),
        assignee_subject_id=uuid.uuid4(),
        assigned_by=uuid.uuid4(),
        state="assigned",
        created_at=now,
        updated_at=now,
    )
    assert task.zone_label == "sot"
    entry = QueueEntry(
        queue_kind="freshness",
        record_id=uuid.uuid4(),
        record_key="REC.1",
        record_version_id=uuid.uuid4(),
        owner_subject_id=uuid.uuid4(),
        classification="internal",
        status="expiring",
        sort_at=now,
        task=task,
    )
    assert entry.zone_label == "sot"
    page = QueuePage(
        queue_kind="freshness",
        computed_at=now,
        entries=[entry],
        aggregates=aggregate_entries([entry]),
    )
    assert page.zone_label == "sot"
    with pytest.raises(ValidationError):
        Gap(**{**gap_payload(), "zone_label": "research"})  # type: ignore[arg-type]


def test_citation_zone_label_is_a_server_constant() -> None:
    """The frozen TIP-007 citation now carries the literal SOT label; any
    other value is structurally impossible (D-011-03 stays intact)."""
    citation = Citation(**citation_payload())  # type: ignore[arg-type]
    assert citation.zone_label == "sot"
    assert citation.model_dump()["zone_label"] == "sot"
    with pytest.raises(ValidationError):
        Citation(**{  # type: ignore[arg-type]
            **citation_payload(),
            "zone_label": "research",
        })


def test_dashboard_tiles_are_zone_labeled_literals() -> None:
    conflict = ConflictTile(
        total=2, disputed=1, superseded_ambiguous=1, assigned=0, unassigned=2,
    )
    review = OwnerReviewTile(total=1, due=1, overdue=0, assigned=1, unassigned=0)
    assert conflict.zone_label == "sot"
    assert review.zone_label == "sot"
    with pytest.raises(ValidationError):
        ConflictTile(
            zone_label="research",  # type: ignore[arg-type]
            total=0, disputed=0, superseded_ambiguous=0, assigned=0, unassigned=0,
        )


def test_picker_query_validation_and_like_escaping() -> None:
    assert validate_picker_query("  lan ") == "lan"
    for invalid in ("", "   ", "x" * 101):
        with pytest.raises(GovernanceError, match="picker_query_invalid"):
            validate_picker_query(invalid)
    assert STATUS_BY_CODE["picker_query_invalid"] == 400
    assert escape_like("100%_a\\b") == "100\\%\\_a\\\\b"


@pytest.mark.asyncio
async def test_subject_picker_is_gated_before_any_directory_access() -> None:
    """AC-06: a non-assigner gets the same typed 403 regardless of what
    exists — the denial happens before any directory row is read."""
    service = GovernanceService()
    with pytest.raises(PermissionError, match="curator_required"):
        await service.search_subjects(
            subject(Role.STAFF),
            "lan",
            request_id="picker-1",
        )
    with pytest.raises(GovernanceError, match="picker_query_invalid"):
        await service.search_subjects(
            subject(Role.CURATOR),
            "   ",
            request_id="picker-2",
        )
    with pytest.raises(GovernanceError, match="invalid_cursor"):
        await service.search_subjects(
            subject(Role.CURATOR),
            "lan",
            request_id="picker-3",
            cursor="tampered",
        )


@pytest.mark.asyncio
async def test_record_picker_rejects_bad_input_before_any_data_access() -> None:
    service = GovernanceService()
    with pytest.raises(GovernanceError, match="picker_query_invalid"):
        await service.search_records(
            subject(Role.CURATOR),
            "",
            request_id="picker-4",
        )
    with pytest.raises(GovernanceError, match="invalid_cursor"):
        await service.search_records(
            subject(Role.CURATOR),
            "warranty",
            request_id="picker-5",
            cursor="tampered",
        )


def override_governance(identity: Subject | None) -> None:
    async def resolve() -> Subject | None:
        return identity

    app.dependency_overrides[governance_subject] = resolve


def override_rag(identity: Subject | None) -> None:
    async def resolve() -> Subject | None:
        return identity

    app.dependency_overrides[rag_subject] = resolve


def test_anonymous_probes_on_new_endpoints_are_typed_401() -> None:
    override_governance(None)
    override_rag(None)
    try:
        with TestClient(app) as client:
            probes = [
                client.get(
                    "/api/v1/governance/pickers/subjects",
                    params={"query": "lan"},
                ),
                client.get(
                    "/api/v1/governance/pickers/records",
                    params={"query": "warranty"},
                ),
                client.get("/api/v1/research/scope"),
                client.get("/api/v1/conversations"),
            ]
    finally:
        app.dependency_overrides.pop(governance_subject, None)
        app.dependency_overrides.pop(rag_subject, None)
    for response in probes:
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"
        assert response.json()["request_id"]


def test_picker_endpoints_reject_invalid_query_and_cursor_typed() -> None:
    override_governance(subject(Role.CURATOR))
    try:
        with TestClient(app) as client:
            staff_denied = None
            missing = client.get("/api/v1/governance/pickers/subjects")
            blank = client.get(
                "/api/v1/governance/pickers/subjects",
                params={"query": "   "},
            )
            tampered = client.get(
                "/api/v1/governance/pickers/records",
                params={"query": "warranty", "cursor": "tampered"},
            )
            override_governance(subject(Role.STAFF))
            staff_denied = client.get(
                "/api/v1/governance/pickers/subjects",
                params={"query": "lan"},
            )
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    assert missing.status_code == 422
    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "picker_query_invalid"
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] == "invalid_cursor"
    assert staff_denied is not None
    assert staff_denied.status_code == 403
    assert staff_denied.json()["error"]["code"] == "curator_required"


def test_research_scope_is_content_free_and_predicate_bound() -> None:
    """Task 5: the boolean comes from the same predicate the search uses and
    never consults stored rows (no DB is available in this test)."""
    service = ResearchService()
    assert service.search_scope_allowed(subject(Role.STAFF), "scope-1") is True
    assert service.search_scope_allowed(subject(Role.CURATOR), "scope-2") is True
    disabled = subject(Role.STAFF, status=SubjectStatus.DISABLED)
    assert service.search_scope_allowed(disabled, "scope-3") is False

    override_governance(subject(Role.STAFF))
    try:
        with TestClient(app) as client:
            allowed = client.get("/api/v1/research/scope")
            override_governance(disabled)
            denied = client.get("/api/v1/research/scope")
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    assert allowed.status_code == 200
    assert allowed.json() == {"allowed": True}
    assert denied.status_code == 200
    assert denied.json() == {"allowed": False}


def test_conversation_list_rejects_tampered_cursor_before_data_access() -> None:
    override_rag(subject(Role.STAFF))
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/conversations",
                params={"cursor": "tampered"},
            )
    finally:
        app.dependency_overrides.pop(rag_subject, None)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"
