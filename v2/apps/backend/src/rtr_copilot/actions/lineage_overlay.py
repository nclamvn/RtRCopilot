"""Final Action-only inherited metadata overlay; shared discovery stays unchanged."""

import json
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.actions.authority import (
    LEAF_ACL,
    MEMBERSHIPS,
    UUID_PATTERN,
    LeafCheckpoint,
    LeafRequest,
    bounded_leaf_requests,
    parse_leaf_checkpoint,
)
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.models import ResourceAttributes
from rtr_copilot.repositories.resources import CLASSIFICATION_TO_POLICY, ResourceRecord

Effective = tuple[ResourceAttributes, list[uuid.UUID]] | None

# These are exactly the bounded associations traversed by ResourceRepository:
# leaf -> optional version -> optional document -> source/upload parent. Keep
# the old UNION ALL LIMIT1 and latest-created-only choice; neither is magically
# deterministic for ambiguous legacy data. A different chosen path fails closed.
INHERITED = """
 , inherited_requests AS (
   SELECT * FROM jsonb_to_recordset(CAST(:inherited AS jsonb))
     AS q(resource_id uuid,action text,lineage uuid[],old_deny boolean)
 ), associations AS (
   SELECT q.*,r.resource_type,CASE WHEN r.resource_type='document_version' THEN r.resource_id
     WHEN r.resource_type IN('rendition','object') THEN v.version_id END version_id
   FROM inherited_requests q LEFT JOIN resources r ON r.resource_id=q.resource_id
   LEFT JOIN LATERAL (
     SELECT version_id FROM document_versions
       WHERE r.resource_type='object' AND object_id=q.resource_id
     UNION ALL SELECT version_id FROM renditions
       WHERE (r.resource_type='object' AND object_id=q.resource_id)
         OR (r.resource_type='rendition' AND rendition_id=q.resource_id)
     LIMIT 1
   ) v ON true
 ), documents_for_path AS (
   SELECT a.*,CASE WHEN a.resource_type='document' THEN a.resource_id
     ELSE dv.document_id END document_id
   FROM associations a LEFT JOIN document_versions dv ON dv.version_id=a.version_id
 ), paths AS (
   SELECT a.*,d.source_id,u.parent_resource_id,
     (a.resource_type IS NOT NULL
       AND (a.resource_type<>'rendition' OR a.version_id IS NOT NULL)
       AND (a.document_id IS NULL OR d.document_id IS NOT NULL)) path_present,
     ARRAY(SELECT member FROM unnest(ARRAY[a.resource_id,
       CASE WHEN a.resource_type IN('object','rendition') THEN a.version_id END,
       a.document_id,d.source_id,u.parent_resource_id]) WITH ORDINALITY p(member,position)
       WHERE member IS NOT NULL GROUP BY member ORDER BY min(position)) current_path
   FROM documents_for_path a LEFT JOIN documents d ON d.document_id=a.document_id
   LEFT JOIN LATERAL (
     SELECT parent_resource_id FROM upload_sessions
     WHERE document_id=d.document_id ORDER BY created_at DESC LIMIT 1
   ) u ON true
 ), inherited_leaves AS (
   SELECT q.*,
     (SELECT jsonb_agg(to_jsonb(r) ORDER BY p.position)
       FROM unnest(q.current_path) WITH ORDINALITY p(member,position)
       LEFT JOIN resources r ON r.resource_id=p.member) members,
     EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=ANY(q.current_path)
       AND a.action=q.action AND a.principal_id IN(SELECT id FROM pm) AND a.effect='deny'
       AND a.valid_from<=transaction_timestamp()
       AND (a.expires_at IS NULL OR a.expires_at>transaction_timestamp())) deny_tx,
     EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=ANY(q.current_path)
       AND a.action=q.action AND a.principal_id IN(SELECT id FROM pm) AND a.effect='deny'
       AND a.valid_from<=statement_timestamp()
       AND (a.expires_at IS NULL OR a.expires_at>statement_timestamp())) deny_current,
     EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=ANY(q.current_path)
       AND a.action=q.action AND a.principal_id IN(SELECT id FROM pm) AND a.effect='allow'
       AND a.valid_from<=transaction_timestamp()
       AND (a.expires_at IS NULL OR a.expires_at>transaction_timestamp())) allow_tx,
     EXISTS(SELECT 1 FROM acl_entries a WHERE a.resource_id=ANY(q.current_path)
       AND a.action=q.action AND a.principal_id IN(SELECT id FROM pm) AND a.effect='allow'
       AND a.valid_from<=statement_timestamp()
       AND (a.expires_at IS NULL OR a.expires_at>statement_timestamp())) allow_current
   FROM paths q
 )
"""


def inherited_attributes(body: Any, principals: frozenset[uuid.UUID]) -> Effective:
    if (not body["path_present"] or body["lineage"] != body["current_path"]
            or not 1 <= len(body["current_path"]) <= 5):
        return None
    try:
        members = [ResourceRecord.model_validate(r) for r in body["members"]]
        path = [uuid.UUID(value) for value in body["current_path"]]
        if ([r.resource_id for r in members] != path
                or any(r.lifecycle_state in {"deleted", "quarantined"} for r in members)):
            return None
        leaf = members[0]
        ancestor = next((r for r in reversed(members) if r.resource_type == "source"), members[-1])
        rank = {"public_internal": 0, "internal": 1, "restricted": 2, "highly_restricted": 3}
        classification = max(members, key=lambda r: rank[r.classification]).classification
        private_without_allow = (
            ancestor.source_zone == "private_context"
            and ancestor.owner_subject_id not in principals
            and not (body["allow_tx"] and body["allow_current"])
        )
        attributes = ResourceAttributes(
            resource_id=str(leaf.resource_id),
            owner_id=str(ancestor.owner_subject_id) if ancestor.owner_subject_id else None,
            source_zone=ancestor.source_zone, lifecycle_state=leaf.lifecycle_state,
            classification=CLASSIFICATION_TO_POLICY[classification],
            department=str(leaf.department_id) if leaf.department_id else None,
            project=str(leaf.project_id) if leaf.project_id else None,
            explicit_deny=(body["old_deny"] or body["deny_tx"] or body["deny_current"]
                           or private_without_allow),
        )
        return attributes, path
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise ActionError("resource_unavailable", 403) from error


async def final_inherited_checkpoint(
    session: AsyncSession, actor_id: uuid.UUID, requests: Sequence[LeafRequest],
    discovered: dict[tuple[uuid.UUID, str], Effective],
) -> LeafCheckpoint:
    requested = bounded_leaf_requests(requests)
    if any(key not in requested or (value is not None and not 1 <= len(value[1]) <= 5)
           for key, value in discovered.items()):
        raise ActionError("resource_unavailable", 403)
    bindings = [{"resource_id": str(key[0]), "action": key[1],
                 "lineage": [str(member) for member in value[1]],
                 "old_deny": value[0].explicit_deny}
                for key, value in discovered.items() if value is not None]
    row = (await session.execute(text("WITH " + MEMBERSHIPS + """
        , requested AS (SELECT * FROM jsonb_to_recordset(CAST(:requests AS jsonb))
            AS q(resource_id uuid,action text)), leaves AS (
        SELECT q.resource_id,q.action,to_jsonb(r) resource,
    """ + LEAF_ACL + """
        FROM requested q LEFT JOIN resources r ON r.resource_id=q.resource_id)
    """ + INHERITED + """
        SELECT (SELECT to_jsonb(i) FROM identity i) identity,
          ARRAY(SELECT id FROM pm) principal_ids,
          COALESCE((SELECT jsonb_agg(to_jsonb(l)) FROM leaves l),'[]'::jsonb) leaves,
          COALESCE((SELECT jsonb_agg(to_jsonb(l)) FROM inherited_leaves l),
                   '[]'::jsonb) inherited
    """), {"actor": actor_id, "uuid_pattern": UUID_PATTERN,
            "requests": json.dumps([{"resource_id": str(r.resource_id), "action": r.action}
                                    for r in requested.values()]),
            "inherited": json.dumps(bindings)})).mappings().one()
    frame = parse_leaf_checkpoint(row, requested)
    attributes = dict(frame.attributes)
    for key, value in discovered.items():
        if value is None:
            attributes[key] = None  # Earlier absence cannot become a grant here.
    for body in row["inherited"]:
        key = (uuid.UUID(body["resource_id"]), body["action"])
        attributes[key] = inherited_attributes(body, frame.principal_ids)
    return LeafCheckpoint(frame.subject, frame.principal_ids, attributes, frame.unsupported)
