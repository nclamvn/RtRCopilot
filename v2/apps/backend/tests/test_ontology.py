import asyncio
import json

import pytest

from rtr_copilot.rag.ontology import EnterpriseOntology, OntologySpec, load_ontology
from rtr_copilot.rag.query_understanding import (
    OfflineRewriter,
    RewriteResult,
    plan_query,
    resolve_entities,
)


def registry() -> EnterpriseOntology:
    return EnterpriseOntology(OntologySpec.model_validate({
        "schema_version": 1,
        "registry_id": "test.enterprise-ontology",
        "owner": "curator:test",
        "entities": [
            {
                "entity_id": "test.product.omnisight",
                "canonical_name": "OmniSight",
                "entity_type": "product",
                "domain": "products",
                "aliases": ["omnisight", "omni sight"],
                "owner": "curator:products",
                "provenance_level": "verified_primary",
            },
            {
                "entity_id": "test.policy.leave",
                "canonical_name": "Annual Leave Policy",
                "entity_type": "policy",
                "domain": "people",
                "aliases": ["leave policy", "quy định nghỉ phép"],
                "owner": "curator:people",
                "provenance_level": "approved_internal",
            },
            {
                "entity_id": "test.project.phoenix",
                "canonical_name": "Project Phoenix",
                "entity_type": "project",
                "domain": "projects",
                "aliases": ["phoenix"],
                "owner": "curator:projects",
                "provenance_level": "approved_internal",
            },
            {
                "entity_id": "test.customer.phoenix",
                "canonical_name": "Phoenix Industries",
                "entity_type": "customer",
                "domain": "customers",
                "aliases": ["phoenix"],
                "owner": "curator:customers",
                "provenance_level": "approved_internal",
            },
        ],
        "collections": [
            {
                "collection_id": "test.catalog.people-policies",
                "canonical_name": "People policy catalog",
                "domain": "people",
                "aliases": ["all people policies", "danh sách chính sách nhân sự"],
                "members": [
                    {
                        "name": "Annual Leave Policy",
                        "kind": "policy",
                        "entity_id": "test.policy.leave",
                    },
                ],
                "record_keys": ["POLICY.CATALOG.001"],
                "owner": "curator:people",
                "provenance_level": "approved_internal",
            },
        ],
    }))


class ExternalStub:
    external = True

    def __init__(self, entities: list[str]) -> None:
        self.calls = 0
        self.entities = entities

    async def rewrite(self, question: str) -> RewriteResult:
        self.calls += 1
        return RewriteResult(entities=self.entities)


class FailingExternal:
    external = True
    calls = 0

    async def rewrite(self, question: str) -> RewriteResult:
        self.calls += 1
        raise RuntimeError("planner unavailable")


class PlanStub:
    external = True

    def __init__(self, result: RewriteResult) -> None:
        self.calls = 0
        self.result = result

    async def rewrite(self, question: str) -> RewriteResult:
        del question
        self.calls += 1
        return self.result


def test_registry_is_domain_agnostic_and_data_driven() -> None:
    ontology = registry()
    matches = ontology.exact_matches("Quy định nghỉ phép áp dụng thế nào?")
    assert [(item.entity_type, item.domain, item.entity_id) for item in matches] == [
        ("policy", "people", "test.policy.leave"),
    ]
    assert ontology.exact_matches("Project Phoenix")
    assert ontology.exact_matches("Phoenix Industries")


def test_packaged_registry_resolves_rtr_as_the_company_identity() -> None:
    ontology = load_ontology()
    company = ontology.by_id["rtr.company.real-time-robotics"]
    assert company.entity_type == "company"
    assert company.domain == "company"
    assert {
        "L3F.ENT.001", "L3F.ENT.002", "L3F.BRD.002", "L3F.1.019",
        "L3F.1.020", "L3F.1.023", "L3F.RES.004", "L3F.REC.001",
    } == set(company.definition_record_keys)
    for question in (
        "rtr là gì?",
        "RtR là gì?",
        "RTR là gì?",
        "Real time Robotics là gì?",
        "Real-time Robotics là gì?",
    ):
        plan = asyncio.run(plan_query(
            question,
            OfflineRewriter(),
            registry=ontology,
        ))
        assert plan.resolution_state == "planning_required"
        assert plan.entities == ("Real-time Robotics",)
        assert plan.entity_ids == ("rtr.company.real-time-robotics",)
        assert set(plan.definition_record_keys) == set(company.definition_record_keys)
        assert len(plan.profile_facets) == 6


def test_packaged_registry_resolves_ordinary_enterprise_descriptions() -> None:
    ontology = load_ontology()
    cases = {
        "cty mình tên pháp nhân đầy đủ là gì": "Real-time Robotics",
        "app quản lý sáng chế là app nào": "RtR IP",
        "Control Tower dùng làm gì": "RtR Control Tower",
        "The Sky Watch là nền tảng gì": "The Sky Watch",
        "Sales Brief bên mình là hệ thống gì": "RtR Sales Brief",
        "SOT bên mình tổ chức sao": "SOT Kernel-in-a-Box",
        "audit trước meeting khách lớn có mấy vai": (
            "Adversarial Audit Checklist"
        ),
        "gói chuyển giao phương pháp lõi gồm gì": "RtR Core Method Package",
        "mấy con số bảo dưỡng này chốt mandatory chưa": (
            "Chương trình bảo dưỡng RtR"
        ),
        "lộ trình đưa chương trình bảo dưỡng vào vận hành bao lâu": (
            "Chương trình bảo dưỡng RtR"
        ),
        "quy trình xử lý lead ở booth diễn ra sao": "RtR Booth Lead Capture",
        "deck phải được bao nhiêu điểm": "RtR Deck Readiness Scorecard",
    }
    for question, expected in cases.items():
        plan = asyncio.run(plan_query(
            question,
            OfflineRewriter(),
            registry=ontology,
        ))
        assert expected in plan.entities
        assert plan.definition_record_keys


def test_bare_ip_is_a_governed_collision_not_a_silent_guess() -> None:
    plan = asyncio.run(plan_query(
        "IP là gì?",
        OfflineRewriter(),
        registry=load_ontology(),
    ))
    assert plan.resolution_state == "clarification_required"
    assert plan.entities == ()
    assert {item.canonical_name for item in plan.candidates} == {
        "Ingress Protection", "RtR IP",
    }


def test_external_planner_cannot_choose_one_side_of_governed_collision() -> None:
    for question, proposed in (
        ("IP là gì?", ["RtR IP"]),
        ("Sight là gì?", ["HeraSight"]),
    ):
        plan = asyncio.run(plan_query(
            question,
            PlanStub(RewriteResult(
                entities=proposed,
                intent="definition",
                answer_shape="direct",
            )),
            registry=load_ontology(),
        ))
        assert plan.resolution_state == "clarification_required"
        assert plan.entities == ()


def test_company_owner_scope_is_not_a_required_answer_subject() -> None:
    plan = asyncio.run(plan_query(
        "Quy trình CRM của RtR gồm các bước nào?",
        OfflineRewriter(),
        registry=load_ontology(),
    ))
    assert plan.entities == ("RtR CRM", "Real-time Robotics")
    assert plan.entity_types == ("enterprise_system", "company")
    assert plan.retrieval_entities == ("RtR CRM", "Real-time Robotics")
    assert plan.answer_entities == ("RtR CRM",)


def test_company_remains_answer_subject_when_it_is_the_only_entity() -> None:
    plan = asyncio.run(plan_query(
        "RtR là gì?",
        OfflineRewriter(),
        registry=load_ontology(),
    ))
    assert plan.answer_entities == ("Real-time Robotics",)


def test_external_planner_cannot_override_explicit_procedure_with_catalog() -> None:
    plan = asyncio.run(plan_query(
        "Quy trình CRM của RtR gồm các bước nào?",
        PlanStub(RewriteResult(
            entities=["RtR CRM", "Real-time Robotics"],
            intent="enumeration",
            completeness="bounded",
            answer_shape="list",
            collections=["Danh mục sản phẩm RtR"],
        )),
        registry=load_ontology(),
    ))
    assert plan.intent == "procedure"
    assert plan.answer_shape == "steps"
    assert plan.collection_ids == ()
    assert plan.required_items == ()


def test_core_method_package_has_a_governed_collection_contract() -> None:
    plan = asyncio.run(plan_query(
        "gói chuyển giao phương pháp lõi gồm những gì?",
        PlanStub(RewriteResult(
            entities=["RtR Core Method Package"],
            intent="enumeration",
            completeness="bounded",
            answer_shape="list",
            collections=["Danh mục phương pháp lõi RtR"],
        )),
        registry=load_ontology(),
    ))
    assert plan.collection_ids == ("rtr.catalog.core-methods",)
    assert plan.required_items == (
        "SOT Kernel-in-a-Box", "Refinery", "Vibecode Kit", "Văn bản Nhà nước",
    )


def test_profiled_entity_definition_upgrades_to_governed_bounded_summary() -> None:
    ontology = load_ontology()
    plan = asyncio.run(plan_query(
        "HERA là gì?",
        PlanStub(RewriteResult(
            entities=["HERA"],
            intent="definition",
            completeness="point",
            answer_shape="direct",
        )),
        registry=ontology,
    ))

    assert plan.resolution_state == "resolved"
    assert plan.completeness == "bounded"
    assert plan.answer_shape == "summary"
    assert plan.requires_synthesis
    assert len(plan.profile_facets) == 12
    assert {facet.facet_id for facet in plan.profile_facets} == {
        "overview", "core_specs", "deployment", "control", "sensing",
        "applications", "compliance", "battery", "commercial", "maintenance",
        "warranty", "roadmap",
    }
    assert set(plan.profile_record_keys) == {
        "L3F.PRD.001", "HC-001", "HC-004", "HC-017", "HC-011", "HC-050",
        "L3F.1.008", "L3F.RES.003", "L3F.2.007", "L3F.2.009",
        "L3F.2.015", "PRICE.HERA.MSRP.US", "L3F.2.022",
    }
    assert set(plan.profile_record_keys) <= set(plan.definition_record_keys)
    assert "Tổng quan" in plan.profile_facets[0].presentation_labels
    assert "Overview" in plan.profile_facets[0].presentation_labels
    audit = plan.audit_metadata()
    assert audit["profile_facet_count"] == 12
    assert audit["profile_record_count"] == 13
    assert "HERA" not in json.dumps(audit)


def test_unprofiled_entity_definition_stays_point_direct() -> None:
    plan = asyncio.run(plan_query(
        "OmniSight là gì?",
        ExternalStub(["OmniSight"]),
        registry=registry(),
    ))
    assert plan.profile_facets == ()
    assert plan.profile_record_keys == ()
    assert plan.completeness == "point"
    assert plan.answer_shape == "direct"
    assert not plan.requires_synthesis


@pytest.mark.parametrize(("question", "facet_id", "record_key"), [
    ("pin HERA là 44.4V hay 50.4V?", "battery", "L3F.2.015"),
    ("giá list HERA bên Mỹ hiện là bao nhiêu vậy", "commercial", "PRICE.HERA.MSRP.US"),
    ("tên file sales brief đặt kiểu gì", "file_naming", "L3F.2.003"),
    ("sales brief chấm điểm cơ hội ở ô nào", "opportunity_score", "L3F.2.004"),
    (
        "The Sky Watch có bao nhiêu gate kiểm dữ liệu trước deploy?",
        "data_governance",
        "L3F.3.007",
    ),
    ("cty mình tên pháp nhân đầy đủ là gì vậy", "identity", "L3F.ENT.001"),
    ("email cty là gì", "contact", "L3F.1.019"),
    (
        "khách hỏi where are you guys from thì mình answer sao",
        "positioning",
        "L3F.1.023",
    ),
    ("MRP làm được gì", "capabilities", "L3F.4.003"),
    (
        "công ty có thành tựu hay dấu công nhận gì nổi bật?",
        "recognition",
        "L3F.REC.001",
    ),
])
def test_point_attribute_alias_routes_to_governed_facet(
    question: str,
    facet_id: str,
    record_key: str,
) -> None:
    plan = asyncio.run(plan_query(question, OfflineRewriter(), registry=load_ontology()))
    assert plan.intent == "lookup"
    assert plan.completeness == "point"
    assert plan.answer_shape == "direct"
    assert {facet.facet_id for facet in plan.profile_facets} == {facet_id}
    assert record_key in plan.profile_record_keys
    assert record_key in plan.definition_record_keys


def test_stability_facets_declare_governed_material_checkpoints() -> None:
    ontology = load_ontology()
    company = ontology.by_id["rtr.company.real-time-robotics"]
    positioning = next(
        facet for facet in company.profile_facets if facet.facet_id == "positioning"
    )
    mrp = ontology.by_id["rtr.system.mrp"]
    capabilities = next(
        facet for facet in mrp.profile_facets if facet.facet_id == "capabilities"
    )

    assert len(positioning.coverage_term_groups) == 4
    assert len(capabilities.coverage_term_groups) == 5
    assert ("U.S.-aligned", "U.S. aligned") in positioning.coverage_term_groups
    assert ("dự báo AI/ML", "Gemini/OpenAI") in capabilities.coverage_term_groups


@pytest.mark.parametrize(("question", "planner_intent", "facet_id"), [
    ("pin HERA là 44.4V hay 50.4V?", "comparison", "battery"),
    ("tên file sales brief đặt kiểu gì", "procedure", "file_naming"),
])
def test_governed_point_facet_overrides_broader_external_planner_intent(
    question: str,
    planner_intent: str,
    facet_id: str,
) -> None:
    plan = asyncio.run(plan_query(
        question,
        PlanStub(RewriteResult(
            intent=planner_intent,
            completeness="bounded",
            answer_shape="summary",
        )),
        registry=load_ontology(),
    ))
    assert plan.intent == "lookup"
    assert plan.completeness == "point"
    assert plan.answer_shape == "direct"
    assert {facet.facet_id for facet in plan.profile_facets} == {facet_id}


def test_spacing_casing_and_safe_typo_resolve_same_entity() -> None:
    ontology = registry()
    for question in ("OmniSight là gì?", "OMNI SIGHT là gì?", "omnisigt là gì?"):
        assert resolve_entities(question, ontology) == ["OmniSight"]


def test_colliding_alias_is_never_first_match_wins() -> None:
    ontology = registry()
    assert resolve_entities("phoenix là gì?", ontology) == []
    candidates = ontology.candidate_matches("phoenix là gì?")
    assert {item.entity_id for item in candidates} == {
        "test.project.phoenix", "test.customer.phoenix",
    }


def test_partial_name_requires_clarification_without_external_confirmation() -> None:
    plan = asyncio.run(plan_query(
        "Omni là gì?",
        OfflineRewriter(),
        registry=registry(),
    ))
    assert plan.resolution_state == "clarification_required"
    assert plan.entities == ()
    assert [item.canonical_name for item in plan.candidates] == ["OmniSight"]


def test_whole_word_inside_long_alias_is_not_a_partial_entity_signal() -> None:
    """Common complete words must not become hidden fail-closed ambiguity."""
    packaged = load_ontology()
    ontology = EnterpriseOntology(OntologySpec(
        schema_version=1,
        registry_id="test.project-token-boundary",
        owner="curator:test",
        entities=(packaged.by_id["rtr.project.cangio"],),
    ))
    candidates = ontology.candidate_matches(
        "Đề xuất UAV-IOC Hải Phòng gồm những nội dung gì?"
    )
    assert not any(
        item.entity_id == "rtr.project.cangio" and item.match_kind == "partial"
        for item in candidates
    )


def test_new_city_projects_are_registry_bound_to_approved_files() -> None:
    ontology = load_ontology()
    expected = {
        "rtr.project.haiphong-uav-ioc": "tip027.project.haiphong-uav-ioc-v4",
        "rtr.project.quangninh-uav-ioc": "tip027.project.quangninh-uav-ioc-v4",
    }
    for entity_id, record_key in expected.items():
        entity = ontology.by_id[entity_id]
        assert entity.definition_record_keys == (record_key,)


def test_ontology_is_not_a_whitelist_for_generic_enterprise_questions() -> None:
    plan = asyncio.run(plan_query(
        "What inspection can the autonomous drone support?",
        OfflineRewriter(),
        registry=registry(),
    ))
    assert plan.resolution_state == "open"
    assert plan.entities == ()


def test_external_planner_cannot_turn_missing_ontology_entry_into_ambiguity() -> None:
    plan = asyncio.run(plan_query(
        "cty có crm không",
        PlanStub(RewriteResult(
            intent="lookup",
            completeness="point",
            answer_shape="direct",
            retrieval_queries=["CRM contacts pipeline"],
            clarification_required=True,
        )),
        registry=registry(),
    ))
    assert plan.resolution_state == "open"
    assert plan.entities == ()
    assert "CRM contacts pipeline" in plan.retrieval_query


def test_ordinary_enumeration_is_bounded_but_requires_semantic_synthesis() -> None:
    plan = asyncio.run(plan_query(
        "Các sản phẩm của RtR là gì?",
        OfflineRewriter(),
        registry=load_ontology(),
    ))
    assert plan.intent == "enumeration"
    assert plan.completeness == "bounded"
    assert plan.coverage_policy == "best_effort"
    assert plan.answer_shape == "list"
    assert plan.resolution_state == "planning_required"


def test_external_plan_binds_governed_collection_and_coverage() -> None:
    for question in (
        "Các sản phẩm của RtR là gì?",
        "rtr co nhung san pham nao vay, liet ke het giup minh",
        "What products does RTR have? Give me the complete list.",
    ):
        plan = asyncio.run(plan_query(
            question,
            PlanStub(RewriteResult(
                entities=["Real-time Robotics"],
                collections=["Danh mục sản phẩm RtR"],
                intent="enumeration",
                completeness="exhaustive",
                answer_shape="list",
                retrieval_queries=["danh mục sản phẩm hiện hành"],
            )),
            registry=load_ontology(),
        ))
        assert plan.resolution_state == "resolved"
        assert plan.collection_ids == ("rtr.catalog.product-portfolio",)
        assert plan.collection_record_keys == ("L3R.2.005",)
        assert len(plan.required_items) == 16
        assert "OmniSight" in plan.required_items
        # The portfolio grows as governed product definitions are admitted;
        # the contract is coverage of the canonical set, not a frozen count.
        assert len(plan.definition_record_keys) >= 11
        assert "L3F.ENT.002" not in plan.definition_record_keys
        assert {"HC-001", "HC-002", "L3F.1.011", "HC-013", "HC-058"} <= set(
            plan.definition_record_keys
        )
        assert plan.requires_synthesis


def test_only_explicit_user_wording_can_require_exhaustive_coverage() -> None:
    ordinary = asyncio.run(plan_query(
        "Các sản phẩm của RtR là gì?",
        PlanStub(RewriteResult(
            entities=["Real-time Robotics"],
            collections=["Danh mục sản phẩm RtR"],
            intent="enumeration",
            completeness="exhaustive",
            answer_shape="list",
        )),
        registry=load_ontology(),
    ))
    explicit = asyncio.run(plan_query(
        "Liệt kê toàn bộ sản phẩm của RtR, không thiếu mục nào",
        PlanStub(RewriteResult(
            entities=["Real-time Robotics"],
            collections=["Danh mục sản phẩm RtR"],
            intent="enumeration",
            completeness="bounded",
            answer_shape="list",
        )),
        registry=load_ontology(),
    ))

    assert ordinary.completeness == "bounded"
    assert ordinary.coverage_policy == "best_effort"
    assert explicit.completeness == "exhaustive"
    assert explicit.coverage_policy == "require_complete"


def test_lookup_follow_up_cannot_inherit_a_planner_collection() -> None:
    plan = asyncio.run(plan_query(
        "thế nó bay được bao lâu?",
        PlanStub(RewriteResult(
            entities=["HERA"],
            collections=["Danh mục sản phẩm RtR"],
            intent="lookup",
            completeness="point",
            answer_shape="direct",
            standalone_question="HERA bay được bao lâu?",
        )),
        registry=load_ontology(),
        conversation_context=(
            "user: HERA là gì?",
            "assistant: HERA là nền tảng UAV đa nhiệm.",
        ),
    ))
    assert plan.entities == ("HERA",)
    assert plan.collection_ids == ()
    assert plan.required_entities == ()
    assert plan.collection_record_keys == ()
    assert plan.intent == "lookup"


def test_non_product_collection_uses_same_generic_contract() -> None:
    plan = asyncio.run(plan_query(
        "Danh sách chính sách nhân sự",
        PlanStub(RewriteResult(
            collections=["People policy catalog"],
            intent="enumeration",
            completeness="exhaustive",
            answer_shape="list",
        )),
        registry=registry(),
    ))
    assert plan.collection_ids == ("test.catalog.people-policies",)
    assert plan.required_items == ("Annual Leave Policy",)
    assert plan.required_entities == ("Annual Leave Policy",)


def test_compound_word_does_not_become_partial_registered_entity() -> None:
    plan = asyncio.run(plan_query(
        "What timeout evidence is current?",
        OfflineRewriter(),
        registry=load_ontology(),
    ))
    assert plan.resolution_state == "open"
    assert plan.entities == ()
    assert all(item.match_kind == "candidate" for item in plan.candidates)


def test_generic_drone_term_does_not_become_partial_project_name() -> None:
    plan = asyncio.run(plan_query(
        "What inspection can the autonomous drone support?",
        OfflineRewriter(),
        registry=load_ontology(),
    ))
    assert plan.resolution_state == "open"
    assert plan.entities == ()
    assert all(item.match_kind == "candidate" for item in plan.candidates)


def test_colliding_exact_alias_requires_clarification() -> None:
    plan = asyncio.run(plan_query(
        "Phoenix là gì?",
        OfflineRewriter(),
        registry=registry(),
    ))
    assert plan.resolution_state == "clarification_required"
    assert plan.entities == ()
    assert {item.entity_id for item in plan.candidates} == {
        "test.project.phoenix", "test.customer.phoenix",
    }


def test_bounded_external_confirmation_becomes_one_semantic_contract() -> None:
    plan = asyncio.run(plan_query(
        "Omni là gì?",
        ExternalStub(["OmniSight"]),
        registry=registry(),
    ))
    assert plan.resolution_state == "resolved"
    assert plan.entities == ("OmniSight",)
    assert plan.entity_ids == ("test.product.omnisight",)
    assert "OmniSight" in plan.retrieval_query


def test_external_entity_outside_bounded_candidates_is_discarded() -> None:
    plan = asyncio.run(plan_query(
        "Omni là gì?",
        ExternalStub(["Annual Leave Policy"]),
        registry=registry(),
    ))
    assert plan.resolution_state == "clarification_required"
    assert plan.entities == ()


def test_external_planner_cannot_promote_weak_similarity_to_identity() -> None:
    plan = asyncio.run(plan_query(
        "annual evidence status",
        ExternalStub(["Annual Leave Policy"]),
        registry=registry(),
    ))
    assert plan.candidates
    assert all(item.match_kind == "candidate" for item in plan.candidates)
    assert plan.resolution_state == "open"
    assert plan.entities == ()


def test_exact_identity_survives_external_planner_failure() -> None:
    plan = asyncio.run(plan_query(
        "OmniSight là gì?",
        FailingExternal(),
        registry=registry(),
    ))
    assert plan.resolution_state == "resolved"
    assert plan.entities == ("OmniSight",)
    assert plan.planner_source == "deterministic"


def test_audit_metadata_contains_no_query_or_catalog_plaintext() -> None:
    plan = asyncio.run(plan_query(
        "Omni là gì?",
        ExternalStub(["OmniSight"]),
        registry=registry(),
    ))
    serialized = json.dumps(plan.audit_metadata())
    assert "Omni" not in serialized
    assert "Phoenix" not in serialized
    assert len(plan.audit_metadata()["plan_digest"]) == 64
