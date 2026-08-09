import math
import uuid

import pytest

from rtr_copilot.rag.adapters import OfflineHashEmbedding, normalize_query
from rtr_copilot.rag.answering import (
    GroundingError,
    existence_answer_instruction,
    needs_double_check,
    verify_grounding,
)
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.rag.models import (
    Citation,
    ProviderAnswer,
    ProviderEvidence,
    RetrievalHit,
)
from rtr_copilot.rag.reindex import stable_split
from rtr_copilot.rag.retrieval import RetrievalService


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        math.sqrt(sum(item * item for item in left))
        * math.sqrt(sum(item * item for item in right))
    )


def test_normalization_embedding_typo_camelcase_and_vietnamese() -> None:
    assert normalize_query("SkyWatch360, UAV!") == "sky watch360 drone"
    assert normalize_query("Thiết bị BAY không người lái") == (
        "thiet bi bay khong nguoi lai"
    )
    adapter = OfflineHashEmbedding()
    assert cosine(adapter.embed("autonomous drone"), adapter.embed("autonomus drone")) > 0.4
    assert adapter.embed("L3F.ENT.002") == adapter.embed("l3f.ent.002")


def test_mixed_case_acronym_remains_one_normalized_token() -> None:
    assert normalize_query("RtR là gì?") == "rtr la gi"


def test_existence_questions_request_a_useful_capability_summary() -> None:
    instruction = existence_answer_instruction("cty có crm không")
    assert "core business capabilities" in instruction
    assert existence_answer_instruction("CRM bên mình làm gì?") == ""


def test_stable_chunking_is_bounded_and_deterministic() -> None:
    content = "Một câu thứ nhất. " * 100
    first = stable_split(content, maximum=180, overlap=20)
    second = stable_split(content, maximum=180, overlap=20)
    assert first == second
    assert all(0 < len(item) <= 180 for item in first)
    assert len(first) > 1


def test_dlp_and_external_provider_fail_closed() -> None:
    external = ProviderPolicy(
        mode="external",
        external_allowlist=frozenset({"public_internal"}),
    )
    assert not external.inspect("ordinary", classification="restricted").allow
    decision = external.inspect(
        "api_key=top-secret-value",
        classification="public_internal",
    )
    assert not decision.allow
    assert "dlp.credential" in decision.rule_ids
    assert decision.text is None
    assert not external.inspect_context(
        '[{"text":"password=hunter2"}]',
        {"public_internal"},
    ).allow


def evidence(
    marker: str = "C1",
    *,
    provenance: str = "verified_primary",
    freshness: str = "current",
) -> ProviderEvidence:
    return ProviderEvidence(
        marker=marker,
        text="Synthetic verified statement.",
        provenance_level=provenance,
        verification_state="verified",
        freshness_state=freshness,
    )


def retrieval_hit(
    snippet: str,
    *,
    record_key: str,
    fusion: float,
) -> RetrievalHit:
    chunk_id = uuid.uuid4()
    return RetrievalHit(
        chunk_id=chunk_id,
        chunk_key=f"chunk:{chunk_id}",
        snippet=snippet,
        lexical_score=0.2,
        vector_score=0.3,
        fusion_score=fusion,
        classification="internal",
        citation=Citation(
            marker="C1",
            chunk_id=chunk_id,
            record_key=record_key,
            evidence_key="structured_text_json",
            record_checksum="a" * 64,
            evidence_checksum="b" * 64,
            source_key="unit-test",
            source_revision=1,
            provenance_level="approved_internal",
            verification_state="approved",
            freshness_state="current",
            source_label="unit test",
            locator={},
        ),
    )


def test_enterprise_merge_preserves_complete_procedure_sequence() -> None:
    authority = retrieval_hit(
        "RtR CRM là hệ thống nội bộ.",
        record_key="CRM.DEFINITION",
        fusion=9.0,
    )
    workflow = [
        retrieval_hit(
            f"B{ordinal} | Bước nghiệp vụ {ordinal}",
            record_key="crm.service-request-process",
            # Deliberately make scalar ranking prefer later steps. The merge
            # must retain the workflow order reconstructed by file retrieval.
            fusion=float(ordinal),
        )
        for ordinal in range(1, 10)
    ]
    padding = retrieval_hit(
        "Biểu mẫu liên quan có điểm rất cao.",
        record_key="crm.service-form",
        fusion=100.0,
    )

    merged = RetrievalService._merge_enterprise_hits(
        [authority],
        [*workflow, padding],
        limit=10,
        priority_record_keys=("CRM.DEFINITION",),
        query_intent="procedure",
    )

    assert [item.snippet for item in merged] == [
        authority.snippet,
        *(item.snippet for item in workflow),
    ]
    assert [item.citation.marker for item in merged] == [
        f"C{index}" for index in range(1, 11)
    ]


def test_enterprise_merge_uses_governed_binding_as_non_procedure_boundary() -> None:
    authority = retrieval_hit(
        "Fail-loud thay vì fail-silent.",
        record_key="L3F.2.038",
        fusion=1.0,
    )
    noisy_file = retrieval_hit(
        "Một tệp khác có điểm vector cao nhưng không được ontology bind.",
        record_key="unbound.file.chunk",
        fusion=100.0,
    )

    merged = RetrievalService._merge_enterprise_hits(
        [authority],
        [noisy_file],
        limit=10,
        priority_record_keys=("L3F.2.038",),
        query_intent="definition",
    )

    assert [item.citation.record_key for item in merged] == ["L3F.2.038"]
    assert merged[0].citation.marker == "C1"


def test_enterprise_merge_keeps_broad_recall_for_open_question() -> None:
    sot = retrieval_hit("SOT related fact.", record_key="SOT.RELATED", fusion=1.0)
    file_hit = retrieval_hit(
        "Enterprise file related fact.",
        record_key="enterprise.file",
        fusion=2.0,
    )

    merged = RetrievalService._merge_enterprise_hits(
        [sot],
        [file_hit],
        limit=10,
        priority_record_keys=(),
        query_intent="lookup",
    )

    assert [item.citation.record_key for item in merged] == [
        "enterprise.file", "SOT.RELATED",
    ]


def test_grounding_accepts_supported_and_rejects_unknown_or_missing_markers() -> None:
    verify_grounding(
        ProviderAnswer(
            answer="Synthetic verified statement. [C1]",
            used_markers=["C1"],
        ),
        [evidence()],
        max_chars=1000,
    )
    with pytest.raises(GroundingError, match="citation_missing_or_unknown"):
        verify_grounding(
            ProviderAnswer(answer="Unsupported. [C9]", used_markers=["C9"]),
            [evidence()],
            max_chars=1000,
        )
    with pytest.raises(GroundingError, match="evidence_unsupported"):
        verify_grounding(
            ProviderAnswer(
                answer="Completely unrelated assertion. [C1]",
                used_markers=["C1"],
            ),
            [evidence()],
            max_chars=1000,
        )
    with pytest.raises(GroundingError, match="factual_unit_ungrounded"):
        verify_grounding(
            ProviderAnswer(
                answer=(
                    "Unsupported hidden fact. "
                    "Synthetic verified statement. [C1]"
                ),
                used_markers=["C1"],
            ),
            [evidence()],
            max_chars=1000,
        )
    with pytest.raises(GroundingError, match="unsafe_provider_output"):
        verify_grounding(
            ProviderAnswer(
                answer="<script>unsafe</script> Synthetic statement. [C1]",
                used_markers=["C1"],
            ),
            [evidence()],
            max_chars=1000,
        )
    with pytest.raises(GroundingError, match="citation_missing_or_unknown"):
        verify_grounding(
            ProviderAnswer(answer="Unsupported.", used_markers=["C1"]),
            [evidence()],
            max_chars=1000,
        )


def test_needs_double_check_fires_only_for_the_soft_marker() -> None:
    # TIP-013B AC-3: the soft-tier marker Part A rides in ``record.value``.
    soft = {
        "capability": "Synthetic soft-tier fact.",
        "confidence_signal": {
            "tier": "soft",
            "needs_double_check": True,
            "source_note": 'specs/company.yaml · row 2 · "Synthetic…"',
        },
    }
    assert needs_double_check(soft) is True
    # Strict record: no confidence_signal key at all.
    assert needs_double_check({"capability": "Strict fact."}) is False
    # Signal present but explicitly not requiring a re-check.
    assert needs_double_check({
        "confidence_signal": {"tier": "strict", "needs_double_check": False},
    }) is False
    # Malformed / hostile shapes are total → False, never raise or coerce.
    assert needs_double_check({"confidence_signal": "soft"}) is False
    assert needs_double_check(
        {"confidence_signal": {"needs_double_check": "true"}},
    ) is False
    assert needs_double_check({"confidence_signal": {"needs_double_check": 1}}) is False
    assert needs_double_check(None) is False
    assert needs_double_check("soft") is False
    assert needs_double_check([{"needs_double_check": True}]) is False


def test_claim_or_stale_cannot_be_presented_as_verified() -> None:
    with pytest.raises(GroundingError, match="weak_evidence_claimed_verified"):
        verify_grounding(
            ProviderAnswer(
                answer="This is verified. [C1]",
                used_markers=["C1"],
            ),
            [evidence(provenance="claim")],
            max_chars=1000,
        )
    with pytest.raises(GroundingError, match="weak_evidence_claimed_verified"):
        verify_grounding(
            ProviderAnswer(
                answer="Đã xác minh. [C1]",
                used_markers=["C1"],
            ),
            [evidence(freshness="stale")],
            max_chars=1000,
        )


def test_ask_response_decision_diagnostic_defaults_none() -> None:
    """TIP-030: additive response field; absent unless diagnostics enabled."""
    import uuid

    from rtr_copilot.rag.models import AskResponse
    response = AskResponse(
        state="honest_null",
        answer="x",
        citations=[],
        conversation_id=uuid.uuid4(),
        answer_run_id=uuid.uuid4(),
        request_id="test-req",
    )
    assert response.decision_diagnostic is None
