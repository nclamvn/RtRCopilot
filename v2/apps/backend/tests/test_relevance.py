from rtr_copilot.rag.models import ProviderEvidence
from rtr_copilot.rag.relevance import (
    answer_relevant,
    candidate_relevance_score,
    evidence_relevant,
    profile_query,
)


def evidence(text: str, marker: str = "C1") -> ProviderEvidence:
    return ProviderEvidence(
        marker=marker,
        text=text,
        provenance_level="approved_internal",
        verification_state="approved",
        freshness_state="current",
    )


def score(question: str, text: str, record_key: str) -> float | None:
    return candidate_relevance_score(
        profile_query(question),
        text=text,
        record_key=record_key,
        base_score=0.07,
        vector_score=0.25,
        min_vector_score=0.15,
    )


def test_vega_definition_requires_vega_as_primary_subject() -> None:
    definition = score(
        "Vega là gì?",
        "VEGA · Tactical heavy lifter: Multirotor tactical UAV, payload 20 kg.",
        "HC-002",
    )
    battery = score(
        "Vega là gì?",
        "VEGA dùng smart battery 50.4V dung lượng 35000 mAh.",
        "L3F.1.011",
    )
    assert definition is not None and battery is not None and definition > battery
    assert score(
        "Vega là gì?",
        "L3R.K.007: Tầm điều khiển HERA là 15 km. VEGA có tầm 10 km.",
        "L3R.K.007",
    ) is None
    assert score(
        "Vega là gì?",
        "Danh mục sản phẩm gồm HERA, VEGA, HeraHub và VegaHub.",
        "L3R.2.005",
    ) is None
    assert score(
        "Vega là gì?",
        "Người đứng đầu công ty là CEO và nhà sáng lập.",
        "L3F.RES.004",
    ) is None


def test_question_evidence_gate_rejects_single_entity_padding() -> None:
    good = evidence("VEGA · Tactical heavy lifter: payload 20 kg.")
    irrelevant = evidence("Người đứng đầu công ty là CEO.", "C2")
    assert evidence_relevant("Vega là gì?", [good])
    assert not evidence_relevant("Vega là gì?", [good, irrelevant])
    assert not evidence_relevant("Vega là gì?", [irrelevant])


def test_answer_gate_rejects_wrong_primary_entity() -> None:
    assert answer_relevant(
        "Vega là gì?",
        "VEGA là nền tảng UAV tactical heavy-lift của RtR. [C1]",
    )
    assert not answer_relevant(
        "Vega là gì?",
        "HERA có tầm điều khiển 15 km; VEGA có tầm 10 km. [C1]",
    )
    assert not answer_relevant("Vega là gì?", "CEO là nhà sáng lập. [C1]")


def test_stopword_only_question_has_no_relevance_basis() -> None:
    assert not evidence_relevant("là gì và ở đâu?", [evidence("VEGA platform")])


def test_external_semantic_bridge_improves_recall_without_becoming_entity_truth() -> None:
    policy = evidence(
        "Annual leave policy grants employees twelve paid days per year."
    )
    answer = "Annual leave provides twelve paid days per year. [C1]"
    question = "PTO entitlement?"
    assert not evidence_relevant(question, [policy])
    assert not answer_relevant(question, answer)
    assert evidence_relevant(
        question,
        [policy],
        support_terms=("annual leave paid time off",),
    )
    assert answer_relevant(
        question,
        answer,
        support_terms=("annual leave paid time off",),
    )


def test_confirmed_plan_entity_controls_alias_retrieval_and_answer_gates() -> None:
    entities = ("OmniSight",)
    direct = evidence(
        "OmniSight 360° · Dual-pod gimbal: AI on-board, pan/tilt độc lập."
    )
    use_case = evidence(
        "Tactical overwatch ISR: HERA + OmniSight + LS1 + S1.",
        "C2",
    )
    assert evidence_relevant(
        "Omni là gì?",
        [direct],
        entities=entities,
        intent="definition",
    )
    assert not evidence_relevant(
        "Omni là gì?",
        [use_case],
        entities=entities,
        intent="definition",
    )
    assert answer_relevant(
        "Omni là gì?",
        "OmniSight là hệ gimbal dual-pod của RtR. [C1]",
        entities=entities,
        intent="definition",
    )
    assert not answer_relevant(
        "Omni là gì?",
        "HERA sử dụng OmniSight trong cấu hình ISR. [C1]",
        entities=entities,
        intent="definition",
    )
