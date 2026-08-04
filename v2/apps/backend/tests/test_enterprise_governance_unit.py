import hashlib
import uuid

import pytest
from pydantic import ValidationError

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.enterprise.models import (
    CorpusManifestSpec,
    CorpusSourceRef,
    EvaluationCase,
    EvaluationExpectation,
    EvaluationSuiteSpec,
)
from rtr_copilot.enterprise.service import EnterpriseService
from rtr_copilot.rag.ontology import OntologyEntity, OntologySpec


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def source(kind: str, key: str) -> CorpusSourceRef:
    return CorpusSourceRef(kind=kind, source_key=key, fingerprint=sha(key))  # type: ignore[arg-type]


def test_corpus_manifest_is_order_independent_and_rejects_duplicate_identity() -> None:
    first = CorpusManifestSpec(
        domain_key="enterprise.policy",
        sources=(source("sot", "rtr.policy"), source("research", "industry.policy")),
    )
    second = CorpusManifestSpec(
        domain_key="enterprise.policy",
        sources=tuple(reversed(first.sources)),
    )
    assert first.digest == second.digest
    assert first.canonical().sources[0].kind == "research"

    with pytest.raises(ValidationError, match="enterprise_source_ref_duplicate"):
        CorpusManifestSpec(
            domain_key="enterprise.policy",
            sources=(source("sot", "rtr.policy"), source("sot", "rtr.policy")),
        )


def domain_cases(domain: str) -> tuple[EvaluationCase, ...]:
    return (
        EvaluationCase(
            case_id=f"{domain}.query",
            domain_key=domain,
            risk_class="critical",
            kind="query",
            question="Which governed policy applies?",
            expectation=EvaluationExpectation(resolution_state="open"),
        ),
        EvaluationCase(
            case_id=f"{domain}.retrieval",
            domain_key=domain,
            risk_class="high",
            kind="retrieval",
            question="Find the policy approval evidence",
            expectation=EvaluationExpectation(required_record_keys=("POLICY.001",)),
        ),
        EvaluationCase(
            case_id=f"{domain}.answer",
            domain_key=domain,
            risk_class="standard",
            kind="answer",
            question="Summarize the approved policy",
            expectation=EvaluationExpectation(
                answer_state="grounded",
                required_record_keys=("POLICY.001",),
            ),
        ),
    )


def test_suite_enforces_domain_stratification_not_product_examples() -> None:
    cases = (*domain_cases("policy"), *domain_cases("customer"), *domain_cases("project"))
    suite = EvaluationSuiteSpec(suite_key="enterprise.release", cases=cases)
    assert suite.coverage_errors({"policy": 3, "customer": 3, "project": 3}) == []
    assert (
        suite.digest
        == EvaluationSuiteSpec(
            suite_key="enterprise.release",
            cases=tuple(reversed(cases)),
        ).digest
    )

    query_only = EvaluationSuiteSpec(
        suite_key="enterprise.incomplete",
        cases=(domain_cases("policy")[0],),
    )
    assert query_only.coverage_errors({"policy": 1}) == [
        "domain_kind_missing:policy:retrieval",
        "domain_kind_missing:policy:answer",
    ]


def test_ontology_alias_collision_requires_an_explicit_ambiguity_case() -> None:
    ontology = OntologySpec(
        schema_version=1,
        registry_id="enterprise.registry",
        owner="Enterprise Architecture",
        entities=(
            OntologyEntity(
                entity_id="policy.alpha",
                canonical_name="Alpha Policy",
                entity_type="policy",
                domain="policy",
                aliases=("Common",),
                owner="Policy",
                provenance_level="approved_internal",
            ),
            OntologyEntity(
                entity_id="project.common",
                canonical_name="Common Project",
                entity_type="project",
                domain="project",
                aliases=("Common",),
                owner="PMO",
                provenance_level="approved_internal",
            ),
        ),
    )
    suite = EvaluationSuiteSpec(
        suite_key="enterprise.aliases",
        cases=domain_cases("policy"),
    )
    assert len(suite.ambiguity_coverage_errors(ontology)) == 1

    covered = EvaluationSuiteSpec(
        suite_key="enterprise.aliases.covered",
        cases=(
            *domain_cases("policy"),
            EvaluationCase(
                case_id="policy.common.ambiguous",
                domain_key="policy",
                risk_class="critical",
                kind="query",
                question="Common là gì?",
                expectation=EvaluationExpectation(
                    resolution_state="clarification_required",
                ),
            ),
        ),
    )
    assert covered.ambiguity_coverage_errors(ontology) == []


@pytest.mark.asyncio
async def test_full_active_ontology_payload_requires_a_governance_role() -> None:
    actor = uuid.uuid4()
    staff = Subject(
        user_id=str(actor),
        issuer="unit",
        sub=actor.hex,
        email="staff@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={Role.STAFF},
    )
    with pytest.raises(PermissionError, match="governance_role_required"):
        await EnterpriseService().active_ontology(staff, request_id="tip025-role-gate")
