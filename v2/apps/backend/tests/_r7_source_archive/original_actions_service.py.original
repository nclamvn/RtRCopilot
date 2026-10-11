import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.actions.authority import LeafRequest, lock_subjects
from rtr_copilot.actions.checkpoints import (
    check_sources,
    input_metadata,
    lock_inputs,
    source_requests,
)
from rtr_copilot.actions.models import (
    CONTRACT_BUILD,
    ActionEvent,
    ApprovalBinding,
    ApprovalRequest,
    ApprovalView,
    BudgetRequest,
    BudgetUnits,
    CapabilityView,
    ContractReceipt,
    PlanPayload,
    PlanRequest,
    PlanView,
    StepRequest,
)
from rtr_copilot.actions.policy import (
    ActionPolicy,
    policy,
)
from rtr_copilot.actions.registry import (
    ActionError,
    HostRegistry,
    canonical,
    digest,
    hashes,
    validate_input,
)
from rtr_copilot.actions.repository import ActionRepository
from rtr_copilot.actions.request_connection import LegacyInitialRequired, RequestConnection
from rtr_copilot.actions.source_metadata import InitialClockDenied, UnsupportedSourceTopology
from rtr_copilot.auth.models import PolicyContext, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository


def correlation(request_id: str) -> str:
    # Public headers are untrusted data, not a safe audit/string channel.
    return hashlib.sha256(request_id.encode()).hexdigest()


def validate_graph(request: PlanRequest) -> None:
    steps = {step.step_key: step for step in request.steps}
    if len(steps) != len(request.steps):
        raise ActionError("dependencies_invalid", 422)
    visited: set[str] = set()
    active: set[str] = set()

    def visit(key: str) -> None:
        if key in active or key not in steps:
            raise ActionError("dependencies_invalid", 422)
        if key in visited:
            return
        active.add(key)
        dependencies = steps[key].dependencies
        if len(set(dependencies)) != len(dependencies):
            raise ActionError("dependencies_invalid", 422)
        for parent in dependencies:
            visit(parent)
        active.remove(key)
        visited.add(key)

    for key in steps:
        visit(key)


class ActionService:
    def __init__(
        self,
        uow: UnitOfWork | None = None,
        *,
        registry: HostRegistry | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.uow = uow or UnitOfWork()
        self.registry = registry or HostRegistry()
        self.repo = ActionRepository()
        self.policy = ActionPolicy(self.uow)
        self.clock = clock
        self.build_id = get_settings().rtr_build_sha

    async def _audit(
        self,
        session: AsyncSession,
        subject: Subject,
        action: str,
        request_id: str,
        *,
        plan: PlanView | None = None,
        reason: str = "contract_recorded",
        result: str = "success",
    ) -> None:
        # Deliberate whitelist. Generic redaction cannot detect all source text.
        details = (
            {
                "plan_id": str(plan.plan_id),
                "plan_digest": plan.plan_digest,
                "run_id": str(plan.run_id),
                "contract_build": CONTRACT_BUILD,
                "runtime_build_sha": self.build_id,
            }
            if plan
            else {"contract_build": CONTRACT_BUILD, "runtime_build_sha": self.build_id}
        )
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=uuid.UUID(subject.user_id),
            action=action,
            result=result,
            reason_code=reason,
            request_id=request_id,
            resource_type="action_contract",
            details=details,
        )

    async def capabilities(self, subject: Subject) -> tuple[CapabilityView, ...]:
        await self.policy.current(subject)
        views: list[CapabilityView] = []
        async with self.uow.factory() as session:
            for spec in self.registry.all():
                row = await self.repo.capability(session, spec.capability_id, spec.version)
                contract_hash, schema_hash = hashes(spec)
                views.append(
                    CapabilityView(
                        spec=spec,
                        contract_digest=contract_hash,
                        schema_digest=schema_hash,
                        admission=row["admission"] if row else "not_admitted",
                        execution_available=(
                            spec.execution_available
                            and get_settings().action_executor_enabled
                            and get_settings().action_workflow_dsn is not None
                            and row is not None
                            and row["admission"] == "admitted"
                        ),
                    )
                )
        return tuple(views)

    async def admit_capability(
        self, subject: Subject, capability_id: str, version: str, *, request_id: str
    ) -> CapabilityView:
        current = await self.policy.current(subject)
        request = correlation(request_id)
        self.policy.manage_registry(current, request)
        spec = self.registry.contract(capability_id, version)
        contract_hash, schema_hash = hashes(spec)
        async with self.uow.transaction() as session:
            current = await self.policy.session_current(session, current)
            self.policy.manage_registry(current, request)
            await session.execute(
                text("""
                INSERT INTO capability_versions(capability_id,version,spec,contract_digest,
                  schema_digest,admission,admitted_by)
                VALUES (:id,:version,CAST(:spec AS jsonb),:digest,:schema,'admitted',:actor)
                ON CONFLICT(capability_id,version) DO NOTHING
            """),
                {
                    "id": capability_id,
                    "version": version,
                    "spec": canonical(spec.model_dump(mode="json")).decode(),
                    "digest": contract_hash,
                    "schema": schema_hash,
                    "actor": uuid.UUID(current.user_id),
                },
            )
            row = await self.repo.capability(session, capability_id, version)
            if row["contract_digest"] != contract_hash or row["schema_digest"] != schema_hash:
                raise ActionError("capability_conflict")
            if row["admission"] != "admitted":
                raise ActionError("capability_revoked")
            await session.execute(text("SELECT pg_advisory_xact_lock(827004)"))
            current = await self.policy.session_current(session, current)
            self.policy.manage_registry(current, request)
            await self._audit(session, current, "action.capability.admit", request)
        return CapabilityView(
            spec=spec,
            contract_digest=contract_hash,
            schema_digest=schema_hash,
            admission="admitted",
        )

    async def revoke_capability(
        self, subject: Subject, capability_id: str, version: str, *, request_id: str
    ) -> None:
        current = await self.policy.current(subject)
        request = correlation(request_id)
        self.policy.manage_registry(current, request)
        self.registry.contract(capability_id, version)
        async with self.uow.transaction() as session:
            current = await self.policy.session_current(session, current)
            self.policy.manage_registry(current, request)
            changed = await session.execute(
                text("""
                UPDATE capability_versions SET admission='revoked',revoked_at=now()
                WHERE capability_id=:id AND version=:version AND admission='admitted'
            """),
                {"id": capability_id, "version": version},
            )
            if getattr(changed, "rowcount", 0) != 1:
                raise ActionError("capability_unavailable", 404)
            await session.execute(text("SELECT pg_advisory_xact_lock(827004)"))
            current = await self.policy.session_current(session, current)
            self.policy.manage_registry(current, request)
            await self._audit(session, current, "action.capability.revoke", request)

    async def _contract(
        self, capability_id: str, version: str, *, initial_session: AsyncSession | None = None
    ) -> Any:
        spec = self.registry.contract(capability_id, version)
        if initial_session is None:
            async with self.uow.factory() as session:
                row = await self.repo.capability(session, capability_id, version)
        else:
            row = await self.repo.capability(initial_session, capability_id, version)
        contract_hash, schema_hash = hashes(spec)
        if (
            row is None
            or row["admission"] != "admitted"
            or str(row["contract_digest"]) != contract_hash
            or str(row["schema_digest"]) != schema_hash
        ):
            raise ActionError("capability_unavailable", 403)
        return spec

    async def _payload(
        self,
        current: Subject,
        request: PlanRequest,
        request_id: str,
        *,
        initial_session: AsyncSession | None = None,
    ) -> PlanPayload:
        validate_graph(request)
        for step in request.steps:
            canonical(step.arguments)
        if request.budget.model_calls or request.budget.tokens or request.budget.spend_microusd:
            raise ActionError("unpriced_work_unavailable", 422)
        ceiling = BudgetRequest()
        if any(
            value > ceiling.model_dump()[key] for key, value in request.budget.model_dump().items()
        ):
            raise ActionError("budget_limit_invalid", 422)
        await self.policy.scope(current, request, initial_session=initial_session)
        sources = await self.policy.sources(
            current, request, request_id, initial_session=initial_session
        )
        if sources.subject.security_version != current.security_version:
            raise ActionError("authority_changed", 403)
        steps = []
        calls = 0
        for step in sorted(request.steps, key=lambda entry: entry.step_key):
            spec = await self._contract(
                step.capability_id, step.capability_version, initial_session=initial_session
            )
            calls += spec.max_tool_calls
            steps.append(
                await self.policy.step(
                    current,
                    step,
                    spec,
                    sources,
                    request,
                    request_id,
                    initial_session=initial_session,
                )
            )
        if calls > request.budget.tool_calls:
            raise ActionError("budget_limit_invalid", 422)
        needs_approval = any(step.effect_class in {"R2", "R3"} for step in steps)
        if needs_approval and not request.reviewers:
            raise ActionError("reviewer_required", 422)
        return PlanPayload(
            actor_id=uuid.UUID(current.user_id),
            actor_security_version=current.security_version,
            workspace_id=uuid.UUID(current.user_id),
            context_packet_id=request.context_packet_id,
            objective=request.objective,
            purpose=request.purpose,
            source_refs=tuple(
                sorted(
                    request.source_refs,
                    key=lambda ref: (
                        ref.source_key,
                        ref.record_key,
                        str(ref.record_version_id),
                        ref.evidence_key or "",
                    ),
                )
            ),
            steps=tuple(steps),
            budget=request.budget,
            reviewers=tuple(sorted(request.reviewers, key=str)),
            requested_internal_draft=request.requested_internal_draft,
            runtime_build_sha=self.build_id,
        )

    async def _snapshot(
        self,
        session: AsyncSession,
        current: Subject,
        payload: PlanPayload,
        request_id: str,
        *,
        audit_fence: bool = False,
        _stage_own_root: Callable[[AsyncSession], Awaitable[None]] | None = None,
    ) -> None:
        if _stage_own_root is not None and not audit_fence:
            raise ValueError("own_root_stage_requires_audit_fence")
        await lock_inputs(session, payload, (uuid.UUID(current.user_id),))
        if _stage_own_root is not None:
            await _stage_own_root(session)
        if audit_fence:
            await session.execute(text("SELECT pg_advisory_xact_lock(827004)"))
        await self._check_locked_snapshot(session, current, payload, request_id)

    async def _check_locked_snapshot(
        self,
        session: AsyncSession,
        current: Subject,
        payload: PlanPayload,
        request_id: str,
    ) -> None:
        # Private closure: callers have acquired all input/evidence fences and,
        # for audit writers, 827004. Never reuse a pre-wait permission frame.
        metadata = await input_metadata(session, payload)
        requests = source_requests(metadata) + [
            LeafRequest(r.resource_id, r.policy_action, r.resource_type)
            for step in payload.steps
            for r in step.resources
        ]
        frame = await self.policy.checkpoint(session, current, requests)
        current = frame.subject
        if (
            uuid.UUID(current.user_id) != payload.actor_id
            or current.security_version != payload.actor_security_version
        ):
            raise ActionError("authority_changed", 403)
        if payload.context_packet_id is not None:
            packet = metadata["packet"]
            if (
                packet is None
                or (
                    packet["scope_kind"] == "project"
                    and str(packet["scope_key"]) not in current.projects
                )
                or (
                    packet["scope_kind"] == "department"
                    and str(packet["scope_key"]) not in current.departments
                )
            ):
                raise ActionError("scope_unavailable", 403)
        capabilities = {(r["capability_id"], r["version"]): r for r in metadata["capabilities"]}
        templates = {r["version_id"]: r for r in metadata["templates"]}
        for step in payload.steps:
            row = capabilities.get((step.capability_id, step.capability_version))
            if (
                row is None
                or row["admission"] != "admitted"
                or row["contract_digest"] != step.contract_digest
                or row["schema_digest"] != step.schema_digest
            ):
                raise ActionError("capability_unavailable", 403)
            for resource in step.resources:
                attributes = frame.attributes.get((resource.resource_id, resource.policy_action))
                if (
                    attributes is None
                    or attributes[0].classification != resource.classification
                    or not policy.decide(
                        current,
                        resource.policy_action,
                        attributes[0],
                        PolicyContext(request_id=request_id),
                    ).allow
                ):
                    raise ActionError("resource_unavailable", 403)
                if resource.resource_type == "template_version":
                    template = templates.get(str(resource.resource_id))
                    if (
                        template is None
                        or template["status"] != "approved"
                        or template["lifecycle"] != "approved"
                        or template["document_class"] != "internal"
                        or resource.content_sha256
                        != digest(
                            {
                                "source": template["source_sha256"],
                                "schema": template["field_schema"],
                                "renderer": template["renderer_version"],
                                "document_class": template["document_class"],
                            }
                        )
                    ):
                        raise ActionError("template_unavailable", 403)
        check_sources(metadata, frame, payload, policy, request_id)

    async def _source_snapshot(
        self, session: AsyncSession, current: Subject, payload: PlanPayload, request_id: str
    ) -> None:
        # Standalone reviewer/disclosure callers receive the same post-wait
        # authority semantics; a supplied Subject is identity, never permission.
        await lock_inputs(session, payload, (uuid.UUID(current.user_id),), sources_only=True)
        metadata = await input_metadata(session, payload)
        frame = await self.policy.checkpoint(session, current, source_requests(metadata))
        check_sources(metadata, frame, payload, policy, request_id)

    async def _reviewer_snapshot(
        self, session: AsyncSession, reviewer: Subject, view: PlanView, request_id: str
    ) -> Subject:
        await lock_inputs(
            session, view.payload, (view.payload.actor_id, uuid.UUID(reviewer.user_id))
        )
        metadata = await input_metadata(session, view.payload)
        requests = source_requests(metadata) + [
            LeafRequest(r.resource_id, action, r.resource_type)
            for step in view.payload.steps
            for r in step.resources
            for action in ("view", "approve")
        ]
        frame = await self.policy.checkpoint(session, reviewer, requests)
        current = frame.subject
        if uuid.UUID(current.user_id) not in view.payload.reviewers or current.user_id == str(
            view.payload.actor_id
        ):
            raise ActionError("approval_unavailable")
        check_sources(metadata, frame, view.payload, policy, request_id)
        for step in view.payload.steps:
            for resource in step.resources:
                for action in ("view", "approve"):
                    attributes = frame.attributes.get((resource.resource_id, action))
                    if attributes is None:
                        raise ActionError("resource_unavailable", 403)
                    attributes[0].proposed_by = str(view.payload.actor_id)
                    if not policy.decide(
                        current, action, attributes[0], PolicyContext(request_id=request_id)
                    ).allow:
                        raise ActionError("resource_unavailable", 403)
        return current

    @staticmethod
    def _r0_request(request: PlanRequest) -> bool:
        return request.supersedes_plan_id is None and all(
            step.capability_id == "sot.read"
            and step.capability_version == "2"
            and (step.destination is None or step.destination.kind == "response")
            for step in request.steps
        )

    @staticmethod
    def _r0_plan(view: PlanView) -> bool:
        return (
            view.root_plan_id == view.plan_id
            and view.plan_version == 1
            and all(
                step.capability_id == "sot.read"
                and step.capability_version == "2"
                and step.effect_class == "R0"
                and step.destination.kind == "response"
                for step in view.payload.steps
            )
        )

    async def _legacy_initial_plan(
        self,
        subject: Subject,
        request: PlanRequest,
        request_id: str,
    ) -> tuple[Subject, PlanPayload]:
        current = await self.policy.current(subject)
        payload = await self._payload(current, request, request_id)
        await self.policy.sources(current, payload, request_id)
        return current, payload

    async def _clock_retry_preflight(
        self,
        session: AsyncSession,
        current: Subject,
        request: PlanRequest,
        request_id: str,
    ) -> None:
        # A source clock denial can precede step/schema/capability validation.
        # Hard errors must suppress retry, not get swallowed by a broad catch.
        validate_graph(request)
        if not self._r0_request(request):
            raise ActionError("contract_changed")
        fresh = await self.policy.current(current, initial_session=session)
        if fresh.security_version != current.security_version:
            raise ActionError("authority_changed", 403)
        await self.policy.scope(fresh, request, initial_session=session)
        calls = 0
        for step in request.steps:
            spec = await self._contract(
                step.capability_id, step.capability_version, initial_session=session
            )
            if (
                spec.capability_id != "sot.read"
                or spec.version != "2"
                or spec.effect_class != "R0"
                or spec.implementation_ref != "sot.read"
                or spec.policy_action != "view"
                or spec.allowed_destinations != ("response",)
                or not spec.execution_available
            ):
                raise ActionError("contract_changed")
            validate_input(step.arguments, spec.input_schema)
            if (
                sum(
                    ref.record_key == step.arguments.get("record_key")
                    for ref in request.source_refs
                )
                != 1
            ):
                raise ActionError("source_unavailable", 403)
            if (
                step.destination is not None
                and step.destination.kind not in spec.allowed_destinations
            ):
                raise ActionError("destination_unavailable", 403)
            calls += spec.max_tool_calls
        if calls > request.budget.tool_calls:
            raise ActionError("budget_limit_invalid", 422)
        # Eligibility only. Owner still CLOSES and uses the whole old path.
        with suppress(InitialClockDenied):
            await self.policy.sources(fresh, request, request_id, initial_session=session)

    async def _initial_plan(
        self,
        subject: Subject,
        request: PlanRequest,
        request_id: str,
        *,
        _owner: RequestConnection | None = None,
    ) -> tuple[Subject, PlanPayload, bool]:
        if not self._r0_request(request):
            current, payload = await self._legacy_initial_plan(subject, request, request_id)
            return current, payload, False
        fallback = False
        phase = _owner.read_phase() if _owner is not None else self.uow.factory()
        async with phase as session:
            current = await self.policy.current(subject, initial_session=session)
            try:
                payload = await self._payload(current, request, request_id, initial_session=session)
                await self.policy.sources(current, payload, request_id, initial_session=session)
            except InitialClockDenied:
                await self._clock_retry_preflight(session, current, request, request_id)
                fallback = True
            except UnsupportedSourceTopology:
                fallback = True
        if fallback:
            if _owner is not None:
                # The public owner context closes/checks in BEFORE old fallback.
                raise LegacyInitialRequired()
            # Once only: this old helper cannot reenter the borrowed lane.
            current, payload = await self._legacy_initial_plan(subject, request, request_id)
            return current, payload, False
        return current, payload, True

    async def create_plan(
        self, subject: Subject, request: PlanRequest, *, request_id: str
    ) -> PlanView:
        if self._r0_request(request):
            owner: RequestConnection | None = None
            try:
                async with RequestConnection(self.uow.factory) as owner:
                    return await self._create_plan_attempt(
                        subject, request, request_id=request_id, _owner=owner
                    )
            except LegacyInitialRequired:
                if owner is not None and not owner.fallback_allowed:
                    raise
                return await self._create_plan_attempt(
                    subject, request, request_id=request_id, private_initial_mode="legacy"
                )
        return await self._create_plan_attempt(subject, request, request_id=request_id)

    async def _create_plan_attempt(
        self,
        subject: Subject,
        request: PlanRequest,
        *,
        request_id: str,
        _owner: RequestConnection | None = None,
        private_initial_mode: Literal["current", "legacy"] = "current",
    ) -> PlanView:
        safe_request = correlation(request_id)
        if private_initial_mode == "legacy":
            current, payload = await self._legacy_initial_plan(subject, request, safe_request)
            optimized = False
        else:
            current, payload, optimized = await self._initial_plan(
                subject, request, safe_request, _owner=_owner
            )
        # Final policy/currentness check after parameter binding. No content
        # disclosure occurs inside the persistence transaction.
        plan_digest = digest(payload.model_dump(mode="json"))
        state = (
            "awaiting_approval"
            if any(step.effect_class in {"R2", "R3"} for step in payload.steps)
            else "contract_ready"
        )
        phase = _owner.mutation_phase() if _owner is not None else self.uow.transaction()
        async with phase as session:
            # Universal key fence covers mixed contract versions. Independent
            # executable plans own distinct roots; only legacy contracts and
            # superseding ordinals require the wider actor fence. Always acquire
            # key then actor so these paths cannot invert their lock order.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"action-plan-key:{current.user_id}:{request.idempotency_key}"},
            )
            if request.supersedes_plan_id or any(
                step.capability_version != "2" for step in payload.steps
            ):
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"action-plan:{current.user_id}"},
                )
            if not optimized:
                await self._snapshot(session, current, payload, safe_request, audit_fence=True)
            existing = await session.scalar(
                text("""
                SELECT plan_id FROM action_plans WHERE actor_id=:actor AND idempotency_key=:key
            """),
                {"actor": payload.actor_id, "key": request.idempotency_key},
            )
            if existing:
                if optimized:
                    await self._snapshot(session, current, payload, safe_request)
                view = await self.repo.plan(session, existing)
                if view.plan_digest != plan_digest:
                    raise ActionError("idempotency_conflict")
            else:
                if optimized:
                    # Only rollback-local self-root bookkeeping precedes audit.
                    # Actual source effects/outbox/dispatch never occur here.
                    staged_view: PlanView | None = None

                    async def stage_own_root(stage_session: AsyncSession) -> None:
                        nonlocal staged_view
                        if stage_session is not session:
                            raise RuntimeError("own_root_stage_session_changed")
                        staged_view = await self._insert_plan(
                            stage_session,
                            current,
                            request,
                            payload,
                            plan_digest,
                            state,
                            safe_request,
                            append_audit=False,
                        )

                    # Keep the existing checkpoint protocol/None return for all
                    # observers. The holder is ledger metadata, never authority.
                    await self._snapshot(
                        session,
                        current,
                        payload,
                        safe_request,
                        audit_fence=True,
                        _stage_own_root=stage_own_root,
                    )
                    if staged_view is None:
                        raise RuntimeError("own_root_stage_missing")
                    view = staged_view
                    await self._audit(
                        session, current, "action.plan.create", safe_request, plan=view
                    )
                else:
                    view = await self._insert_plan(
                        session, current, request, payload, plan_digest, state, safe_request
                    )
        # End the lock-owning transaction before NEW final disclosure authority.
        if self._builtin_execution_payload(view.payload):
            if _owner is not None:
                return await self._metadata_plan(
                    current, view.plan_id, plan_digest, safe_request, _owner=_owner
                )
            return await self._metadata_plan(current, view.plan_id, plan_digest, safe_request)
        return await self.read_plan(current, view.plan_id, request_id=request_id)

    @staticmethod
    def _builtin_execution_payload(payload: PlanPayload) -> bool:
        effects = {"sot.read": "R0", "documents.create_draft": "R1"}
        return bool(payload.steps) and all(
            step.capability_version == "2"
            and step.capability_id in effects
            and step.effect_class == effects[step.capability_id]
            for step in payload.steps
        )

    async def _metadata_plan(
        self,
        subject: Subject,
        plan_id: uuid.UUID,
        expected_digest: str,
        request_id: str,
        *,
        _owner: RequestConnection | None = None,
    ) -> PlanView:
        # Only this method's already-bound immutable builtin v2 admission uses
        # the metadata seam. Fresh persisted state and statement-time authority
        # are read AFTER the insertion transaction closes, without a content bind.
        async with AsyncExitStack() as stack:
            session = await stack.enter_async_context(
                _owner.read_phase(commit=True) if _owner is not None else self.uow.factory()
            )
            if _owner is None:
                await stack.enter_async_context(session.begin())
            view = await self.repo.plan(session, plan_id)
            if not self._builtin_execution_payload(view.payload):
                raise ActionError("contract_changed")
            if view.payload.actor_id != uuid.UUID(subject.user_id):
                raise ActionError("not_found", 404)
            if (
                view.plan_digest != expected_digest
                or digest(view.payload.model_dump(mode="json")) != expected_digest
                or view.payload.runtime_build_sha != self.build_id
                or view.payload.workspace_id != view.payload.actor_id
            ):
                raise ActionError("contract_changed")
            for step in view.payload.steps:
                spec = self.registry.contract(step.capability_id, step.capability_version)
                contract_hash, schema_hash = hashes(spec)
                if (
                    step.contract_digest != contract_hash
                    or step.schema_digest != schema_hash
                    or step.arguments_digest != digest(step.arguments)
                    or step.effect_class != spec.effect_class
                    or not spec.execution_available
                ):
                    raise ActionError("contract_changed")
                validate_input(step.arguments, spec.input_schema)
            await self._snapshot(session, subject, view.payload, request_id)
        return view

    async def _insert_plan(
        self,
        session: AsyncSession,
        current: Subject,
        request: PlanRequest,
        payload: PlanPayload,
        plan_digest: str,
        state: str,
        safe_request: str,
        *,
        append_audit: bool = True,
    ) -> PlanView:
        plan_id, run_id = uuid.uuid4(), uuid.uuid4()
        root_id, ordinal = plan_id, 1
        if request.supersedes_plan_id:
            previous = await self.repo.plan(session, request.supersedes_plan_id)
            if previous.payload.actor_id != payload.actor_id:
                raise ActionError("not_found", 404)
            root_id = previous.root_plan_id
            ordinal = int(
                await session.scalar(
                    text("""
                SELECT max(plan_version)+1 FROM action_plans WHERE root_plan_id=:root
            """),
                    {"root": root_id},
                )
            )
        await session.execute(
            text("""
                INSERT INTO action_plans(plan_id,root_plan_id,plan_version,actor_id,workspace_id,
                  idempotency_key,plan_digest,payload,supersedes_plan_id,request_id,build_id)
                VALUES (:id,:root,:ordinal,:actor,:workspace,:key,:digest,CAST(:payload AS jsonb),
                  :supersedes,:request,:build)
            """),
            {
                "id": plan_id,
                "root": root_id,
                "ordinal": ordinal,
                "actor": payload.actor_id,
                "workspace": payload.workspace_id,
                "key": request.idempotency_key,
                "digest": plan_digest,
                "payload": canonical(payload.model_dump(mode="json")).decode(),
                "supersedes": request.supersedes_plan_id,
                "request": safe_request,
                "build": self.build_id,
            },
        )
        await session.execute(
            text("""
                INSERT INTO action_runs(run_id,plan_id,state,budget_limits,budget_reserved)
                VALUES (:id,:plan,:state,CAST(:limits AS jsonb),CAST(:reserved AS jsonb))
            """),
            {
                "id": run_id,
                "plan": plan_id,
                "state": state,
                "limits": canonical(payload.budget.model_dump(mode="json")).decode(),
                "reserved": canonical(BudgetUnits().model_dump(mode="json")).decode(),
            },
        )
        view = await self.repo.plan(session, plan_id)
        await self.repo.event(
            session, view, event_type="plan_admitted", reason_code=state, request_id=safe_request
        )
        await self.repo.receipt(session, view, kind="contract_admission", request_id=safe_request)
        if append_audit:
            await self._audit(session, current, "action.plan.create", safe_request, plan=view)
        return view

    async def read_plan(self, subject: Subject, plan_id: uuid.UUID, *, request_id: str) -> PlanView:
        current = await self.policy.current(subject)
        safe_request = correlation(request_id)
        async with self.uow.factory() as session:
            view = await self.repo.plan(session, plan_id)
        if view.payload.actor_id == uuid.UUID(current.user_id):
            await self._revalidate(current, view, safe_request)
        else:
            await self.policy.reviewer(current, view.payload, safe_request)
            actor = await PostgresSubjectRepository(self.uow.factory).get_by_user_id(
                view.payload.actor_id
            )
            if actor is None:
                raise ActionError("subject_unavailable", 403)
            await self._revalidate(actor, view, safe_request)
        # Metadata-only final guard after any expensive binding/DB work.
        final = await self.policy.current(current)
        await self.policy.sources(final, view.payload, safe_request)
        if view.payload.actor_id == uuid.UUID(final.user_id):
            if final.security_version != view.payload.actor_security_version:
                raise ActionError("authority_changed", 403)
            for step in view.payload.steps:
                for resource in step.resources:
                    await self.policy.resource(
                        final, resource.resource_id, resource.policy_action, safe_request
                    )
        else:
            await self.policy.reviewer(final, view.payload, safe_request)
        if view.state == "contract_ready" and any(
            step.effect_class in {"R2", "R3"} for step in view.payload.steps
        ):
            try:
                await self._approval_for_ready(view, safe_request)
            except ActionError:
                view = view.model_copy(update={"state": "awaiting_approval"})
        return view

    @staticmethod
    def _request_from_plan(view: PlanView) -> PlanRequest:
        return PlanRequest(
            idempotency_key="validation-only",
            objective=view.payload.objective,
            purpose=view.payload.purpose,
            workspace_id=view.payload.workspace_id,
            context_packet_id=view.payload.context_packet_id,
            source_refs=view.payload.source_refs,
            steps=tuple(
                StepRequest(
                    step_key=step.step_key,
                    capability_id=step.capability_id,
                    capability_version=step.capability_version,
                    arguments=step.arguments,
                    dependencies=step.dependencies,
                    destination=step.destination,
                    expected_outcome=step.expected_outcome,
                )
                for step in view.payload.steps
            ),
            budget=view.payload.budget,
            reviewers=view.payload.reviewers,
            requested_internal_draft=view.payload.requested_internal_draft,
        )

    async def _revalidate(
        self,
        actor: Subject,
        view: PlanView,
        request_id: str,
        *,
        initial_session: AsyncSession | None = None,
    ) -> None:
        current = await self.policy.current(actor, initial_session=initial_session)
        if current.security_version != view.payload.actor_security_version:
            raise ActionError("authority_changed", 403)
        request = self._request_from_plan(view)
        rebuilt = await self._payload(current, request, request_id, initial_session=initial_session)
        if digest(rebuilt.model_dump(mode="json")) != view.plan_digest:
            raise ActionError("contract_changed")

    def _approval_binding(
        self, view: PlanView, reviewer: Subject, expires_at: datetime
    ) -> ApprovalBinding:
        steps = [step.model_dump(mode="json") for step in view.payload.steps]
        return ApprovalBinding(
            plan_id=view.plan_id,
            plan_digest=view.plan_digest,
            actor_id=view.payload.actor_id,
            actor_security_version=view.payload.actor_security_version,
            reviewer_id=uuid.UUID(reviewer.user_id),
            reviewer_security_version=reviewer.security_version,
            resources_digest=digest(
                {
                    "sources": [ref.model_dump(mode="json") for ref in view.payload.source_refs],
                    "resources": [step["resources"] for step in steps],
                }
            ),
            capabilities_digest=digest(
                [
                    {
                        key: step[key]
                        for key in (
                            "capability_id",
                            "capability_version",
                            "schema_digest",
                            "contract_digest",
                            "arguments_digest",
                            "effect_class",
                        )
                    }
                    for step in steps
                ]
            ),
            destinations_digest=digest([step["destination"] for step in steps]),
            limits_digest=digest(view.payload.budget.model_dump(mode="json")),
            expires_at=expires_at,
        )

    async def approve(
        self, subject: Subject, plan_id: uuid.UUID, request: ApprovalRequest, *, request_id: str
    ) -> ApprovalView:
        view = await self.read_plan(subject, plan_id, request_id=request_id)
        reviewer = await self.policy.reviewer(subject, view.payload, correlation(request_id))
        if not any(step.effect_class in {"R2", "R3"} for step in view.payload.steps):
            raise ActionError("approval_not_required")
        if request.expected_plan_digest != view.plan_digest:
            raise ActionError("approval_binding_changed")
        actor = await PostgresSubjectRepository(self.uow.factory).get_by_user_id(
            view.payload.actor_id
        )
        if actor is None:
            raise ActionError("subject_unavailable", 403)
        await self._revalidate(actor, view, correlation(request_id))
        binding = self._approval_binding(
            view,
            reviewer,
            self.clock()
            + timedelta(
                seconds=request.expires_in_seconds,
            ),
        )
        approval_id = uuid.uuid4()
        safe_request = correlation(request_id)
        async with self.uow.transaction() as session:
            await self.repo.plan(session, view.plan_id, lock=True)
            await lock_inputs(
                session, view.payload, (view.payload.actor_id, uuid.UUID(reviewer.user_id))
            )
            await session.execute(
                text("""
                SELECT approval_id FROM action_approvals WHERE plan_id=:id
                ORDER BY created_at DESC,approval_id DESC LIMIT 1 FOR SHARE
            """),
                {"id": view.plan_id},
            )
            # No actor frame may cross a later reviewer/input lock wait.
            await self._snapshot(session, actor, view.payload, safe_request, audit_fence=True)
            final_reviewer = await self._reviewer_snapshot(session, reviewer, view, safe_request)
            if final_reviewer.security_version != binding.reviewer_security_version:
                raise ActionError("authority_changed", 403)
            await session.execute(
                text("""
                INSERT INTO action_approvals(
                    approval_id,plan_id,reviewer_id,binding,decision,expires_at)
                VALUES (:id,:plan,:reviewer,CAST(:binding AS jsonb),:decision,:expires)
            """),
                {
                    "id": approval_id,
                    "plan": plan_id,
                    "reviewer": binding.reviewer_id,
                    "binding": canonical(binding.model_dump(mode="json")).decode(),
                    "decision": request.decision,
                    "expires": binding.expires_at,
                },
            )
            await self.repo.event(
                session,
                view,
                event_type="approval_recorded",
                reason_code=request.decision,
                request_id=safe_request,
            )
            await self._audit(session, reviewer, "action.approval.create", safe_request, plan=view)
        await self.read_plan(reviewer, view.plan_id, request_id=request_id)
        return ApprovalView(approval_id=approval_id, binding=binding, decision=request.decision)

    async def revoke_approval(
        self, subject: Subject, approval_id: uuid.UUID, *, request_id: str
    ) -> None:
        current = await self.policy.current(subject)
        async with self.uow.factory() as session:
            row = (
                (
                    await session.execute(
                        text("""
                SELECT plan_id,reviewer_id FROM action_approvals WHERE approval_id=:id
            """),
                        {"id": approval_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ActionError("not_found", 404)
        view = await self.read_plan(current, row["plan_id"], request_id=request_id)
        if uuid.UUID(current.user_id) not in {view.payload.actor_id, row["reviewer_id"]}:
            raise ActionError("not_found", 404)
        safe_request = correlation(request_id)
        async with self.uow.transaction() as session:
            await self.repo.plan(session, view.plan_id, lock=True)
            # Revocation is metadata-only but still requires a current actor
            # after its approval row and existing audit-chain waits.
            await lock_subjects(session, (uuid.UUID(current.user_id),))
            changed = await session.execute(
                text("""
                UPDATE action_approvals SET revoked_at=now(),revoked_by=:actor
                WHERE approval_id=:id AND revoked_at IS NULL
            """),
                {"id": approval_id, "actor": uuid.UUID(current.user_id)},
            )
            if getattr(changed, "rowcount", 0) != 1:
                raise ActionError("approval_unavailable")
            await session.execute(text("SELECT pg_advisory_xact_lock(827004)"))
            final = await self.policy.session_current(session, current)
            if final.security_version != current.security_version or uuid.UUID(
                final.user_id
            ) not in {view.payload.actor_id, row["reviewer_id"]}:
                raise ActionError("authority_changed", 403)
            await session.execute(
                text("""
                UPDATE action_runs SET state='awaiting_approval',updated_at=now() WHERE run_id=:run
            """),
                {"run": view.run_id},
            )
            await self.repo.event(
                session,
                view,
                event_type="approval_revoked",
                reason_code="approval_revoked",
                request_id=safe_request,
            )
            await self._audit(session, current, "action.approval.revoke", safe_request, plan=view)

    async def _approval_for_ready(
        self, view: PlanView, request_id: str
    ) -> tuple[ApprovalView, Subject] | None:
        if not any(step.effect_class in {"R2", "R3"} for step in view.payload.steps):
            return None
        async with self.uow.factory() as session:
            approvals = await self.repo.approvals(session, view.plan_id)
        if not approvals or approvals[0].decision != "approved":
            raise ActionError("approval_required")
        approval = approvals[0]
        if approval.revoked_at is not None or approval.binding.expires_at <= self.clock():
            raise ActionError("approval_unavailable")
        reviewer = await PostgresSubjectRepository(self.uow.factory).get_by_user_id(
            approval.binding.reviewer_id,
        )
        if reviewer is None:
            raise ActionError("approval_unavailable")
        await self.policy.reviewer(reviewer, view.payload, request_id)
        if self._approval_binding(view, reviewer, approval.binding.expires_at) != approval.binding:
            raise ActionError("approval_binding_changed")
        return approval, reviewer

    async def validate_ready(
        self, subject: Subject, plan_id: uuid.UUID, *, request_id: str
    ) -> PlanView:
        view = await self.read_plan(subject, plan_id, request_id=request_id)
        actor = await PostgresSubjectRepository(self.uow.factory).get_by_user_id(
            view.payload.actor_id
        )
        if actor is None:
            raise ActionError("subject_unavailable", 403)
        safe_request = correlation(request_id)
        await self._revalidate(actor, view, safe_request)
        authorized = await self._approval_for_ready(view, safe_request)
        async with self.uow.transaction() as session:
            locked = await self.repo.plan(session, plan_id, lock=True)
            if locked.state == "cancelled":
                raise ActionError("plan_cancelled")
            actors: tuple[uuid.UUID, ...] = (view.payload.actor_id,)
            if authorized is not None:
                actors += (uuid.UUID(authorized[1].user_id),)
            await lock_inputs(session, view.payload, actors)
            if authorized is not None:
                approval, reviewer = authorized
                latest = (
                    (
                        await session.execute(
                            text("""
                    SELECT approval_id,decision,revoked_at,expires_at,binding FROM action_approvals
                    WHERE plan_id=:id ORDER BY created_at DESC,approval_id DESC LIMIT 1 FOR SHARE
                """),
                            {"id": plan_id},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    latest is None
                    or latest["approval_id"] != approval.approval_id
                    or latest["decision"] != "approved"
                    or latest["revoked_at"] is not None
                    or latest["expires_at"] <= self.clock()
                ):
                    raise ActionError("approval_unavailable")
            await self._snapshot(session, actor, view.payload, safe_request, audit_fence=True)
            if authorized is not None:
                final_reviewer = await self._reviewer_snapshot(
                    session, reviewer, view, safe_request
                )
                assert latest is not None  # Validated before both final frames.
                binding = ApprovalBinding.model_validate_json(json.dumps(latest["binding"]))
                if (
                    binding.expires_at <= self.clock()
                    or self._approval_binding(view, final_reviewer, binding.expires_at) != binding
                ):
                    raise ActionError("approval_binding_changed")
            await session.execute(
                text("""
                UPDATE action_runs SET state='contract_ready',updated_at=now() WHERE run_id=:run
            """),
                {"run": view.run_id},
            )
            ready = await self.repo.plan(session, plan_id)
            await self.repo.event(
                session,
                ready,
                event_type="ready_validated",
                reason_code="contract_ready",
                request_id=safe_request,
            )
            await self.repo.receipt(
                session, ready, kind="contract_validation", request_id=safe_request
            )
            await self._audit(session, actor, "action.plan.validate", safe_request, plan=ready)
        result = await self.read_plan(subject, plan_id, request_id=request_id)
        await self._approval_for_ready(result, safe_request)
        return result

    async def approvals(
        self, subject: Subject, plan_id: uuid.UUID, *, request_id: str
    ) -> tuple[ApprovalView, ...]:
        await self.read_plan(subject, plan_id, request_id=request_id)
        async with self.uow.factory() as session:
            return await self.repo.approvals(session, plan_id)

    async def events(
        self, subject: Subject, plan_id: uuid.UUID, *, request_id: str
    ) -> tuple[ActionEvent, ...]:
        view = await self.read_plan(subject, plan_id, request_id=request_id)
        async with self.uow.factory() as session:
            return await self.repo.events(session, view.run_id)

    async def receipts(
        self, subject: Subject, plan_id: uuid.UUID, *, request_id: str
    ) -> tuple[ContractReceipt, ...]:
        view = await self.read_plan(subject, plan_id, request_id=request_id)
        async with self.uow.factory() as session:
            return await self.repo.receipts(session, view.run_id)

    async def reserve_budget(
        self,
        subject: Subject,
        plan_id: uuid.UUID,
        units: BudgetUnits,
        *,
        idempotency_key: str,
        request_id: str,
    ) -> BudgetUnits:
        """Internal-only reservation, shared by child work; not reported execution usage."""
        view = await self.read_plan(subject, plan_id, request_id=request_id)
        if view.payload.actor_id != uuid.UUID(subject.user_id):
            raise ActionError("not_found", 404)
        event_key = digest({"reservation": idempotency_key})
        safe_request = correlation(request_id)
        if not 8 <= len(idempotency_key) <= 200:
            raise ActionError("input_invalid", 422)
        current = await self.policy.current(subject)
        async with self.uow.transaction() as session:
            locked = await self.repo.plan(session, plan_id, lock=True)
            await self._snapshot(session, current, view.payload, safe_request, audit_fence=True)
            existing = (
                await session.execute(
                    text("""
                SELECT usage FROM action_events WHERE run_id=:run AND event_key=:key
            """),
                    {"run": view.run_id, "key": event_key},
                )
            ).scalar_one_or_none()
            usage = units.model_dump(mode="json")
            if existing is not None:
                if existing != usage:
                    raise ActionError("idempotency_conflict")
                return locked.reserved
            totals = {
                key: locked.reserved.model_dump()[key] + value for key, value in usage.items()
            }
            if any(value > view.payload.budget.model_dump()[key] for key, value in totals.items()):
                raise ActionError("budget_exhausted", 429)
            reserved = BudgetUnits.model_validate(totals)
            await session.execute(
                text("""
                UPDATE action_runs SET budget_reserved=CAST(:reserved AS jsonb),updated_at=now()
                WHERE run_id=:run
            """),
                {"reserved": canonical(totals).decode(), "run": view.run_id},
            )
            await self.repo.event(
                session,
                view,
                event_type="budget_reserved",
                reason_code="budget_reserved",
                request_id=safe_request,
                event_key=event_key,
                usage=units,
            )
            await self._audit(session, subject, "action.budget.reserve", safe_request, plan=view)
            return reserved
