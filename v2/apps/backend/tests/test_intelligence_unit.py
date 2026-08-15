import hashlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from rtr_copilot.auth.models import ResourceAttributes, Role, Subject
from rtr_copilot.governance.models import ResearchSource
from rtr_copilot.intelligence.api import briefing
from rtr_copilot.intelligence.models import (
    IntelligenceBriefing,
    IntelligenceCounts,
    IntelligenceEvidence,
    IntelligenceItem,
)
from rtr_copilot.intelligence.service import IntelligenceService


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self.rows)

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    def __init__(
        self,
        metadata: list[dict[str, Any]],
        content: list[dict[str, Any]],
    ) -> None:
        self.metadata = metadata
        self.content = content
        self.content_ids: list[uuid.UUID] = []

    async def execute(self, statement: object, params: dict[str, Any]) -> FakeResult:
        query = str(statement)
        if "FROM subject_groups" in query:
            return FakeResult([])
        if "FROM records r" in query and "rv.value_payload" not in query:
            return FakeResult(self.metadata)
        if "FROM record_versions rv" in query and "rv.value_payload" in query:
            self.content_ids = list(params["ids"])
            return FakeResult([
                row for row in self.content if row["version_id"] in self.content_ids
            ])
        raise AssertionError(query)


class FakeContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeContext:
        return FakeContext(self.session)


class FakeResearchSession(FakeSession):
    async def execute(self, statement: object, params: dict[str, Any]) -> FakeResult:
        query = str(statement)
        if "FROM research_records rr" in query and "rr.searchable_text" not in query:
            return FakeResult(self.metadata)
        if "FROM research_records rr" in query and "rr.searchable_text" in query:
            self.content_ids = list(params["ids"])
            return FakeResult([
                row for row in self.content
                if row["research_record_id"] in self.content_ids
            ])
        raise AssertionError(query)


class FakeResearchPolicy:
    def search_scope_allowed(self, _subject: Subject, _request_id: str) -> bool:
        return True

    def source_searchable(
        self,
        _subject: Subject,
        source: ResearchSource,
        _request_id: str,
    ) -> bool:
        return source.lifecycle == "active"


class FakeResources:
    def __init__(self, denied: set[uuid.UUID], revoke: set[uuid.UUID] | None = None) -> None:
        self.denied = denied
        self.revoke = revoke or set()
        self.calls: dict[uuid.UUID, int] = {}

    async def policy_attributes(
        self,
        _session: object,
        resource_id: uuid.UUID,
        **_: object,
    ) -> ResourceAttributes | None:
        self.calls[resource_id] = self.calls.get(resource_id, 0) + 1
        if resource_id in self.denied:
            return ResourceAttributes(explicit_deny=True)
        if resource_id in self.revoke and self.calls[resource_id] > 1:
            return ResourceAttributes(explicit_deny=True)
        return ResourceAttributes(resource_id=str(resource_id), classification="internal")


def actor() -> Subject:
    user_id = uuid.uuid4()
    return Subject(
        user_id=str(user_id),
        issuer="unit",
        sub=user_id.hex,
        email="staff@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={Role.STAFF},
    )


def metadata_row(*, freshness: str = "current") -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "record_id": uuid.uuid4(),
        "record_key": f"RTR.TEST.{uuid.uuid4().hex[:6]}",
        "source_key": "rtr.company",
        "version_id": uuid.uuid4(),
        "package_revision": 1,
        "provenance_level": "approved_internal",
        "verification_state": "approved",
        "fact_state": "approved",
        "freshness_state": freshness,
        "freshness_due_at": None,
        "effective_from": now,
        "created_at": now,
        "content_sha256": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "classification": "internal",
        "producer": "rtr-company-registry",
    }


def content_row(row: dict[str, Any], text: str = "Company capability update") -> dict[str, Any]:
    return {
        "version_id": row["version_id"],
        "value_payload": {"title": "Capability update"},
        "searchable_text": text,
        "source_label": "Approved company registry",
        "locator": {"record_key": row["record_key"]},
    }


def research_rows(*, content_lifecycle: str = "active") -> tuple[
    dict[str, Any], dict[str, Any]
]:
    record_id = uuid.uuid4()
    source_id = uuid.uuid4()
    now = datetime.now(UTC)
    common = {
        "research_record_id": record_id,
        "record_key": "research.industry.signal",
        "tier": "P",
        "corroboration_state": "corroborated",
        "content_sha256": hashlib.sha256(b"research").hexdigest(),
        "created_at": now,
        "fingerprint": hashlib.sha256(b"package").hexdigest(),
        "source_id": source_id,
        "stable_key": "theskywatch",
        "origin": "refinery",
        "owner_subject_id": uuid.uuid4(),
        "classification": "internal",
        "content": {"title": "Precision agriculture market signal"},
    }
    metadata = {
        **common,
        "version_ordinal": 1,
        "package_id": uuid.uuid4(),
        "lifecycle": "active",
    }
    content = {
        **common,
        "lifecycle": content_lifecycle,
        "searchable_text": "Verified external UAV market signal",
        "evidence_spans": [{
            "source_url": "https://theskywatch.com/report",
            "locator": {"url": "https://theskywatch.com/report"},
        }],
    }
    return metadata, content


@pytest.mark.asyncio
async def test_metadata_policy_precedes_content_and_denied_rows_never_load() -> None:
    visible = metadata_row()
    denied = metadata_row()
    session = FakeSession([visible, denied], [content_row(visible), content_row(denied)])
    service = IntelligenceService(
        factory=FakeFactory(session),  # type: ignore[arg-type]
        resources=FakeResources({denied["record_id"]}),  # type: ignore[arg-type]
    )
    items, _ = await service._sot_items(actor(), request_id="req-038", budget=5)
    assert session.content_ids == [visible["version_id"]]
    assert [item.evidence.record_version_id for item in items] == [visible["version_id"]]


@pytest.mark.asyncio
async def test_revoked_after_content_load_is_not_disclosed() -> None:
    row = metadata_row()
    session = FakeSession([row], [content_row(row)])
    service = IntelligenceService(
        factory=FakeFactory(session),  # type: ignore[arg-type]
        resources=FakeResources(set(), {row["record_id"]}),  # type: ignore[arg-type]
    )
    items, _ = await service._sot_items(actor(), request_id="req-038", budget=5)
    assert session.content_ids == [row["version_id"]]
    assert items == []


@pytest.mark.asyncio
async def test_stale_item_is_metadata_only_and_never_loads_stale_value() -> None:
    row = metadata_row(freshness="expired")
    session = FakeSession([row], [content_row(row, "password=must-not-load")])
    service = IntelligenceService(
        factory=FakeFactory(session),  # type: ignore[arg-type]
        resources=FakeResources(set()),  # type: ignore[arg-type]
    )
    items, _ = await service._sot_items(actor(), request_id="req-038", budget=5)
    assert session.content_ids == []
    assert len(items) == 1
    assert items[0].kind == "attention"
    assert "password" not in items[0].summary


@pytest.mark.asyncio
async def test_synthetic_package_is_filtered_before_policy_and_content() -> None:
    row = metadata_row()
    row["producer"] = "test-fixture"
    session = FakeSession([row], [content_row(row, "must-not-load")])
    resources = FakeResources(set())
    service = IntelligenceService(
        factory=FakeFactory(session),  # type: ignore[arg-type]
        resources=resources,  # type: ignore[arg-type]
    )
    items, _ = await service._sot_items(actor(), request_id="req-038", budget=5)
    assert session.content_ids == []
    assert resources.calls == {}
    assert items == []


@pytest.mark.asyncio
async def test_dlp_rejection_removes_current_sot_content() -> None:
    row = metadata_row()
    session = FakeSession([row], [content_row(row, "api_key=must-not-disclose")])
    service = IntelligenceService(
        factory=FakeFactory(session),  # type: ignore[arg-type]
        resources=FakeResources(set()),  # type: ignore[arg-type]
    )
    items, rules = await service._sot_items(
        actor(), request_id="req-dlp", budget=5,
    )
    assert items == []
    assert rules == ["dlp.credential"]


def test_evidence_contract_cannot_mix_sot_and_research_identity() -> None:
    with pytest.raises(ValidationError, match="mixed_evidence_zone"):
        IntelligenceEvidence(
            zone_label="sot",
            record_key="RTR.TEST",
            source_key="rtr.company",
            source_label="Company",
            content_sha256="0" * 64,
            record_version_id=uuid.uuid4(),
            source_revision=1,
            research_record_id=uuid.uuid4(),
            package_fingerprint="1" * 64,
        )


def test_briefing_contract_rejects_mismatched_counts() -> None:
    evidence = IntelligenceEvidence(
        zone_label="sot",
        record_key="RTR.TEST",
        source_key="rtr.company",
        source_label="Company",
        content_sha256="0" * 64,
        record_version_id=uuid.uuid4(),
        source_revision=1,
    )
    item = IntelligenceItem(
        item_id="1" * 64,
        zone_label="sot",
        kind="update",
        priority="normal",
        title="Update",
        summary="Approved update",
        observed_at=datetime.now(UTC),
        ask_query="Explain this update",
        evidence=evidence,
    )
    with pytest.raises(ValidationError, match="intelligence_counts_mismatch"):
        IntelligenceBriefing(
            generated_at=datetime.now(UTC),
            items=[item],
            counts=IntelligenceCounts(updates=0, attention=0, research=0),
            request_id="req-counts",
        )


@pytest.mark.asyncio
async def test_research_source_revoked_after_content_load_is_not_disclosed() -> None:
    metadata, content = research_rows(content_lifecycle="retired")
    session = FakeResearchSession([metadata], [content])
    service = IntelligenceService(
        factory=FakeFactory(session),  # type: ignore[arg-type]
        research=FakeResearchPolicy(),  # type: ignore[arg-type]
    )
    items, _ = await service._research_items(
        actor(), request_id="req-research", budget=3,
    )
    assert session.content_ids == [metadata["research_record_id"]]
    assert items == []


@pytest.mark.asyncio
async def test_permitted_research_remains_separate_and_evidence_bound() -> None:
    metadata, content = research_rows()
    session = FakeResearchSession([metadata], [content])
    service = IntelligenceService(
        factory=FakeFactory(session),  # type: ignore[arg-type]
        research=FakeResearchPolicy(),  # type: ignore[arg-type]
    )
    items, _ = await service._research_items(
        actor(), request_id="req-research", budget=3,
    )
    assert len(items) == 1
    assert items[0].zone_label == "research"
    assert items[0].kind == "research"
    assert items[0].title == "Precision agriculture market signal"
    assert items[0].evidence.source_key == "theskywatch"
    assert items[0].evidence.record_version_id is None


@pytest.mark.asyncio
async def test_research_title_is_dlp_inspected_before_disclosure() -> None:
    metadata, content = research_rows()
    content["content"] = {"title": "secret=must-not-disclose"}
    session = FakeResearchSession([metadata], [content])
    service = IntelligenceService(
        factory=FakeFactory(session),  # type: ignore[arg-type]
        research=FakeResearchPolicy(),  # type: ignore[arg-type]
    )
    items, rules = await service._research_items(
        actor(), request_id="req-research-dlp", budget=3,
    )
    assert items == []
    assert rules == ["dlp.credential"]


@pytest.mark.asyncio
async def test_anonymous_briefing_is_denied_before_service_use() -> None:
    request = SimpleNamespace(state=SimpleNamespace(request_id="req-anon"))
    response = await briefing(request, None, 12)  # type: ignore[arg-type]
    assert response.status_code == 401
    assert b"authentication_required" in response.body
