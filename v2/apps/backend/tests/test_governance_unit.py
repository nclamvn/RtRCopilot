import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from rtr_copilot.governance.models import (
    RESEARCH_ZONE_LABEL,
    GovernanceSetting,
    ResearchEvidenceSpan,
    ResearchPackage,
    ResearchRecord,
    ResearchSource,
)
from rtr_copilot.repositories.governance import (
    ALLOWED_GAP_TRANSITIONS,
    GovernanceError,
    decode_gap_cursor,
    encode_gap_cursor,
    validate_setting_value,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64


def span() -> ResearchEvidenceSpan:
    return ResearchEvidenceSpan(
        source_url="https://example.org/evidence",
        locator={"page": 4, "line": 12},
        quoted_text="verbatim evidence",
        checksum=SHA,
    )


def record(**overrides: object) -> ResearchRecord:
    payload: dict[str, object] = {
        "package_id": uuid.uuid4(),
        "record_key": "IND.0001",
        "version_ordinal": 1,
        "tier": "P",
        "content": {"claim": "synthetic"},
        "searchable_text": "synthetic",
        "evidence_spans": [span()],
        "content_sha256": SHA,
    }
    payload.update(overrides)
    return ResearchRecord(**payload)  # type: ignore[arg-type]


def test_alembic_has_single_governance_head() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0015_generation_term_stats"]


def test_research_models_round_trip() -> None:
    source = ResearchSource(
        stable_key="refinery.industry",
        display_name="Refinery industry corpus",
        origin="refinery",
        owner_subject_id=uuid.uuid4(),
        classification="internal",
    )
    assert ResearchSource(**source.model_dump()) == source
    package = ResearchPackage(
        source_id=source.source_id,
        fingerprint=SHA,
        payload_sha256=SHA,
        snapshot_manifest={
            "captured_at": "2026-07-01T00:00:00+00:00",
            "scope": "industry",
            "adapter_version": "refinery-adapter-1",
        },
        captured_at=datetime(2026, 7, 1, tzinfo=UTC),
        snapshot_scope="industry",
        adapter_version="refinery-adapter-1",
        importer_subject_id=uuid.uuid4(),
    )
    assert ResearchPackage(**package.model_dump()) == package
    item = record()
    assert ResearchRecord(**item.model_dump()) == item
    assert item.zone_label == RESEARCH_ZONE_LABEL == "research"


def test_research_record_zone_label_and_tier_are_closed_vocabularies() -> None:
    with pytest.raises(ValidationError):
        record(zone_label="sot")
    with pytest.raises(ValidationError):
        record(zone_label="private_context")
    with pytest.raises(ValidationError):
        record(tier="Z")
    with pytest.raises(ValidationError):
        record(evidence_spans=[])


def test_gap_transition_matrix_is_append_only() -> None:
    for legal in (
        ("open", "triaged"),
        ("triaged", "assigned"),
        ("assigned", "answered"),
        ("answered", "published"),
        ("open", "declined"),
        ("triaged", "declined"),
        ("assigned", "declined"),
        ("answered", "declined"),
    ):
        assert legal in ALLOWED_GAP_TRANSITIONS
    for illegal in (
        ("open", "answered"),
        ("open", "published"),
        ("triaged", "open"),
        ("declined", "open"),
        ("published", "declined"),
    ):
        assert illegal not in ALLOWED_GAP_TRANSITIONS
    terminal = {"published", "declined"}
    assert all(source not in terminal for source, _ in ALLOWED_GAP_TRANSITIONS)


def test_gap_cursor_round_trip_and_rejection() -> None:
    first_seen_at = datetime(2026, 7, 31, 12, 30, 45, 123456, tzinfo=UTC)
    gap_id = uuid.uuid4()
    cursor = encode_gap_cursor(first_seen_at, gap_id)
    assert decode_gap_cursor(cursor) == (first_seen_at, gap_id)
    for malformed in ("", "not-a-cursor", "2026-07-31~not-a-uuid", "~"):
        with pytest.raises(GovernanceError, match="invalid_cursor"):
            decode_gap_cursor(malformed)


def test_setting_values_are_typed_and_bounded() -> None:
    validate_setting_value("integer", 5)
    validate_setting_value("decimal", 2.5)
    validate_setting_value("boolean", True)
    validate_setting_value("string", "curator:sot")
    validate_setting_value("duration_hours", 72)
    mismatches: list[tuple[str, object]] = [
        ("integer", "5"),
        ("integer", True),
        ("decimal", "2.5"),
        ("boolean", 1),
        ("string", 7),
        ("duration_hours", -1),
        ("duration_hours", 1.5),
    ]
    for value_type, value in mismatches:
        with pytest.raises(GovernanceError, match="setting_value_type_mismatch"):
            validate_setting_value(value_type, value)  # type: ignore[arg-type]


def test_governance_setting_model_round_trip() -> None:
    setting = GovernanceSetting(
        setting_id=uuid.uuid4(),
        setting_key="gap.sla.assign_hours",
        version=1,
        value_type="duration_hours",
        value=48,
        updated_by=uuid.uuid4(),
        reason="initial SLA window",
        created_at=datetime.now(UTC),
    )
    assert GovernanceSetting(**setting.model_dump()) == setting
