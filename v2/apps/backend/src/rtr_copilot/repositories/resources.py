import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.auth.models import ResourceAttributes
from rtr_copilot.repositories.audit import AuditRepository

Classification = Literal[
    "public_internal",
    "internal",
    "restricted",
    "highly_restricted",
]
SourceZone = Literal["sot", "research", "private_context"]
Lifecycle = Literal["draft", "active", "superseded", "quarantined", "deleted"]


class ResourceRecord(BaseModel):
    resource_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    resource_type: Literal[
        "source",
        "document",
        "document_version",
        "object",
        "rendition",
        "record",
    ]
    owner_subject_id: uuid.UUID | None = None
    classification: Classification
    source_zone: SourceZone
    department_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    lifecycle_state: Lifecycle = "draft"
    retention_until: datetime | None = None
    legal_hold: bool = False


class ACLRecord(BaseModel):
    acl_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    resource_id: uuid.UUID
    principal_type: Literal["user", "group", "role", "department", "project"]
    principal_id: uuid.UUID
    action: str
    effect: Literal["allow", "deny"]
    conditions: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    granted_by: uuid.UUID | None = None
    reason: str | None = None


CLASSIFICATION_TO_POLICY = {
    "public_internal": "public",
    "internal": "internal",
    "restricted": "restricted",
    "highly_restricted": "classified",
}


class ResourceRepository:
    async def create(self, session: AsyncSession, record: ResourceRecord) -> ResourceRecord:
        await session.execute(text("""
            INSERT INTO resources (
              resource_id, resource_type, owner_subject_id, classification,
              source_zone, department_id, project_id, lifecycle_state,
              retention_until, legal_hold
            ) VALUES (
              :resource_id, :resource_type, :owner_subject_id, :classification,
              :source_zone, :department_id, :project_id, :lifecycle_state,
              :retention_until, :legal_hold
            )
        """), record.model_dump())
        return record

    async def get(self, session: AsyncSession, resource_id: uuid.UUID) -> ResourceRecord | None:
        row = (await session.execute(text("""
            SELECT resource_id, resource_type, owner_subject_id, classification,
              source_zone, department_id, project_id, lifecycle_state,
              retention_until, legal_hold
            FROM resources WHERE resource_id = :resource_id
        """), {"resource_id": resource_id})).mappings().one_or_none()
        return ResourceRecord(**row) if row else None

    async def policy_attributes(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        *,
        action: str,
        principal_ids: set[uuid.UUID],
    ) -> ResourceAttributes | None:
        resource = await self.get(session, resource_id)
        if resource is None or resource.lifecycle_state in {
            "deleted",
            "quarantined",
        }:
            return None
        deny = await session.scalar(text("""
            SELECT EXISTS(
              SELECT 1 FROM acl_entries
              WHERE resource_id = :resource_id AND action = :action
                AND principal_id = ANY(:principal_ids)
                AND effect = 'deny' AND valid_from <= now()
                AND (expires_at IS NULL OR expires_at > now())
            )
        """), {
            "resource_id": resource_id,
            "action": action,
            "principal_ids": list(principal_ids),
        })
        return ResourceAttributes(
            resource_id=str(resource.resource_id),
            owner_id=str(resource.owner_subject_id) if resource.owner_subject_id else None,
            classification=CLASSIFICATION_TO_POLICY[resource.classification],
            department=(
                str(resource.department_id) if resource.department_id else None
            ),
            project=str(resource.project_id) if resource.project_id else None,
            source_zone=resource.source_zone,
            lifecycle_state=resource.lifecycle_state,
            explicit_deny=bool(deny),
        )

    async def effective_policy_attributes(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        *,
        action: str,
        principal_ids: set[uuid.UUID],
    ) -> tuple[ResourceAttributes, list[uuid.UUID]] | None:
        """Resolve security lineage without changing the TIP-003 policy contract."""
        leaf = await self.get(session, resource_id)
        if leaf is None:
            return None
        lineage = [resource_id]
        document_id: uuid.UUID | None = None
        if leaf.resource_type == "rendition":
            version_id = await session.scalar(text("""
                SELECT version_id FROM renditions WHERE rendition_id=:resource_id
            """), {"resource_id": resource_id})
            if version_id is None:
                return None
            lineage.append(version_id)
            document_id = await session.scalar(text("""
                SELECT document_id FROM document_versions WHERE version_id=:version_id
            """), {"version_id": version_id})
        elif leaf.resource_type == "document_version":
            document_id = await session.scalar(text("""
                SELECT document_id FROM document_versions WHERE version_id=:resource_id
            """), {"resource_id": resource_id})
        elif leaf.resource_type == "object":
            version_id = await session.scalar(text("""
                SELECT version_id FROM document_versions WHERE object_id=:resource_id
                UNION ALL
                SELECT version_id FROM renditions WHERE object_id=:resource_id
                LIMIT 1
            """), {"resource_id": resource_id})
            if version_id is not None:
                lineage.append(version_id)
                document_id = await session.scalar(text("""
                    SELECT document_id FROM document_versions WHERE version_id=:version_id
                """), {"version_id": version_id})
        elif leaf.resource_type == "document":
            document_id = resource_id
        if document_id is not None:
            lineage.append(document_id)
            document_row = (await session.execute(text("""
                SELECT d.source_id,
                  (SELECT parent_resource_id FROM upload_sessions u
                   WHERE u.document_id=d.document_id
                   ORDER BY u.created_at DESC LIMIT 1) AS parent_resource_id
                FROM documents d WHERE d.document_id=:document_id
            """), {"document_id": document_id})).mappings().one_or_none()
            if document_row is None:
                return None
            if document_row["source_id"]:
                lineage.append(document_row["source_id"])
            if document_row["parent_resource_id"]:
                lineage.append(document_row["parent_resource_id"])
        lineage = list(dict.fromkeys(lineage))
        rows = (await session.execute(text("""
            SELECT resource_id,resource_type,owner_subject_id,classification,
              source_zone,lifecycle_state,department_id,project_id
            FROM resources WHERE resource_id=ANY(:lineage)
        """), {"lineage": lineage})).mappings().all()
        if len(rows) != len(lineage) or any(
            row["lifecycle_state"] in {"deleted", "quarantined"} for row in rows
        ):
            return None
        attributes = await self.policy_attributes(
            session,
            resource_id,
            action=action,
            principal_ids=principal_ids,
        )
        if attributes is None:
            return None
        classification_rank = {
            "public_internal": 0,
            "internal": 1,
            "restricted": 2,
            "highly_restricted": 3,
        }
        effective = max(rows, key=lambda row: classification_rank[row["classification"]])
        attributes.classification = CLASSIFICATION_TO_POLICY[effective["classification"]]
        rows_by_id = {row["resource_id"]: row for row in rows}
        security_ancestor = next(
            (
                rows_by_id[ancestor_id]
                for ancestor_id in reversed(lineage)
                if rows_by_id[ancestor_id]["resource_type"] == "source"
            ),
            rows_by_id[lineage[-1]],
        )
        attributes.source_zone = security_ancestor["source_zone"]
        attributes.owner_id = (
            str(security_ancestor["owner_subject_id"])
            if security_ancestor["owner_subject_id"]
            else None
        )
        acl_effects = (await session.execute(text("""
            SELECT effect, bool_or(true) AS active
            FROM acl_entries
            WHERE resource_id=ANY(:lineage) AND action=:action
              AND principal_id=ANY(:principal_ids)
              AND valid_from <= now()
              AND (expires_at IS NULL OR expires_at > now())
            GROUP BY effect
        """), {
            "lineage": lineage,
            "action": action,
            "principal_ids": list(principal_ids),
        })).mappings().all()
        active_effects = {str(row["effect"]) for row in acl_effects if row["active"]}
        inherited_deny = "deny" in active_effects
        private_owner = (
            attributes.owner_id is not None
            and uuid.UUID(attributes.owner_id) in principal_ids
        )
        private_without_allow = (
            attributes.source_zone == "private_context"
            and not private_owner
            and "allow" not in active_effects
        )
        # Keep the public TIP-003 policy input stable: an absent private-context
        # grant is represented as an effective deny before policy evaluation.
        attributes.explicit_deny = (
            attributes.explicit_deny
            or inherited_deny
            or private_without_allow
        )
        return attributes, lineage

    async def add_acl(
        self,
        session: AsyncSession,
        record: ACLRecord,
        *,
        request_id: str,
    ) -> ACLRecord:
        await session.execute(text("""
            INSERT INTO acl_entries (
              acl_id, resource_id, principal_type, principal_id, action, effect,
              conditions, valid_from, expires_at, granted_by, reason
            ) VALUES (
              :acl_id, :resource_id, :principal_type, :principal_id, :action,
              :effect, CAST(:conditions AS jsonb), :valid_from, :expires_at,
              :granted_by, :reason
            )
        """), {
            **record.model_dump(exclude={"conditions"}),
            "conditions": __import__("json").dumps(record.conditions),
        })
        await AuditRepository().append(
            session,
            actor_kind="user" if record.granted_by else "service",
            actor_user_id=record.granted_by,
            action="acl.create",
            result="success",
            reason_code="acl_granted",
            request_id=request_id,
            resource_id=record.resource_id,
            resource_type="acl",
            details={
                "principal_type": record.principal_type,
                "action": record.action,
                "effect": record.effect,
            },
        )
        return record

    async def active_acl(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
    ) -> list[ACLRecord]:
        rows = (await session.execute(text("""
            SELECT acl_id, resource_id, principal_type, principal_id, action,
              effect, conditions, valid_from, expires_at, granted_by, reason
            FROM acl_entries WHERE resource_id = :resource_id
              AND valid_from <= now()
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY created_at
        """), {"resource_id": resource_id})).mappings()
        return [ACLRecord(**row) for row in rows]

    async def soft_delete(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> None:
        await session.execute(text("""
            UPDATE resources SET lifecycle_state = 'deleted', deleted_at = now(),
              updated_at = now() WHERE resource_id = :resource_id
        """), {"resource_id": resource_id})
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=actor_id,
            action="resource.soft_delete",
            result="success",
            reason_code="soft_deleted",
            request_id=request_id,
            resource_id=resource_id,
        )

    async def assert_purge_allowed(
        self,
        session: AsyncSession,
        resource_id: uuid.UUID,
        *,
        retention_configured: bool,
    ) -> None:
        row = (await session.execute(text("""
            SELECT legal_hold, retention_until FROM resources
            WHERE resource_id = :resource_id
        """), {"resource_id": resource_id})).mappings().one()
        if row["legal_hold"]:
            raise PermissionError("legal_hold")
        if row["retention_until"] and row["retention_until"] > datetime.now(UTC):
            raise PermissionError("retention_active")
        if not retention_configured:
            raise PermissionError("retention_policy_unconfigured")
