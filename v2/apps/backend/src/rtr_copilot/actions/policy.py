"""Current authority before content; existing real policy actions only."""

import uuid
from contextlib import suppress
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.actions.authority import (
    LeafCheckpoint,
    LeafRequest,
    batch_leaf_attributes,
    lock_subjects,
    project_subject,
)
from rtr_copilot.actions.lineage_overlay import final_inherited_checkpoint
from rtr_copilot.actions.models import (
    BoundStep,
    CapabilitySpec,
    Destination,
    PlanPayload,
    PlanRequest,
    PolicyClassification,
    ResourceBinding,
    StepRequest,
)
from rtr_copilot.actions.registry import ActionError, digest, hashes, validate_input
from rtr_copilot.actions.source_metadata import (
    InitialClockDenied,
    UnsupportedSourceTopology,
    resolve_action_sources,
)
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.context.models import ContextError, SourceResolution
from rtr_copilot.context.sources import revalidate_sot_references
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.models import BindRequest, TemplateSchema
from rtr_copilot.documents.service import DocumentOSService
from rtr_copilot.repositories.resources import ResourceRepository

policy = PolicyEngine(StructuredAuditSink())


async def current_principal_ids(session: AsyncSession, subject: Subject) -> set[uuid.UUID]:
    rows = (
        await session.execute(
            text("""
        SELECT group_id AS principal_id FROM subject_groups
        WHERE subject_id=:id AND valid_from<=statement_timestamp()
          AND (expires_at IS NULL OR expires_at>statement_timestamp())
        UNION SELECT role_id FROM subject_roles
        WHERE subject_id=:id AND valid_from<=statement_timestamp()
          AND (expires_at IS NULL OR expires_at>statement_timestamp())
        UNION SELECT CAST(scope_key AS uuid) FROM subject_scopes
        WHERE subject_id=:id AND valid_from<=statement_timestamp()
          AND (expires_at IS NULL OR expires_at>statement_timestamp())
          AND scope_key ~* :uuid_pattern
    """),
            {
                "id": uuid.UUID(subject.user_id),
                "uuid_pattern": (
                    "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
                ),
            },
        )
    ).scalars()
    return {uuid.UUID(subject.user_id), *(uuid.UUID(str(value)) for value in rows)}


async def current_effective_attributes(
    session: AsyncSession,
    resource_id: uuid.UUID,
    *,
    action: str,
    principal_ids: set[uuid.UUID],
) -> Any:
    """Final denial uses statement time, not transaction-start PostgreSQL now()."""
    effective = await ResourceRepository().effective_policy_attributes(
        session,
        resource_id,
        action=action,
        principal_ids=principal_ids,
    )
    if effective is not None:
        denied = await session.scalar(
            text("""
            SELECT EXISTS(SELECT 1 FROM acl_entries
            WHERE resource_id=ANY(:lineage) AND principal_id=ANY(:principals)
              AND action=:action AND effect='deny' AND valid_from<=statement_timestamp()
              AND (expires_at IS NULL OR expires_at>statement_timestamp()))
        """),
            {"lineage": effective[1], "principals": list(principal_ids), "action": action},
        )
        effective[0].explicit_deny = effective[0].explicit_deny or bool(denied)
        # Shared resource policy uses transaction time. An action can wait on a
        # final source fence after that time, so expired inherited ALLOW cannot
        # remain authority for a non-owner private-context effect/disclosure.
        owner = effective[0].owner_id
        private_owner = owner is not None and owner in {
            str(principal) for principal in principal_ids
        }
        if effective[0].source_zone == "private_context" and not private_owner:
            allowed = await session.scalar(text("""
                SELECT EXISTS(SELECT 1 FROM acl_entries
                WHERE resource_id=ANY(:lineage) AND principal_id=ANY(:principals)
                  AND action=:action AND effect='allow' AND valid_from<=statement_timestamp()
                  AND (expires_at IS NULL OR expires_at>statement_timestamp()))
            """), {"lineage": effective[1], "principals": list(principal_ids), "action": action})
            # Never undo an existing deny. A grant born during a transaction may
            # conservatively wait for a fresh transaction; no stale grant wins.
            effective[0].explicit_deny = effective[0].explicit_deny or not bool(allowed)
    return effective


class ActionPolicy:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def current(self, subject: Subject,
                      *, initial_session: AsyncSession | None = None) -> Subject:
        if initial_session is not None:
            return (await project_subject(initial_session, uuid.UUID(subject.user_id))).subject
        async with self.uow.factory() as session:
            return (await project_subject(session, uuid.UUID(subject.user_id))).subject

    async def session_current(self, session: AsyncSession, subject: Subject) -> Subject:
        """Lock first, NEW projection next. Never aggregate authority in a waiting lock."""
        actor = uuid.UUID(subject.user_id)
        await lock_subjects(session, (actor,))
        return (await project_subject(session, actor)).subject

    async def checkpoint(
        self, session: AsyncSession, subject: Subject, requests: list[LeafRequest],
        *, clock_retry: bool = False,
    ) -> LeafCheckpoint:
        frame = await batch_leaf_attributes(session, uuid.UUID(subject.user_id), requests,
                                            clock_retry=clock_retry)
        if not frame.unsupported:
            return frame
        if clock_retry:
            raise UnsupportedSourceTopology()
        # Only nonleaf topology uses the unchanged inherited-lineage repository.
        # No frame/session cache; close this checkpoint with a new projection.
        fallback = {}
        for resource_id, action in frame.unsupported:
            fallback[(resource_id, action)] = await current_effective_attributes(
                session, resource_id, action=action, principal_ids=set(frame.principal_ids)
            )
        final = await final_inherited_checkpoint(session, uuid.UUID(subject.user_id),
                                                  requests, fallback)
        if (final.principal_ids != frame.principal_ids
                or final.subject.security_version != frame.subject.security_version
                or final.unsupported != frame.unsupported):
            raise ActionError("authority_changed", 403)
        return LeafCheckpoint(final.subject, final.principal_ids,
                              final.attributes, frozenset())

    def manage_registry(self, subject: Subject, request_id: str) -> None:
        if not policy.decide(
            subject,
            "manage_policies",
            ResourceAttributes(
                resource_id="action_capability_registry",
                classification="public",
            ),
            PolicyContext(request_id=request_id),
        ).allow:
            raise ActionError("forbidden", 403)

    async def sources(
        self, subject: Subject, plan: PlanRequest | PlanPayload, request_id: str,
        *, initial_session: AsyncSession | None = None,
    ) -> SourceResolution:
        try:
            result = None
            effects = {"sot.read": "R0", "documents.create_draft": "R1"}
            builtin = bool(plan.steps) and all(
                step.capability_id in effects and step.capability_version == "2"
                for step in plan.steps
            )
            if isinstance(plan, PlanPayload):
                builtin = builtin and all(step.effect_class == effects[step.capability_id]
                                          for step in plan.steps)
            if initial_session is not None:
                if not builtin:
                    raise UnsupportedSourceTopology()
                result = await resolve_action_sources(
                    subject, plan.source_refs, factory=self.uow.factory,
                    use_class=plan.purpose, request_id=request_id,
                    initial_session=initial_session,
                )
            elif builtin:
                with suppress(UnsupportedSourceTopology):
                    result = await resolve_action_sources(
                        subject, plan.source_refs, factory=self.uow.factory,
                        use_class=plan.purpose, request_id=request_id,
                    )
            if result is None:
                result = await revalidate_sot_references(
                    subject,
                    plan.source_refs,
                    factory=self.uow.factory,
                    use_class=plan.purpose,
                    request_id=request_id,
                    include_text=False,
                )
        except ContextError as error:
            raise ActionError("source_unavailable", 403) from error
        if result.gaps or len(result.sources) != len(plan.source_refs):
            raise ActionError("source_unavailable", 403)
        return result

    async def scope(self, subject: Subject, request: PlanRequest | PlanPayload,
                    *, initial_session: AsyncSession | None = None) -> None:
        # .3 has no external workspace authority. Private namespace is the
        # server actor UUID, never an arbitrary client-chosen UUID grant.
        if request.workspace_id is not None and request.workspace_id != uuid.UUID(subject.user_id):
            raise ActionError("scope_unavailable", 403)
        if request.context_packet_id is not None:
            # Packet linkage is metadata only; source refs are independently
            # revalidated and packet body cannot become plan authority.
            async def packet(session: AsyncSession) -> Any:
                return (await session.execute(text("""
                    SELECT packet_id,scope_kind,scope_key FROM context_packets
                    WHERE packet_id=:id AND owner_subject_id=:actor AND use_class=:purpose
                """), {"id": request.context_packet_id, "actor": uuid.UUID(subject.user_id),
                        "purpose": request.purpose})).mappings().one_or_none()

            if initial_session is None:
                async with self.uow.factory() as session:
                    owned = await packet(session)
            else:
                owned = await packet(initial_session)
            if (
                owned is None
                or (
                    owned["scope_kind"] == "project"
                    and str(owned["scope_key"]) not in subject.projects
                )
                or (
                    owned["scope_kind"] == "department"
                    and str(owned["scope_key"]) not in subject.departments
                )
            ):
                raise ActionError("scope_unavailable", 403)

    async def resource(
        self,
        subject: Subject,
        resource_id: uuid.UUID,
        action: str,
        request_id: str,
        *,
        proposed_by: str | None = None,
        initial_session: AsyncSession | None = None,
    ) -> Any:
        if initial_session is not None:
            return await self.session_resource(
                initial_session, subject, resource_id, action, request_id,
                proposed_by=proposed_by, clock_retry=True,
            )
        async with self.uow.factory() as session:
            return await self.session_resource(
                session, subject, resource_id, action, request_id, proposed_by=proposed_by
            )

    async def session_resource(
        self,
        session: AsyncSession,
        subject: Subject,
        resource_id: uuid.UUID,
        action: str,
        request_id: str,
        *,
        proposed_by: str | None = None,
        clock_retry: bool = False,
    ) -> Any:
        frame = await self.checkpoint(session, subject, [LeafRequest(resource_id, action)],
                                      clock_retry=clock_retry)
        if clock_retry and frame.subject.security_version != subject.security_version:
            raise ActionError("authority_changed", 403)
        attributes = frame.attributes[(resource_id, action)]
        if attributes is None:
            raise ActionError("resource_unavailable", 403)
        attributes[0].proposed_by = proposed_by
        if not policy.decide(
            frame.subject, action, attributes[0], PolicyContext(request_id=request_id)
        ).allow:
            if clock_retry and (resource_id, action) in frame.clock_denials:
                raise InitialClockDenied()
            raise ActionError("resource_unavailable", 403)
        return attributes[0]

    async def step(
        self,
        subject: Subject,
        step: StepRequest,
        spec: CapabilitySpec,
        sources: SourceResolution,
        request: PlanRequest | PlanPayload,
        request_id: str,
        *, initial_session: AsyncSession | None = None,
    ) -> BoundStep:
        validate_input(step.arguments, spec.input_schema)
        destination = step.destination or Destination(kind=spec.allowed_destinations[0])
        if destination.kind not in spec.allowed_destinations:
            raise ActionError("destination_unavailable", 403)
        resources: list[ResourceBinding] = []
        if spec.implementation_ref in {"sot.read", "contract_only"}:
            matches = [
                source
                for source in sources.sources
                if source.reference.record_key == step.arguments.get("record_key")
            ]
            if len(matches) != 1:
                raise ActionError("source_unavailable", 403)
            source = matches[0]
            await self.resource(subject, source.record_id, spec.policy_action, request_id,
                                initial_session=initial_session)
            resources.append(
                ResourceBinding(
                    resource_id=source.record_id,
                    resource_type="record",
                    version_id=source.reference.record_version_id,
                    content_sha256=source.reference.content_sha256,
                    classification=cast(PolicyClassification, source.classification),
                    policy_action=spec.policy_action,
                )
            )
        elif spec.implementation_ref == "documents.create_draft":
            if not request.requested_internal_draft:
                raise ActionError("explicit_draft_request_required", 403)
            template_id = uuid.UUID(step.arguments["template_version_id"])
            attributes = await self.resource(subject, template_id, "render", request_id)
            async with self.uow.factory() as session:
                template = (
                    (
                        await session.execute(
                            text("""
                    SELECT tv.source_sha256,tv.field_schema,tv.renderer_version,tv.status,
                      t.document_class,t.lifecycle FROM template_versions tv
                    JOIN templates t USING(template_id) WHERE tv.version_id=:id
                """),
                            {"id": template_id},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if (
                template is None
                or template["status"] != "approved"
                or template["lifecycle"] != "approved"
                or template["document_class"] != "internal"
            ):
                raise ActionError("template_unavailable", 403)
            schema = TemplateSchema.model_validate(template["field_schema"])
            allowed_fields = {
                binding.field_path for binding in schema.bindings if binding.source == "user"
            }
            parameters = step.arguments["parameters"]
            locked_keys = {
                binding.record_key for binding in schema.bindings if binding.source == "locked_fact"
            }
            if set(parameters) - allowed_fields or any(
                sum(source.reference.record_key == key for source in sources.sources) != 1
                for key in locked_keys
            ):
                raise ActionError("arguments_invalid", 422)
            # Existing template bounds/types/fact contracts are the authority;
            # no renderer/storage/network effect is called by bind.
            binding = await DocumentOSService(self.uow).bind(
                subject,
                template_id,
                BindRequest(parameters=parameters),
                request_id=request_id,
            )
            if not binding.valid:
                raise ActionError("binding_unavailable", 422)
            references = {source.reference.record_version_id for source in sources.sources}
            if any(
                field.record_version_id not in references
                for field in binding.fields
                if field.source == "locked_fact"
            ):
                raise ActionError("source_unavailable", 403)
            for source in sources.sources:
                if source.reference.record_key in locked_keys:
                    resources.append(
                        ResourceBinding(
                            resource_id=source.record_id,
                            resource_type="record",
                            version_id=source.reference.record_version_id,
                            content_sha256=source.reference.content_sha256,
                            classification=cast(PolicyClassification, source.classification),
                            policy_action="view",
                        )
                    )
            resources.append(
                ResourceBinding(
                    resource_id=template_id,
                    resource_type="template_version",
                    version_id=template_id,
                    content_sha256=digest(
                        {
                            "source": str(template["source_sha256"]),
                            "schema": template["field_schema"],
                            "renderer": template["renderer_version"],
                            "document_class": template["document_class"],
                        }
                    ),
                    classification=cast(PolicyClassification, attributes.classification),
                    policy_action="render",
                )
            )
        else:
            raise ActionError("capability_unavailable", 404)
        if destination.kind == "resource":
            assert destination.resource_id is not None
            await self.resource(subject, destination.resource_id, spec.policy_action, request_id)
        contract_hash, schema_hash = hashes(spec)
        return BoundStep(
            step_key=step.step_key,
            capability_id=spec.capability_id,
            capability_version=spec.version,
            contract_digest=contract_hash,
            schema_digest=schema_hash,
            effect_class=spec.effect_class,
            arguments=step.arguments,
            arguments_digest=digest(step.arguments),
            dependencies=tuple(sorted(step.dependencies)),
            resources=tuple(resources),
            destination=destination,
            expected_outcome=step.expected_outcome,
        )

    async def reviewer(self, subject: Subject, payload: PlanPayload, request_id: str) -> Subject:
        current = await self.current(subject)
        if uuid.UUID(current.user_id) not in payload.reviewers or current.user_id == str(
            payload.actor_id
        ):
            raise ActionError("not_found", 404)
        await self.sources(current, payload, request_id)
        for step in payload.steps:
            for resource in step.resources:
                await self.resource(current, resource.resource_id, "view", request_id)
                await self.resource(
                    current,
                    resource.resource_id,
                    "approve",
                    request_id,
                    proposed_by=str(payload.actor_id),
                )
        return current
