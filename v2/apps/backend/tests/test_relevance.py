from rtr_copilot.rag.models import ProviderEvidence
from rtr_copilot.rag.relevance import (
    answer_relevant,
    candidate_relevance_score,
    collection_items_covered,
    corpus_idf_coverage,
    corpus_rare_term_coverage,
    evidence_relevant,
    is_procedure_row,
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


def test_corpus_idf_coverage_fails_neutral_without_statistics() -> None:
    assert corpus_idf_coverage(
        ("argon2id", "nguoi", "dung"),
        text="Mật khẩu người dùng được băm bằng Argon2id.",
        record_key="L3F.INF.014",
        idf_by_term={},
    ) == 0.0


def test_corpus_idf_lifts_rare_exact_fact_above_long_company_prose() -> None:
    question = "Mật khẩu người dùng của RtR được băm bằng Argon2id phải không?"
    profile = profile_query(question)
    query_terms = (
        "mat", "khau", "nguoi", "dung", "rtr", "bam", "bang", "argon2id", "phai",
    )
    idf = {
        "argon2id": 6.301,
        "bam": 5.608,
        "khau": 4.429,
        "phai": 4.050,
        "mat": 3.949,
        "nguoi": 3.858,
        "bang": 3.356,
        "dung": 2.760,
        "rtr": 2.232,
    }
    fact_text = (
        "Mật khẩu người dùng được băm bằng Argon2id với salt riêng cho từng "
        "người dùng."
    )
    inventory_text = (
        "RtR có kho tài liệu người dùng và các báo cáo được dùng trong vận hành."
    )
    fact_coverage = corpus_idf_coverage(
        query_terms,
        text=fact_text,
        record_key="L3F.INF.014",
        idf_by_term=idf,
    )
    inventory_coverage = corpus_idf_coverage(
        query_terms,
        text=inventory_text,
        record_key="L3F.2.039",
        idf_by_term=idf,
    )
    fact = candidate_relevance_score(
        profile,
        text=fact_text,
        record_key="L3F.INF.014",
        base_score=0.123,
        vector_score=0.25,
        min_vector_score=0.15,
        idf_coverage=fact_coverage,
        rare_idf_coverage=corpus_rare_term_coverage(
            query_terms,
            text=fact_text,
            record_key="L3F.INF.014",
            idf_by_term=idf,
        ),
    )
    inventory = candidate_relevance_score(
        profile,
        text=inventory_text,
        record_key="L3F.2.039",
        base_score=0.083,
        vector_score=0.25,
        min_vector_score=0.15,
        idf_coverage=inventory_coverage,
        rare_idf_coverage=corpus_rare_term_coverage(
            query_terms,
            text=inventory_text,
            record_key="L3F.2.039",
            idf_by_term=idf,
        ),
    )
    assert fact_coverage > inventory_coverage
    assert fact is not None and inventory is not None and fact > inventory


def test_rare_exact_anchor_beats_multiple_common_company_terms() -> None:
    question = "Argon2id được RtR dùng để làm gì?"
    profile = profile_query(question)
    terms = ("argon2id", "rtr", "dung", "lam")
    idf = {"argon2id": 6.301, "lam": 3.698, "dung": 2.760, "rtr": 2.232}
    fact_text = "Mật khẩu người dùng được băm bằng Argon2id với salt riêng."
    generic_text = "RtR dùng tài liệu này làm fact-sheet chính thức gửi báo chí."

    def ranked(text: str, key: str, base: float) -> float | None:
        return candidate_relevance_score(
            profile,
            text=text,
            record_key=key,
            base_score=base,
            vector_score=0.25,
            min_vector_score=0.15,
            idf_coverage=corpus_idf_coverage(
                terms, text=text, record_key=key, idf_by_term=idf,
            ),
            rare_idf_coverage=corpus_rare_term_coverage(
                terms, text=text, record_key=key, idf_by_term=idf,
            ),
        )

    fact = ranked(fact_text, "L3F.INF.014", 0.058)
    generic = ranked(generic_text, "L3F.2.021", 0.105)
    assert fact is not None and generic is not None and fact > generic


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


def test_authoritative_definition_binding_rejects_incidental_acronym_record() -> None:
    profile = profile_query(
        "rtr là gì? Real-time Robotics",
        entities=("Real-time Robotics",),
        intent="definition",
        definition_record_keys=("L3F.ENT.002",),
    )
    company = candidate_relevance_score(
        profile,
        text="Real-time Robotics (RtR) là công ty Việt Nam phát triển hệ thống UAV.",
        record_key="L3F.ENT.002",
        base_score=0.07,
        vector_score=0.25,
        min_vector_score=0.15,
    )
    droneverse = candidate_relevance_score(
        profile,
        text="RTR DroneVerse là hệ thống mô phỏng UAV chiến thuật của RtR.",
        record_key="L3F.4.007",
        base_score=0.07,
        vector_score=0.25,
        min_vector_score=0.15,
    )
    assert company is not None
    assert droneverse is None


def test_governed_definition_binding_admits_process_without_repeated_alias() -> None:
    profile = profile_query(
        "khách tier a ở booth thì chuyển cho ai",
        entities=("RtR Booth Escalation",),
        intent="lookup",
        definition_record_keys=("L3F.1.031",),
    )
    bound = candidate_relevance_score(
        profile,
        text=(
            "Luật escalation tại booth: khách Tier A chuyển CEO ngay lập tức; "
            "CEO là điểm cuối escalation."
        ),
        record_key="L3F.1.031",
        base_score=0.02,
        vector_score=0.0,
        min_vector_score=0.15,
    )
    assert bound is not None


def test_question_evidence_gate_accepts_governed_definition_binding() -> None:
    bound = ProviderEvidence(
        marker="C1",
        text="Khách Tier A chuyển CEO ngay lập tức.",
        record_key="L3F.1.031",
        provenance_level="approved_internal",
        verification_state="approved",
        freshness_state="current",
    )
    assert evidence_relevant(
        "khách tier a ở booth thì chuyển cho ai",
        [bound],
        entities=("RtR Booth Escalation",),
        intent="lookup",
        definition_record_keys=("L3F.1.031",),
    )
    assert not evidence_relevant(
        "khách tier a ở booth thì chuyển cho ai",
        [bound],
        entities=("RtR Booth Escalation",),
        intent="lookup",
        definition_record_keys=("L3F.2.019",),
    )


def test_governed_profile_binding_admits_related_cross_subject_facet() -> None:
    profile = profile_query(
        "HERA là gì?",
        entities=("HERA",),
        intent="definition",
        definition_record_keys=("HC-011",),
        profile_record_keys=("HC-011",),
    )
    sensor = candidate_relevance_score(
        profile,
        text=(
            "HeraSight LR: RGB 61MP Sony + Thermal LWIR · ISR đêm, "
            "powerline và cứu hộ."
        ),
        record_key="HC-011",
        base_score=0.01,
        vector_score=0.0,
        min_vector_score=0.15,
    )
    assert sensor is not None


def test_question_evidence_gate_tolerates_padding_after_correct_primary_hit() -> None:
    good = evidence("VEGA · Tactical heavy lifter: payload 20 kg.")
    irrelevant = evidence("Người đứng đầu công ty là CEO.", "C2")
    assert evidence_relevant("Vega là gì?", [good])
    assert evidence_relevant("Vega là gì?", [good, irrelevant])
    assert not evidence_relevant("Vega là gì?", [irrelevant])


def test_question_evidence_gate_accepts_cross_subject_padding_after_primary() -> None:
    core = evidence("HERA là nền tảng UAV đa nhiệm.")
    sensor = ProviderEvidence(
        marker="C2",
        text="HeraSight LR dùng RGB 61MP Sony và Thermal LWIR.",
        record_key="HC-011",
        provenance_level="approved_internal",
        verification_state="approved",
        freshness_state="current",
    )
    assert evidence_relevant("HERA là gì?", [core, sensor])
    assert evidence_relevant(
        "HERA là gì?",
        [core, sensor],
        profile_record_keys=("HC-011",),
    )


def test_governed_file_key_binds_workflow_rows_to_enterprise_system() -> None:
    workflow = ProviderEvidence(
        marker="C1",
        text="B6 | Sửa chữa, thay thế linh kiện và cập nhật nhật ký ca.",
        record_key="tip027.crm.service-request-process",
        provenance_level="approved_internal",
        verification_state="approved",
        freshness_state="current",
    )
    company = ProviderEvidence(
        marker="C2",
        text="Real-time Robotics (RtR) là công ty Việt Nam.",
        record_key="L3F.ENT.002",
        provenance_level="verified_primary",
        verification_state="verified",
        freshness_state="current",
    )
    assert evidence_relevant(
        "Quy trình CRM của RtR gồm các bước nào?",
        [workflow, company],
        entities=("RtR CRM", "Real-time Robotics"),
        intent="procedure",
    )


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


def test_definition_answer_allows_short_structure_before_requested_entity() -> None:
    assert answer_relevant(
        "The Sky Watch là nền tảng gì?",
        "Tổng quan\nTheSkyWatch là nền tảng dữ liệu UAV. [C1]",
        entities=("The Sky Watch",),
        intent="definition",
    )
    assert answer_relevant(
        "The Sky Watch là nền tảng gì?",
        "Theo bằng chứng, The Sky Watch là nền tảng dữ liệu UAV. [C1]",
        entities=("The Sky Watch",),
        intent="definition",
    )


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


def test_registered_original_entity_rejects_generic_rewrite_padding() -> None:
    """Recall expansions cannot steal authority from a registered entity."""
    profile = profile_query("cty có crm không")
    support = (
        "công ty có sử dụng hệ thống quản lý quan hệ khách hàng không",
        "hệ thống nội bộ của công ty",
    )
    crm = candidate_relevance_score(
        profile,
        text=(
            "RtR CRM là nền tảng sales nội bộ: quản lý contacts, companies, "
            "pipeline deal, báo giá, đơn hàng và hóa đơn."
        ),
        record_key="L3F.4.001",
        base_score=0.05,
        vector_score=0.18,
        min_vector_score=0.15,
        support_queries=support,
    )
    generic = candidate_relevance_score(
        profile,
        text="Công ty vận hành nhiều hệ thống nội bộ theo quy trình quản trị chung.",
        record_key="L3F.ENT.001",
        base_score=0.12,
        vector_score=0.35,
        min_vector_score=0.15,
        support_queries=support,
    )
    assert crm is not None
    assert generic is None


def test_structured_enterprise_file_key_supplies_governed_subject_metadata() -> None:
    """Stable dotted file ids must remain useful to generic relevance gates."""
    profile = profile_query(
        "Quy trình tiếp nhận yêu cầu dịch vụ trên CRM như thế nào?",
        entities=("RtR CRM",),
        intent="procedure",
    )
    process = candidate_relevance_score(
        profile,
        text=(
            "Tiếp nhận yêu cầu dịch vụ, phân loại, giao người phụ trách, "
            "xử lý và đóng yêu cầu sau khi khách hàng xác nhận."
        ),
        record_key="tip027.crm.service-request-process",
        base_score=0.04,
        vector_score=0.18,
        min_vector_score=0.15,
    )
    assert process is not None

    process_metadata = candidate_relevance_score(
        profile,
        text="",
        record_key="tip027.crm.service-request-process",
        base_score=0.0,
        vector_score=0.0,
        min_vector_score=0.15,
        allow_unbound_definition=True,
    )
    form_metadata = candidate_relevance_score(
        profile,
        text="",
        record_key="tip027.crm.service-request-intake-form",
        base_score=0.0,
        vector_score=0.0,
        min_vector_score=0.15,
        allow_unbound_definition=True,
    )
    assert process_metadata is not None and form_metadata is not None
    assert process_metadata > form_metadata


def test_procedure_rows_outrank_the_same_documents_cover_text() -> None:
    profile = profile_query(
        "Quy trình xử lý yêu cầu dịch vụ trên CRM như thế nào?",
        entities=("RtR CRM",),
        intent="procedure",
    )
    common = {
        "record_key": "tip027.crm.service-request-process",
        "base_score": 0.04,
        "vector_score": 0.18,
        "min_vector_score": 0.15,
    }
    cover = candidate_relevance_score(
        profile,
        text="QUY TRÌNH TIẾP NHẬN VÀ XỬ LÝ YÊU CẦU KỸ THUẬT",
        **common,
    )
    step = candidate_relevance_score(
        profile,
        text=(
            "B6 | Sửa chữa, thay thế linh kiện và ghi nhật ký | Kỹ sư | "
            "Theo SLA | BM-CSKH-04"
        ),
        **common,
    )
    assert cover is not None and step is not None and step > cover
    assert is_procedure_row("B9 | Đóng ca hỗ trợ")
    assert is_procedure_row("Step 12: archive the request")
    assert not is_procedure_row("12 ngày xử lý tối đa")


def test_original_structure_terms_select_the_right_sot_record() -> None:
    profile = profile_query("SOT bên mình tổ chức sao")
    doctrine = candidate_relevance_score(
        profile,
        text=(
            "RtR tổ chức Source of Truth theo doctrine 4 xuất xứ với các tầng "
            "L1, L2, L3 và L4."
        ),
        record_key="L3F.2.033",
        base_score=0.04,
        vector_score=0.16,
        min_vector_score=0.15,
    )
    transfer = candidate_relevance_score(
        profile,
        text="Package chuyển giao có SOT Kernel-in-a-Box và Vibecode Kit.",
        record_key="L3F.2.037",
        base_score=0.09,
        vector_score=0.28,
        min_vector_score=0.15,
    )
    assert doctrine is not None and transfer is not None and doctrine > transfer


def test_vietnamese_content_words_survive_cross_language_stopwords() -> None:
    # Accent folding turns tổ/tải/đo into tokens that happen to be English
    # stopwords. They remain discriminative Vietnamese content words here.
    assert set(profile_query("tổ chức tải trọng đo lường").terms) >= {
        "to", "chuc", "tai", "trong", "do", "luong",
    }


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


def test_collection_anchor_is_ranked_and_every_item_is_required() -> None:
    profile = profile_query(
        "các chính sách là gì",
        entities=("Annual Leave Policy",),
        intent="enumeration",
        collection_record_keys=("POLICY.CATALOG.001",),
    )
    anchor = candidate_relevance_score(
        profile,
        text="Danh mục gồm Annual Leave Policy và Travel Policy.",
        record_key="POLICY.CATALOG.001",
        base_score=0.01,
        vector_score=0.16,
        min_vector_score=0.15,
    )
    assert anchor is not None and anchor > 1
    assert collection_items_covered(
        ("Annual Leave Policy", "Travel Policy"),
        "1. Annual Leave Policy\n2. Travel Policy",
    )
    assert not collection_items_covered(
        ("Annual Leave Policy", "Travel Policy"),
        "Annual Leave Policy",
    )


class TestMetaReplyRelevance:
    """TIP-030: suggested-reply questions must not demand a canonical
    entity restatement inside the suggested reply (COM-008 class)."""

    QUESTION = "khách hỏi where are you guys from thì mình answer sao"

    def test_natural_reply_with_question_overlap_passes(self):
        from rtr_copilot.rag.relevance import answer_relevant
        answer = (
            "Bạn có thể trả lời khách: chúng tôi là công ty Việt Nam, "
            "định hướng U.S.-aligned."
        )
        assert answer_relevant(
            self.QUESTION, answer, entities=("Real-time Robotics",),
        )

    def test_reply_with_canonical_mention_passes(self):
        from rtr_copilot.rag.relevance import answer_relevant
        answer = "Real-time Robotics là công ty Việt Nam."
        assert answer_relevant(
            self.QUESTION, answer, entities=("Real-time Robotics",),
        )

    def test_unrelated_reply_is_still_rejected(self):
        from rtr_copilot.rag.relevance import answer_relevant
        answer = "Thời tiết hôm nay đẹp."
        assert not answer_relevant(
            self.QUESTION, answer, entities=("Real-time Robotics",),
        )

    def test_non_meta_question_keeps_strict_entity_rule(self):
        from rtr_copilot.rag.relevance import answer_relevant
        # Ordinary lookup: answer omitting the canonical entity still fails.
        assert not answer_relevant(
            "trụ sở công ty ở đâu",
            "Toà nhà nằm tại quận 1.",
            entities=("Real-time Robotics",),
        )
