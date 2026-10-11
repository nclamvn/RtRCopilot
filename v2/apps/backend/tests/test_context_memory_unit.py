"""Model and full-serialization budget oracles, without business-service stubs."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sot_fixtures import NOW

from rtr_copilot.context.models import (
    ContextError,
    ContextPacket,
    MemoryCreate,
    MemoryScope,
    PacketRequest,
    ResolvedSOTSource,
    SOTReference,
)
from rtr_copilot.context.service import ContextService, bound_packet


@pytest.mark.parametrize(
    "change",
    [
        {"authority": "sot"},
        {"classification": "public_internal"},
        {"acl": []},
        {"scope": {"kind": "project"}},
        {"scope": {"kind": "private", "key": str(uuid4())}},
        {"expires_at": NOW.replace(tzinfo=None)},
        {"kind": "inference"},
    ],
)
def test_memory_cannot_fabricate_authority_or_scope(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MemoryCreate.model_validate(
            {
                "kind": "preference",
                "text": "Prefer Vietnamese",
                "expires_at": NOW,
                **change,
            }
        )


@pytest.mark.parametrize(
    "keys", [("a" * 129,), ("same", "same"), (" ",), tuple(map(str, range(11)))]
)
def test_context_source_keys_are_bounded_and_unique(keys: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        PacketRequest(query="HERA", source_keys=keys)


@pytest.mark.parametrize("bytes_budget,tokens", [(1024, 256), (4096, 1024), (8192, 256)])
def test_entire_utf8_packet_not_only_source_text_is_bounded(bytes_budget: int, tokens: int) -> None:
    owner = uuid4()
    ref = SOTReference(
        source_key="synthetic.spec",
        record_key="ENT.001",
        record_version_id=uuid4(),
        content_sha256="a" * 64,
    )
    packet = ContextPacket(
        packet_id=uuid4(),
        caller_id=owner,
        scope=MemoryScope(),
        use_class="proposal",
        ontology_digest="b" * 64,
        retrieved_at=NOW,
        sources=(
            ResolvedSOTSource(
                reference=ref,
                record_id=uuid4(),
                owner_subject_id=owner,
                classification="internal",
                source_revision=1,
                effective_from=NOW,
                effective_to=None,
                freshness_due_at=None,
                retrieved_at=NOW,
                text="Thông tin hợp lệ — Việt Nam 🚁 " * 2000,
            ),
        ),
        max_bytes=bytes_budget,
        max_estimated_tokens=tokens,
    )
    result = bound_packet(packet)
    wire = json.dumps(
        result.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert len(wire) <= min(bytes_budget, tokens * 4)
    assert result.truncated and result.coverage == "partial"
    assert "budget_limited" in {gap.code for gap in result.gaps}
    assert result.token_measurement == "utf8_bytes_div4_estimate_not_provider_usage"
    assert "Thông tin" in (result.sources[0].text or "") if result.sources else True


def test_correction_ttl_is_absolute_initial_creation_ceiling() -> None:
    # Validation happens before SQL even if the client proposes now+30 days.
    service = ContextService.__new__(ContextService)
    service.clock = lambda: NOW + timedelta(days=10)
    service._expiry(NOW + timedelta(days=29), NOW)
    with pytest.raises(ContextError, match="memory_ttl_invalid") as failure:
        service._expiry(NOW + timedelta(days=40), NOW)
    assert failure.value.status == 422
