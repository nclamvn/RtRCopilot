"""Activate a resumable, evidence-bound enterprise governance release."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.enterprise.models import (
    CorpusManifestSpec,
    CorpusSourceRef,
    DecisionInput,
    DomainCreate,
    EvaluationSuiteSpec,
)
from rtr_copilot.enterprise.repository import EnterpriseError
from rtr_copilot.enterprise.service import EnterpriseService
from rtr_copilot.rag.ontology import OntologySpec

PACKAGE_ROOT = Path(__file__).parents[1]
DEFAULT_PLAN = PACKAGE_ROOT / "enterprise" / "release_plan.json"
DEFAULT_ONTOLOGY = PACKAGE_ROOT / "rag" / "enterprise_ontology.json"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DomainPlan(StrictModel):
    domain_key: str
    display_name: str
    description: str
    classification: str = "internal"
    minimum_eval_cases: int = Field(ge=3)
    sot_sources: tuple[str, ...] = Field(min_length=1)


class ReleasePlan(StrictModel):
    schema_version: int = 1
    release_key: str
    domains: tuple[DomainPlan, ...] = Field(min_length=1)
    suite: EvaluationSuiteSpec


def _subject(actor_id: uuid.UUID, role: Role, label: str) -> Subject:
    return Subject(
        user_id=str(actor_id),
        issuer="tip031-local-governance",
        sub=actor_id.hex,
        email=f"tip031-{label}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        display_name=f"TIP-031 {label.title()}",
        roles={role},
    )


async def _seed_actors(service: EnterpriseService) -> tuple[Subject, Subject]:
    curator_id = uuid.uuid5(uuid.NAMESPACE_URL, "rtr:tip031:curator")
    leader_id = uuid.uuid5(uuid.NAMESPACE_URL, "rtr:tip031:leader")
    async with service.uow.transaction() as session:
        for actor_id, label in ((curator_id, "curator"), (leader_id, "leader")):
            await session.execute(text("""
                INSERT INTO subjects(
                  user_id,issuer,provider_sub,email,canonical_domain,display_name,status
                ) VALUES (
                  :id,'tip031-local-governance',:sub,:email,'rtrobotics.com',:name,'active'
                ) ON CONFLICT (user_id) DO UPDATE SET
                  email=EXCLUDED.email,display_name=EXCLUDED.display_name,status='active'
            """), {
                "id": actor_id,
                "sub": actor_id.hex,
                "email": f"tip031-{label}@rtrobotics.com",
                "name": f"TIP-031 {label.title()}",
            })
    return _subject(curator_id, Role.CURATOR, "curator"), _subject(
        leader_id, Role.LEADER, "leader",
    )


async def _source_refs(
    service: EnterpriseService,
    source_keys: tuple[str, ...],
) -> tuple[CorpusSourceRef, ...]:
    refs: list[CorpusSourceRef] = []
    async with service.uow.factory() as session:
        for source_key in source_keys:
            fingerprint = await service.repository.current_source_fingerprint(
                session, "sot", source_key,
            )
            if fingerprint is None:
                raise RuntimeError(f"enterprise_source_unavailable:{source_key}")
            refs.append(CorpusSourceRef(
                kind="sot", source_key=source_key, fingerprint=fingerprint,
            ))
    return tuple(refs)


async def _existing_id(
    service: EnterpriseService,
    query: str,
    parameters: dict[str, Any],
) -> uuid.UUID | None:
    async with service.uow.factory() as session:
        value = await session.scalar(text(query), parameters)
    return uuid.UUID(str(value)) if value else None


async def _ensure_domain(
    service: EnterpriseService,
    curator: Subject,
    leader: Subject,
    plan: DomainPlan,
) -> Any:
    domain = None
    async with service.uow.factory() as session:
        domain = await service.repository.domain_by_key(session, plan.domain_key)
    if domain is None:
        domain = await service.propose_domain(
            curator,
            DomainCreate(
                domain_key=plan.domain_key,
                display_name=plan.display_name,
                description=plan.description,
                owner_subject_id=uuid.UUID(curator.user_id),
                classification=plan.classification,  # type: ignore[arg-type]
                minimum_eval_cases=plan.minimum_eval_cases,
            ),
            request_id=f"tip031-domain:{plan.domain_key}",
        )
    if domain.state == "proposed":
        domain = await service.decide_domain(
            leader,
            domain.domain_id,
            DecisionInput(decision="approved", reason="TIP-031 independent domain review"),
            request_id=f"tip031-domain-approve:{plan.domain_key}",
        )
    if domain.state != "active" or domain.minimum_eval_cases != plan.minimum_eval_cases:
        raise RuntimeError(f"enterprise_domain_drift:{plan.domain_key}")
    return domain


async def _ensure_manifest(
    service: EnterpriseService,
    curator: Subject,
    leader: Subject,
    plan: DomainPlan,
) -> Any:
    refs = await _source_refs(service, plan.sot_sources)
    spec = CorpusManifestSpec(domain_key=plan.domain_key, sources=refs)
    manifest_id = await _existing_id(
        service,
        """SELECT m.manifest_id FROM enterprise_corpus_manifests m
           JOIN enterprise_domains d ON d.domain_id=m.domain_id
           WHERE d.domain_key=:key AND m.version=1
           ORDER BY m.proposed_at DESC LIMIT 1""",
        {"key": plan.domain_key},
    )
    manifest = None
    if manifest_id:
        async with service.uow.factory() as session:
            manifest = await service.repository.manifest_by_id(session, manifest_id)
    if manifest is None:
        manifest = await service.propose_manifest(
            curator, spec, version=1,
            request_id=f"tip031-manifest:{plan.domain_key}",
        )
    if manifest.manifest_digest != spec.digest:
        raise RuntimeError(f"enterprise_manifest_drift:{plan.domain_key}")
    if manifest.state == "proposed":
        await service.validate_manifest(
            curator, manifest.manifest_id,
            request_id=f"tip031-manifest-validate:{plan.domain_key}",
        )
        async with service.uow.factory() as session:
            manifest = await service.repository.manifest_by_id(
                session, manifest.manifest_id,
            )
    if manifest is not None and manifest.state == "validated":
        manifest = await service.decide_manifest(
            leader,
            manifest.manifest_id,
            DecisionInput(decision="approved", reason="TIP-031 fingerprints reviewed"),
            request_id=f"tip031-manifest-approve:{plan.domain_key}",
        )
    if manifest is None or manifest.state != "active":
        raise RuntimeError(f"enterprise_manifest_inactive:{plan.domain_key}")
    return manifest


async def _ensure_ontology(
    service: EnterpriseService,
    curator: Subject,
    leader: Subject,
    ontology: OntologySpec,
) -> Any:
    revision_id = await _existing_id(
        service,
        """SELECT revision_id FROM enterprise_ontology_revisions
           WHERE registry_id=:registry AND version=1 LIMIT 1""",
        {"registry": ontology.registry_id},
    )
    revision = None
    if revision_id:
        async with service.uow.factory() as session:
            revision = await service.repository.ontology_by_id(session, revision_id)
    if revision is None:
        revision = await service.propose_ontology(
            curator, ontology, version=1, request_id="tip031-ontology",
        )
    if revision.payload != ontology:
        raise RuntimeError("enterprise_ontology_drift")
    if revision.state == "proposed":
        revision = await service.decide_ontology(
            leader,
            revision.revision_id,
            DecisionInput(decision="approved", reason="TIP-031 ontology reviewed"),
            request_id="tip031-ontology-approve",
        )
    if revision.state not in {"approved", "active"}:
        raise RuntimeError("enterprise_ontology_not_approved")
    return revision


async def _ensure_suite(
    service: EnterpriseService,
    curator: Subject,
    leader: Subject,
    suite_spec: EvaluationSuiteSpec,
) -> Any:
    suite_id = await _existing_id(
        service,
        """SELECT suite_id FROM enterprise_evaluation_suites
           WHERE suite_key=:key AND version=1 LIMIT 1""",
        {"key": suite_spec.suite_key},
    )
    suite = None
    if suite_id:
        async with service.uow.factory() as session:
            suite = await service.repository.suite_by_id(session, suite_id)
    if suite is None:
        suite = await service.propose_suite(
            curator, suite_spec, version=1, request_id="tip031-suite",
        )
    if suite.suite_digest != suite_spec.digest:
        raise RuntimeError("enterprise_suite_drift")
    if suite.state == "proposed":
        suite = await service.decide_suite(
            leader,
            suite.suite_id,
            DecisionInput(decision="approved", reason="TIP-031 matrix reviewed"),
            request_id="tip031-suite-approve",
        )
    if suite.state != "approved":
        raise RuntimeError("enterprise_suite_not_approved")
    return suite


async def bootstrap(plan_path: Path, ontology_path: Path) -> dict[str, Any]:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("enterprise_bootstrap_local_only")
    plan = ReleasePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    ontology = OntologySpec.model_validate_json(
        ontology_path.read_text(encoding="utf-8"),
    )
    service = EnterpriseService()
    curator, leader = await _seed_actors(service)

    readiness = await service.readiness(leader, request_id="tip031-readiness-before")
    if readiness.ready:
        active = await service.active_ontology(
            leader, request_id="tip031-active-ontology",
        )
        if active.payload != ontology:
            raise RuntimeError("enterprise_active_release_drift")
        return {"mode": "idempotent", "readiness": readiness.model_dump(mode="json")}

    domains = []
    manifests = []
    for domain_plan in plan.domains:
        domain = await _ensure_domain(service, curator, leader, domain_plan)
        domains.append(str(domain.domain_id))
        manifest = await _ensure_manifest(service, curator, leader, domain_plan)
        manifests.append(str(manifest.manifest_id))

    revision = await _ensure_ontology(service, curator, leader, ontology)
    if revision.state == "active":
        readiness = await service.readiness(leader, request_id="tip031-readiness-active")
        return {"mode": "idempotent", "readiness": readiness.model_dump(mode="json")}
    suite = await _ensure_suite(service, curator, leader, plan.suite)
    run = await service.run_suite(
        curator, suite.suite_id, revision.revision_id,
        request_id="tip031-release-evaluation",
    )
    if run.status != "passed":
        return {
            "mode": "evaluation_failed",
            "run": run.model_dump(mode="json"),
            "domains": domains,
            "manifests": manifests,
        }
    release = await service.activate_ontology(
        leader,
        revision.revision_id,
        run.run_id,
        reason="TIP-031 domain-stratified release passed",
        request_id="tip031-release-activate",
    )
    readiness = await service.readiness(leader, request_id="tip031-readiness-after")
    return {
        "mode": "activated",
        "run": run.model_dump(mode="json"),
        "release": release.model_dump(mode="json"),
        "readiness": readiness.model_dump(mode="json"),
        "domains": domains,
        "manifests": manifests,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.approve:
        parser.error("bootstrap requires --approve")
    try:
        result = asyncio.run(bootstrap(args.plan, args.ontology))
    except EnterpriseError as error:
        raise SystemExit(f"ENTERPRISE RELEASE FAIL · {error.code}") from error
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report:
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if result["mode"] == "evaluation_failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
