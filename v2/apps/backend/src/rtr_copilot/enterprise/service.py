"""Policy-enforced enterprise onboarding, evaluation and release workflow."""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Role, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.enterprise.models import (
    CorpusManifestRecord,
    CorpusManifestSpec,
    DecisionInput,
    DomainCreate,
    DomainRecord,
    EnterpriseReadiness,
    EvaluationCase,
    EvaluationRunRecord,
    EvaluationStatus,
    EvaluationSuiteRecord,
    EvaluationSuiteSpec,
    OntologyRevisionRecord,
    ReleaseAttestation,
    ValidationResult,
    digest_of,
)
from rtr_copilot.enterprise.repository import EnterpriseError, EnterpriseRepository
from rtr_copilot.rag.adapters import normalize_query
from rtr_copilot.rag.answering import AnswerService
from rtr_copilot.rag.models import SearchFilters
from rtr_copilot.rag.ontology import EnterpriseOntology, OntologySpec
from rtr_copilot.rag.query_understanding import OfflineRewriter, plan_query
from rtr_copilot.rag.retrieval import RetrievalService
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.resources import CLASSIFICATION_TO_POLICY

policy = PolicyEngine(StructuredAuditSink())


class EnterpriseService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        repository: EnterpriseRepository | None = None,
    ) -> None:
        self.uow = UnitOfWork(factory)
        self.repository = repository or EnterpriseRepository()
        self.factory = factory

    @staticmethod
    def _actor(subject: Subject) -> uuid.UUID:
        return uuid.UUID(subject.user_id)

    @staticmethod
    def _require(
        subject: Subject,
        action: str,
        *,
        request_id: str,
        resource_id: str = "enterprise",
        classification: str = "internal",
        proposed_by: uuid.UUID | None = None,
    ) -> None:
        decision = policy.decide(
            subject,
            action,
            ResourceAttributes(
                resource_id=resource_id,
                classification=CLASSIFICATION_TO_POLICY.get(classification, "internal"),
                source_zone="sot",
                lifecycle_state="published",
                proposed_by=str(proposed_by) if proposed_by else None,
            ),
            PolicyContext(request_id=request_id),
        )
        if not decision.allow:
            raise PermissionError(decision.reason_code)

    async def _audit(
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        action: str,
        request_id: str,
        resource_id: uuid.UUID,
        resource_type: str,
        details: dict[str, Any],
    ) -> None:
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=self._actor(subject),
            action=action,
            result="allow",
            reason_code="enterprise_governance",
            request_id=request_id,
            # audit_events.resource_id is an FK to content-plane resources.
            # Enterprise ledger ids are structural governance identifiers, so
            # keep the FK empty and carry the typed id in redacted details.
            resource_id=None,
            resource_type=resource_type,
            details={"ledger_id": str(resource_id), **details},
        )

    async def propose_domain(
        self,
        subject: Subject,
        payload: DomainCreate,
        *,
        request_id: str,
    ) -> DomainRecord:
        self._require(subject, "curate", request_id=request_id)
        async with self.uow.transaction() as session:
            if not await self.repository.subject_active(session, payload.owner_subject_id):
                raise EnterpriseError("enterprise_owner_unknown")
            record = await self.repository.create_domain(session, payload, self._actor(subject))
            await self._audit(
                session,
                subject,
                action="enterprise.domain.propose",
                request_id=request_id,
                resource_id=record.domain_id,
                resource_type="enterprise_domain",
                details={
                    "domain_key_digest": digest_of(record.domain_key),
                    "minimum_eval_cases": record.minimum_eval_cases,
                    "classification": record.classification,
                },
            )
            return record

    async def decide_domain(
        self,
        subject: Subject,
        domain_id: uuid.UUID,
        payload: DecisionInput,
        *,
        request_id: str,
    ) -> DomainRecord:
        async with self.uow.transaction() as session:
            record = await self.repository.domain_by_id(session, domain_id, lock=True)
            if record is None:
                raise EnterpriseError("enterprise_domain_not_found")
            self._require(
                subject,
                "approve",
                request_id=request_id,
                resource_id=str(domain_id),
                classification=record.classification,
                proposed_by=record.proposed_by,
            )
            decided = await self.repository.decide_domain(
                session,
                domain_id,
                approver=self._actor(subject),
                approved=payload.decision == "approved",
                reason=payload.reason,
            )
            await self._audit(
                session,
                subject,
                action="enterprise.domain.decide",
                request_id=request_id,
                resource_id=domain_id,
                resource_type="enterprise_domain",
                details={"decision": payload.decision},
            )
            return decided

    async def propose_manifest(
        self,
        subject: Subject,
        spec: CorpusManifestSpec,
        *,
        version: int,
        request_id: str,
    ) -> CorpusManifestRecord:
        self._require(subject, "curate", request_id=request_id)
        async with self.uow.transaction() as session:
            domain = await self.repository.domain_by_key(session, spec.domain_key)
            if domain is None:
                raise EnterpriseError("enterprise_domain_not_found")
            if domain.state != "active":
                raise EnterpriseError("enterprise_domain_inactive")
            record = await self.repository.create_manifest(
                session,
                domain_id=domain.domain_id,
                version=version,
                spec=spec,
                proposer=self._actor(subject),
            )
            await self._audit(
                session,
                subject,
                action="enterprise.corpus.propose",
                request_id=request_id,
                resource_id=record.manifest_id,
                resource_type="enterprise_corpus_manifest",
                details={
                    "manifest_digest": record.manifest_digest,
                    "source_count": record.source_count,
                },
            )
            return record

    async def validate_manifest(
        self,
        subject: Subject,
        manifest_id: uuid.UUID,
        *,
        request_id: str,
    ) -> ValidationResult:
        self._require(
            subject,
            "curate",
            request_id=request_id,
            resource_id=str(manifest_id),
        )
        async with self.uow.transaction() as session:
            manifest = await self.repository.manifest_by_id(session, manifest_id, lock=True)
            if manifest is None:
                raise EnterpriseError("enterprise_manifest_not_found")
            if manifest.state != "proposed":
                raise EnterpriseError("enterprise_manifest_transition_invalid")
            snapshot, errors = await self.repository.validate_sources(session, manifest.sources)
            if errors:
                if any(item.startswith("source_drift") for item in errors):
                    raise EnterpriseError("enterprise_source_fingerprint_mismatch")
                raise EnterpriseError("enterprise_source_unavailable")
            validated = await self.repository.mark_manifest_validated(
                session,
                manifest_id,
                validator=self._actor(subject),
                snapshot_digest=snapshot,
            )
            await self._audit(
                session,
                subject,
                action="enterprise.corpus.validate",
                request_id=request_id,
                resource_id=manifest_id,
                resource_type="enterprise_corpus_manifest",
                details={"snapshot_digest": snapshot, "source_count": manifest.source_count},
            )
            return ValidationResult(manifest=validated, snapshot_digest=snapshot)

    async def decide_manifest(
        self,
        subject: Subject,
        manifest_id: uuid.UUID,
        payload: DecisionInput,
        *,
        request_id: str,
    ) -> CorpusManifestRecord:
        async with self.uow.transaction() as session:
            manifest = await self.repository.manifest_by_id(session, manifest_id, lock=True)
            if manifest is None:
                raise EnterpriseError("enterprise_manifest_not_found")
            domain = await self.repository.domain_by_id(session, manifest.domain_id)
            if domain is None:
                raise EnterpriseError("enterprise_domain_not_found")
            self._require(
                subject,
                "approve",
                request_id=request_id,
                resource_id=str(manifest_id),
                classification=domain.classification,
                proposed_by=manifest.proposed_by,
            )
            if payload.decision == "approved":
                current, errors = await self.repository.validate_sources(session, manifest.sources)
                if errors or current != manifest.validated_snapshot_digest:
                    raise EnterpriseError("enterprise_corpus_drifted")
            decided = await self.repository.decide_manifest(
                session,
                manifest_id,
                approver=self._actor(subject),
                approved=payload.decision == "approved",
                reason=payload.reason,
            )
            await self._audit(
                session,
                subject,
                action="enterprise.corpus.decide",
                request_id=request_id,
                resource_id=manifest_id,
                resource_type="enterprise_corpus_manifest",
                details={"decision": payload.decision, "manifest_digest": manifest.manifest_digest},
            )
            return decided

    async def propose_ontology(
        self,
        subject: Subject,
        ontology: OntologySpec,
        *,
        version: int,
        request_id: str,
    ) -> OntologyRevisionRecord:
        self._require(subject, "curate", request_id=request_id)
        registry = EnterpriseOntology(ontology)
        async with self.uow.transaction() as session:
            record = await self.repository.create_ontology(
                session,
                version=version,
                ontology=ontology,
                ontology_digest=registry.digest,
                proposer=self._actor(subject),
            )
            await self._audit(
                session,
                subject,
                action="enterprise.ontology.propose",
                request_id=request_id,
                resource_id=record.revision_id,
                resource_type="enterprise_ontology_revision",
                details={
                    "ontology_digest": registry.digest,
                    "entity_count": len(ontology.entities),
                },
            )
            return record

    async def decide_ontology(
        self,
        subject: Subject,
        revision_id: uuid.UUID,
        payload: DecisionInput,
        *,
        request_id: str,
    ) -> OntologyRevisionRecord:
        async with self.uow.transaction() as session:
            revision = await self.repository.ontology_by_id(session, revision_id, lock=True)
            if revision is None:
                raise EnterpriseError("enterprise_ontology_not_found")
            self._require(
                subject,
                "approve",
                request_id=request_id,
                resource_id=str(revision_id),
                proposed_by=revision.proposed_by,
            )
            decided = await self.repository.decide_ontology(
                session,
                revision_id,
                approver=self._actor(subject),
                approved=payload.decision == "approved",
                reason=payload.reason,
            )
            await self._audit(
                session,
                subject,
                action="enterprise.ontology.decide",
                request_id=request_id,
                resource_id=revision_id,
                resource_type="enterprise_ontology_revision",
                details={"decision": payload.decision, "ontology_digest": revision.ontology_digest},
            )
            return decided

    async def propose_suite(
        self,
        subject: Subject,
        suite: EvaluationSuiteSpec,
        *,
        version: int,
        request_id: str,
    ) -> EvaluationSuiteRecord:
        self._require(subject, "curate", request_id=request_id)
        async with self.uow.transaction() as session:
            minimums = await self.repository.active_domain_minimums(session)
            errors = suite.coverage_errors(minimums)
            if errors:
                raise EnterpriseError("enterprise_suite_domain_coverage_invalid")
            record = await self.repository.create_suite(
                session,
                version=version,
                suite=suite,
                proposer=self._actor(subject),
            )
            await self._audit(
                session,
                subject,
                action="enterprise.suite.propose",
                request_id=request_id,
                resource_id=record.suite_id,
                resource_type="enterprise_evaluation_suite",
                details={
                    "suite_digest": record.suite_digest,
                    "case_count": record.case_count,
                    "domain_count": record.domain_count,
                },
            )
            return record

    async def decide_suite(
        self,
        subject: Subject,
        suite_id: uuid.UUID,
        payload: DecisionInput,
        *,
        request_id: str,
    ) -> EvaluationSuiteRecord:
        async with self.uow.transaction() as session:
            suite = await self.repository.suite_by_id(session, suite_id, lock=True)
            if suite is None:
                raise EnterpriseError("enterprise_suite_not_found")
            self._require(
                subject,
                "approve",
                request_id=request_id,
                resource_id=str(suite_id),
                proposed_by=suite.proposed_by,
            )
            if payload.decision == "approved":
                minimums = await self.repository.active_domain_minimums(session)
                if suite.definition.coverage_errors(minimums):
                    raise EnterpriseError("enterprise_suite_domain_coverage_invalid")
            decided = await self.repository.decide_suite(
                session,
                suite_id,
                approver=self._actor(subject),
                approved=payload.decision == "approved",
                reason=payload.reason,
            )
            await self._audit(
                session,
                subject,
                action="enterprise.suite.decide",
                request_id=request_id,
                resource_id=suite_id,
                resource_type="enterprise_evaluation_suite",
                details={"decision": payload.decision, "suite_digest": suite.suite_digest},
            )
            return decided

    async def _evaluate_case(
        self,
        case: EvaluationCase,
        ontology: EnterpriseOntology,
        subject: Subject,
        *,
        request_id: str,
        retrieval: RetrievalService,
        answer: AnswerService,
        answer_configured: bool,
    ) -> tuple[bool, str, list[str]]:
        plan = await plan_query(
            case.question,
            OfflineRewriter(),
            registry=ontology,
        )
        expected = case.expectation
        if case.kind == "query":
            passed = plan.resolution_state == expected.resolution_state and set(
                plan.entity_ids
            ) == set(expected.entity_ids)
            return passed, "passed" if passed else "query_contract_mismatch", []
        hits = await retrieval.search(
            subject,
            plan.retrieval_query,
            filters=SearchFilters(),
            request_id=request_id,
            query_entities=plan.entities,
            query_intent=plan.intent,
        )
        record_keys = [item.citation.record_key for item in hits]
        if case.kind == "retrieval":
            passed = set(expected.required_record_keys).issubset(record_keys) and not set(
                expected.forbidden_record_keys
            ).intersection(record_keys)
            return passed, "passed" if passed else "retrieval_contract_mismatch", record_keys
        if not answer_configured:
            return False, "answer_quality_configuration_required", record_keys
        response = await answer.ask(
            subject,
            case.question,
            filters=SearchFilters(),
            require_verified=True,
            conversation_id=None,
            request_id=request_id,
        )
        cited_keys = [item.record_key for item in response.citations]
        normalized_answer = normalize_query(response.answer)
        passed = (
            response.state == expected.answer_state
            and set(expected.required_record_keys).issubset(cited_keys)
            and not set(expected.forbidden_record_keys).intersection(cited_keys)
            and all(normalize_query(term) in normalized_answer for term in expected.required_terms)
        )
        return passed, "passed" if passed else "answer_contract_mismatch", cited_keys

    async def run_suite(
        self,
        subject: Subject,
        suite_id: uuid.UUID,
        ontology_revision_id: uuid.UUID,
        *,
        request_id: str,
    ) -> EvaluationRunRecord:
        self._require(subject, "curate", request_id=request_id, resource_id=str(suite_id))
        async with self.uow.factory() as session:
            suite = await self.repository.suite_by_id(session, suite_id)
            revision = await self.repository.ontology_by_id(session, ontology_revision_id)
            if suite is None:
                raise EnterpriseError("enterprise_suite_not_found")
            if revision is None:
                raise EnterpriseError("enterprise_ontology_not_found")
            if suite.state != "approved" or revision.state != "approved":
                raise EnterpriseError("enterprise_evaluation_candidate_unapproved")
            (
                corpus_digest,
                domain_count,
                manifest_count,
                drift,
            ) = await self.repository.current_corpus_snapshot(session)
            minimums = await self.repository.active_domain_minimums(session)
        if domain_count == 0 or domain_count != manifest_count or drift:
            raise EnterpriseError("enterprise_corpus_not_ready")
        coverage_errors = suite.definition.coverage_errors(minimums)
        ambiguity_errors = suite.definition.ambiguity_coverage_errors(revision.payload)
        if coverage_errors or ambiguity_errors:
            raise EnterpriseError("enterprise_suite_coverage_stale")

        ontology = EnterpriseOntology(revision.payload)
        retrieval = RetrievalService(factory=self.factory)
        answer = AnswerService(
            factory=self.factory,
            retrieval=retrieval,
            rewriter=OfflineRewriter(),
            ontology=ontology,
        )
        # Evidence-only mode keeps day-to-day Ask usable, but it must never
        # masquerade as the independently generated/reviewed LLM path required
        # for enterprise release certification.
        answer_configured = answer.provider.name not in {"unavailable", "evidence-only"}
        started = datetime.now(UTC)
        results: list[dict[str, Any]] = []
        metrics: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "passed": 0, "failed": 0, "critical_failed": 0},
        )
        for case in suite.definition.cases:
            case_request_id = f"{request_id}:eval:{digest_of(case.case_id)[:12]}"
            try:
                passed, code, record_keys = await self._evaluate_case(
                    case,
                    ontology,
                    subject,
                    request_id=case_request_id,
                    retrieval=retrieval,
                    answer=answer,
                    answer_configured=answer_configured,
                )
            except Exception as error:  # noqa: BLE001 - result must be sanitized and complete
                passed = False
                code = f"evaluation_error_{type(error).__name__.lower()}"
                record_keys = []
            domain = metrics[case.domain_key]
            domain["total"] += 1
            domain["passed" if passed else "failed"] += 1
            if not passed and case.risk_class == "critical":
                domain["critical_failed"] += 1
            results.append(
                {
                    "case_id": case.case_id,
                    "case_digest": digest_of(case.model_dump(mode="json")),
                    "domain_key": case.domain_key,
                    "risk_class": case.risk_class,
                    "kind": case.kind,
                    "passed": passed,
                    "code": code,
                    "record_key_digests": [digest_of(item) for item in record_keys],
                }
            )
        finished = datetime.now(UTC)
        passed_count = sum(1 for item in results if item["passed"])
        failed_count = len(results) - passed_count
        critical_failed = sum(
            1 for item in results if not item["passed"] and item["risk_class"] == "critical"
        )
        status: EvaluationStatus = (
            "passed"
            if failed_count == 0
            else (
                "incomplete"
                if any(item["code"] == "answer_quality_configuration_required" for item in results)
                else "failed"
            )
        )
        subject_digest = digest_of(
            {
                "user_id": subject.user_id,
                "roles": sorted(role.value for role in subject.roles),
                "groups": sorted(subject.groups),
                "departments": sorted(subject.departments),
                "projects": sorted(subject.projects),
            }
        )
        result_payload = {
            "schema_version": 1,
            "case_results": results,
            "answer_quality_configured": answer_configured,
        }
        result_digest = digest_of(
            {
                "ontology_digest": revision.ontology_digest,
                "suite_digest": suite.suite_digest,
                "corpus_snapshot_digest": corpus_digest,
                "subject_digest": subject_digest,
                "result_payload": result_payload,
            }
        )
        async with self.uow.transaction() as session:
            run = await self.repository.create_run(
                session,
                suite_id=suite_id,
                ontology_revision_id=ontology_revision_id,
                ontology_digest=revision.ontology_digest,
                suite_digest=suite.suite_digest,
                corpus_snapshot_digest=corpus_digest,
                evaluation_subject_digest=subject_digest,
                status=status,
                passed_count=passed_count,
                failed_count=failed_count,
                critical_failed_count=critical_failed,
                domain_metrics=dict(metrics),
                result_payload=result_payload,
                result_digest=result_digest,
                executed_by=self._actor(subject),
                started_at=started,
                finished_at=finished,
            )
            await self._audit(
                session,
                subject,
                action="enterprise.evaluation.run",
                request_id=request_id,
                resource_id=run.run_id,
                resource_type="enterprise_evaluation_run",
                details={
                    "status": status,
                    "passed_count": passed_count,
                    "failed_count": failed_count,
                    "critical_failed_count": critical_failed,
                    "result_digest": result_digest,
                    "corpus_snapshot_digest": corpus_digest,
                },
            )
            return run

    async def activate_ontology(
        self,
        subject: Subject,
        revision_id: uuid.UUID,
        evaluation_run_id: uuid.UUID,
        *,
        reason: str,
        request_id: str,
    ) -> ReleaseAttestation:
        async with self.uow.transaction() as session:
            revision = await self.repository.ontology_by_id(session, revision_id, lock=True)
            run = await self.repository.run_by_id(session, evaluation_run_id)
            if revision is None:
                raise EnterpriseError("enterprise_ontology_not_found")
            if run is None:
                raise EnterpriseError("enterprise_evaluation_run_not_found")
            suite = await self.repository.suite_by_id(session, run.suite_id)
            self._require(
                subject,
                "approve",
                request_id=request_id,
                resource_id=str(revision_id),
                proposed_by=revision.proposed_by,
            )
            (
                corpus_digest,
                domain_count,
                manifest_count,
                drift,
            ) = await self.repository.current_corpus_snapshot(session)
            if (
                revision.state != "approved"
                or suite is None
                or suite.state != "approved"
                or run.suite_digest != suite.suite_digest
                or run.status != "passed"
                or run.ontology_revision_id != revision_id
                or run.ontology_digest != revision.ontology_digest
                or run.corpus_snapshot_digest != corpus_digest
                or domain_count == 0
                or domain_count != manifest_count
                or drift
            ):
                raise EnterpriseError("enterprise_release_gate_failed")
            release_digest = digest_of(
                {
                    "registry_id": revision.registry_id,
                    "ontology_digest": run.ontology_digest,
                    "corpus_snapshot_digest": run.corpus_snapshot_digest,
                    "suite_digest": run.suite_digest,
                    "result_digest": run.result_digest,
                }
            )
            attestation = await self.repository.activate(
                session,
                revision=revision,
                run=run,
                approver=self._actor(subject),
                release_digest=release_digest,
            )
            await self._audit(
                session,
                subject,
                action="enterprise.ontology.activate",
                request_id=request_id,
                resource_id=revision_id,
                resource_type="enterprise_ontology_revision",
                details={
                    "release_digest": release_digest,
                    "evaluation_run_id": str(run.run_id),
                    "reason_digest": hashlib.sha256(reason.encode()).hexdigest(),
                },
            )
            return attestation

    async def readiness(self, subject: Subject, *, request_id: str) -> EnterpriseReadiness:
        self._require(subject, "view", request_id=request_id)
        async with self.uow.factory() as session:
            active = await self.repository.active_ontology(session)
            release = await self.repository.active_release(session)
            (
                corpus_digest,
                domains,
                manifests,
                drift,
            ) = await self.repository.current_corpus_snapshot(session)
        code = "ready"
        ready = True
        if domains == 0:
            ready, code = False, "no_active_domains"
        elif manifests != domains:
            ready, code = False, "active_manifest_missing"
        elif drift:
            ready, code = False, "corpus_drift_detected"
        elif active is None or release is None:
            ready, code = False, "release_missing"
        elif (
            release.ontology_revision_id != active.revision_id
            or release.ontology_digest != active.ontology_digest
            or release.corpus_snapshot_digest != corpus_digest
        ):
            ready, code = False, "release_attestation_stale"
        return EnterpriseReadiness(
            ready=ready,
            code=code,
            active_domain_count=domains,
            active_manifest_count=manifests,
            active_ontology_digest=active.ontology_digest if active else None,
            corpus_snapshot_digest=corpus_digest,
            release_digest=release.release_digest if release else None,
            drifted_source_count=len(drift),
        )

    async def active_ontology(
        self,
        subject: Subject,
        *,
        request_id: str,
    ) -> OntologyRevisionRecord:
        if not subject.roles.intersection({Role.CURATOR, Role.LEADER}):
            raise PermissionError("governance_role_required")
        self._require(subject, "view", request_id=request_id)
        async with self.uow.factory() as session:
            revision = await self.repository.active_ontology(session)
        if revision is None:
            raise EnterpriseError("enterprise_active_ontology_not_found")
        return revision
