"""One-shot Action metadata projections. Never a session/request permission cache."""

import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import (
    PolicyContext,
    ResourceAttributes,
    Role,
    Subject,
    TemporaryEntitlement,
)
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.repositories.resources import CLASSIFICATION_TO_POLICY, ResourceRecord

UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"

# No FOR SHARE here: membership must be projected in a NEW statement AFTER
# every potentially blocking lock. Entitlement ROWS retain transaction-time
# semantics; PolicyEngine still applies fresh TemporaryEntitlement.active().
MEMBERSHIPS = """
rm AS (
 SELECT sr.role_id,r.key FROM subject_roles sr JOIN roles r USING(role_id)
 WHERE sr.subject_id=:actor AND sr.valid_from<=statement_timestamp()
   AND (sr.expires_at IS NULL OR sr.expires_at>statement_timestamp())
), gm AS (
 SELECT sg.group_id,g.provider_group_key FROM subject_groups sg JOIN groups g USING(group_id)
 WHERE sg.subject_id=:actor AND sg.valid_from<=statement_timestamp()
   AND (sg.expires_at IS NULL OR sg.expires_at>statement_timestamp())
), sm AS (
 SELECT scope_type,scope_key FROM subject_scopes WHERE subject_id=:actor
   AND valid_from<=statement_timestamp()
   AND (expires_at IS NULL OR expires_at>statement_timestamp())
), em AS (
 SELECT entitlement_id,action,resource_id,conditions->'classification' classification,expires_at
 FROM entitlements WHERE subject_id=:actor AND active AND effect='allow'
   AND expires_at IS NOT NULL AND expires_at>transaction_timestamp()
), pm AS (
 SELECT CAST(:actor AS uuid) id UNION SELECT role_id FROM rm UNION SELECT group_id FROM gm
 UNION SELECT CAST(scope_key AS uuid) FROM sm WHERE scope_key ~* :uuid_pattern
), identity AS (
 SELECT s.user_id,s.issuer,s.provider_sub,s.email,s.canonical_domain,s.display_name,
   s.status,s.security_version,ARRAY(SELECT DISTINCT key FROM rm) roles,
   ARRAY(SELECT DISTINCT provider_group_key FROM gm) groups,
   COALESCE((SELECT jsonb_agg(jsonb_build_object('type',scope_type,'key',scope_key)) FROM sm),
            '[]'::jsonb) scopes,
   COALESCE((SELECT jsonb_agg(jsonb_build_object('action',action,'resource_id',resource_id,
     'classification',classification,'expires_at',expires_at) ORDER BY entitlement_id) FROM em),
     '[]'::jsonb) entitlements
 FROM subjects s WHERE s.user_id=:actor
)
"""


@dataclass(frozen=True)
class SubjectProjection:
    subject: Subject
    principal_ids: frozenset[uuid.UUID]


@dataclass(frozen=True)
class LeafRequest:
    resource_id: uuid.UUID
    action: str
    expected_type: str | None = None


@dataclass(frozen=True)
class LeafCheckpoint(SubjectProjection):
    attributes: dict[tuple[uuid.UUID, str], tuple[ResourceAttributes, list[uuid.UUID]] | None]
    unsupported: frozenset[tuple[uuid.UUID, str]]
    clock_denials: frozenset[tuple[uuid.UUID, str]] = frozenset()


def projection(row: Any) -> SubjectProjection:
    body = row["identity"] if row is not None else None
    if body is None or body["status"] != "active":
        raise ActionError("subject_unavailable", 403)
    try:
        subject = Subject(
            user_id=str(body["user_id"]), issuer=body["issuer"], sub=body["provider_sub"],
            email=body["email"] or "", canonical_domain=body["canonical_domain"] or "",
            display_name=body["display_name"], status=body["status"],
            security_version=body["security_version"],
            roles={Role(value) for value in body["roles"]} or {Role.STAFF},
            groups=set(body["groups"]),
            departments={s["key"] for s in body["scopes"] if s["type"] == "department"},
            projects={s["key"] for s in body["scopes"] if s["type"] == "project"},
            temporary_entitlements=[TemporaryEntitlement.model_validate(e)
                                    for e in body["entitlements"]],
        )
        return SubjectProjection(subject, frozenset(uuid.UUID(str(p))
                                                  for p in row["principal_ids"]))
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise ActionError("subject_unavailable", 403) from error


async def project_subject(session: AsyncSession, actor_id: uuid.UUID) -> SubjectProjection:
    row = (await session.execute(text("WITH " + MEMBERSHIPS + """
        SELECT (SELECT to_jsonb(i) FROM identity i) identity,
          ARRAY(SELECT id FROM pm) principal_ids
    """), {"actor": actor_id, "uuid_pattern": UUID_PATTERN})).mappings().one()
    return projection(row)


async def lock_subjects(session: AsyncSession, actor_ids: Iterable[uuid.UUID]) -> None:
    actors = sorted(set(actor_ids), key=str)
    rows = (await session.execute(text("""
        SELECT user_id FROM subjects WHERE user_id=ANY(:actors) ORDER BY user_id FOR SHARE
    """), {"actors": actors})).scalars().all()
    if len(rows) != len(actors):
        raise ActionError("subject_unavailable", 403)


def leaf_attributes(body: Any, principals: frozenset[uuid.UUID]) -> ResourceAttributes | None:
    if body["resource"] is None:
        return None
    try:
        resource = ResourceRecord.model_validate(body["resource"])
        if resource.lifecycle_state in {"deleted", "quarantined"}:
            return None
        private_without_allow = (
            resource.source_zone == "private_context"
            and resource.owner_subject_id not in principals
            and not (body["allow_tx"] and body["allow_current"])
        )
        return ResourceAttributes(
            resource_id=str(resource.resource_id),
            owner_id=str(resource.owner_subject_id) if resource.owner_subject_id else None,
            classification=CLASSIFICATION_TO_POLICY[resource.classification],
            source_zone=resource.source_zone, lifecycle_state=resource.lifecycle_state,
            department=str(resource.department_id) if resource.department_id else None,
            project=str(resource.project_id) if resource.project_id else None,
            explicit_deny=body["deny_tx"] or body["deny_current"] or private_without_allow,
        )
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise ActionError("resource_unavailable", 403) from error


LEAF_ACL = """
 EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=q.resource_id AND a.action=q.action
   AND a.principal_id IN(SELECT id FROM pm) AND a.effect='deny'
   AND a.valid_from<=transaction_timestamp()
   AND (a.expires_at IS NULL OR a.expires_at>transaction_timestamp())) deny_tx,
 EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=q.resource_id AND a.action=q.action
   AND a.principal_id IN(SELECT id FROM pm) AND a.effect='deny'
   AND a.valid_from<=statement_timestamp()
   AND (a.expires_at IS NULL OR a.expires_at>statement_timestamp())) deny_current,
 EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=q.resource_id AND a.action=q.action
   AND a.principal_id IN(SELECT id FROM pm) AND a.effect='allow'
   AND a.valid_from<=transaction_timestamp()
   AND (a.expires_at IS NULL OR a.expires_at>transaction_timestamp())) allow_tx,
 EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=q.resource_id AND a.action=q.action
   AND a.principal_id IN(SELECT id FROM pm) AND a.effect='allow'
   AND a.valid_from<=statement_timestamp()
   AND (a.expires_at IS NULL OR a.expires_at>statement_timestamp())) allow_current
"""


async def batch_leaf_attributes(
    session: AsyncSession, actor_id: uuid.UUID, requests: Sequence[LeafRequest],
    *, clock_retry: bool = False,
) -> LeafCheckpoint:
    # Bounded host bindings, not arbitrary client query programs. The result is
    # consumed within this checkpoint; every call reprojects actual authority.
    requested = bounded_leaf_requests(requests)
    rows = [{"resource_id": str(r.resource_id), "action": r.action}
            for r in requested.values()]
    result = (await session.execute(text("WITH " + MEMBERSHIPS + """
        , requested AS (SELECT * FROM jsonb_to_recordset(CAST(:requests AS jsonb))
            AS q(resource_id uuid,action text)), leaves AS (
        SELECT q.resource_id,q.action,to_jsonb(r) resource,
    """ + LEAF_ACL + """
        FROM requested q LEFT JOIN resources r ON r.resource_id=q.resource_id)
        SELECT (SELECT to_jsonb(i) FROM identity i) identity,
          ARRAY(SELECT id FROM pm) principal_ids,
          COALESCE((SELECT jsonb_agg(to_jsonb(l)) FROM leaves l),'[]'::jsonb) leaves
    """), {"actor": actor_id, "uuid_pattern": UUID_PATTERN,
            "requests": json.dumps(rows)})).mappings().one()
    return parse_leaf_checkpoint(result, requested, clock_retry=clock_retry)


def bounded_leaf_requests(
    requests: Sequence[LeafRequest],
) -> dict[tuple[uuid.UUID, str], LeafRequest]:
    requested: dict[tuple[uuid.UUID, str], LeafRequest] = {}
    for request in requests:
        key = (request.resource_id, request.action)
        previous = requested.get(key)
        if previous is not None and previous.expected_type != request.expected_type:
            raise ActionError("resource_unavailable", 403)
        requested[key] = request
    # Existing 20 source refs + 20 step resources, reviewer view/approve.
    # This bounds internal metadata keys; it changes no public plan limit.
    if len(requested) > 80:
        raise ActionError("resource_unavailable", 403)
    return requested


def parse_leaf_checkpoint(
    result: Any, requested: dict[tuple[uuid.UUID, str], LeafRequest],
    *, clock_retry: bool = False,
) -> LeafCheckpoint:
    """Pure parsing only: no permission query/wait after the final statement."""
    current = projection(result)
    attributes: dict[tuple[uuid.UUID, str], tuple[ResourceAttributes, list[uuid.UUID]] | None] = {}
    unsupported: set[tuple[uuid.UUID, str]] = set()
    clock_denials: set[tuple[uuid.UUID, str]] = set()
    for body in result["leaves"]:
        resource_id = uuid.UUID(body["resource_id"])
        key = (resource_id, body["action"])
        resource = body["resource"]
        expected = requested[key].expected_type
        if resource is not None and expected is not None and resource["resource_type"] != expected:
            attributes[key] = None
            continue
        if resource is not None and resource["resource_type"] not in {"record", "template_version"}:
            unsupported.add(key)
            continue
        value = leaf_attributes(body, current.principal_ids)
        attributes[key] = (value, [resource_id]) if value is not None else None
        if clock_retry and clock_retry_allowed(body, current):
            clock_denials.add(key)
    return LeafCheckpoint(current.subject, current.principal_ids,
                          attributes, frozenset(unsupported), frozenset(clock_denials))


def clock_retry_allowed(body: Any, current: SubjectProjection) -> bool:
    """Retry eligibility ONLY; never return current-only attributes as permission."""
    resource = body["resource"]
    if (resource is None or resource["resource_type"] != "record"
            or resource["source_zone"] != "sot" or resource["lifecycle_state"] != "active"
            or not body["deny_tx"] or body["deny_current"]):
        return False
    conservative = leaf_attributes(body, current.principal_ids)
    if conservative is None:
        return False
    comparison = conservative.model_copy(update={"explicit_deny": False})
    # Pure policy comparison emits no speculative ALLOW audit. Actual guarded
    # work still uses the conservative attributes and a fresh final checkpoint.
    return PolicyEngine(StructuredAuditSink())._decide(
        current.subject, body["action"], comparison, PolicyContext(request_id="initial-retry-only")
    ).allow
