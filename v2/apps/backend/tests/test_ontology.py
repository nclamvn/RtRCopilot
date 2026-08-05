import asyncio
import json

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
    assert company.definition_record_keys == ("L3F.ENT.002",)
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
        assert plan.resolution_state == "resolved"
        assert plan.entities == ("Real-time Robotics",)
        assert plan.entity_ids == ("rtr.company.real-time-robotics",)
        assert plan.definition_record_keys == ("L3F.ENT.002",)


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


def test_ontology_is_not_a_whitelist_for_generic_enterprise_questions() -> None:
    plan = asyncio.run(plan_query(
        "What inspection can the autonomous drone support?",
        OfflineRewriter(),
        registry=registry(),
    ))
    assert plan.resolution_state == "open"
    assert plan.entities == ()


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


def test_exact_identity_survives_external_planner_failure() -> None:
    plan = asyncio.run(plan_query(
        "OmniSight là gì?",
        FailingExternal(),
        registry=registry(),
    ))
    assert plan.resolution_state == "resolved"
    assert plan.entities == ("OmniSight",)
    assert plan.planner_source == "fallback"


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
