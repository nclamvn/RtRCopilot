from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.auth.models import Role, Subject, SubjectStatus, TemporaryEntitlement
from rtr_copilot.db.engine import session_factory
from rtr_copilot.db.uow import ensure_mutation_allowed
from rtr_copilot.repositories.audit import AuditRepository


class PostgresSubjectRepository:
    """TIP-003 SubjectRepository backed by immutable PostgreSQL identity."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        request_id: str = "identity-sync",
    ) -> None:
        self.factory = factory or session_factory()
        self.request_id = request_id

    async def upsert_from_claims(
        self,
        claims: dict[str, Any],
        mapping: dict[str, Any],
    ) -> Subject:
        async with self.factory() as session, session.begin():
            await ensure_mutation_allowed(session)
            issuer = str(claims["iss"])
            provider_sub = str(claims["sub"])
            email = str(claims["email"]).lower()
            row = (await session.execute(text("""
                INSERT INTO subjects
                  (issuer, provider_sub, email, canonical_domain, display_name)
                VALUES
                  (:issuer, :provider_sub, :email, :domain, :display_name)
                ON CONFLICT (issuer, provider_sub) DO UPDATE SET
                  email = EXCLUDED.email,
                  canonical_domain = EXCLUDED.canonical_domain,
                  display_name = EXCLUDED.display_name,
                  updated_at = now(),
                  last_seen_at = now()
                RETURNING user_id, status, security_version, (xmax = 0) AS inserted
            """), {
                "issuer": issuer,
                "provider_sub": provider_sub,
                "email": email,
                "domain": email.rsplit("@", 1)[1],
                "display_name": str(claims.get("name", "")),
            })).mappings().one()
            user_id = row["user_id"]
            old_groups = set((await session.execute(text("""
                SELECT g.provider_group_key
                FROM subject_groups sg JOIN groups g ON g.group_id = sg.group_id
                WHERE sg.subject_id = :user_id
                  AND (sg.expires_at IS NULL OR sg.expires_at > now())
            """), {"user_id": user_id})).scalars())
            old_roles = set((await session.execute(text("""
                SELECT r.key
                FROM subject_roles sr JOIN roles r ON r.role_id = sr.role_id
                WHERE sr.subject_id = :user_id
                  AND (sr.expires_at IS NULL OR sr.expires_at > now())
            """), {"user_id": user_id})).scalars())

            groups = {str(value) for value in claims.get("groups", [])}
            roles = {Role.STAFF}
            departments: set[str] = set()
            projects: set[str] = set()
            for group_key in groups:
                rule = mapping.get(group_key, {})
                roles.update(Role(value) for value in rule.get("roles", []))
                departments.update(str(value) for value in rule.get("departments", []))
                projects.update(str(value) for value in rule.get("projects", []))
                await session.execute(text("""
                    INSERT INTO groups (issuer, provider_group_key, name)
                    VALUES (:issuer, :group_key, :group_key)
                    ON CONFLICT (issuer, provider_group_key)
                    DO UPDATE SET name = EXCLUDED.name, updated_at = now()
                """), {"issuer": issuer, "group_key": group_key})
            await session.execute(
                text("DELETE FROM subject_groups WHERE subject_id = :user_id"),
                {"user_id": user_id},
            )
            if groups:
                await session.execute(text("""
                    INSERT INTO subject_groups(subject_id, group_id)
                    SELECT :user_id, group_id FROM groups
                    WHERE issuer = :issuer
                      AND provider_group_key = ANY(:group_keys)
                """), {
                    "user_id": user_id,
                    "issuer": issuer,
                    "group_keys": sorted(groups),
                })
            await session.execute(
                text("DELETE FROM subject_roles WHERE subject_id = :user_id"),
                {"user_id": user_id},
            )
            await session.execute(text("""
                INSERT INTO subject_roles(subject_id, role_id)
                SELECT :user_id, role_id FROM roles WHERE key = ANY(:role_keys)
            """), {
                "user_id": user_id,
                "role_keys": sorted(role.value for role in roles),
            })
            await session.execute(
                text("DELETE FROM subject_scopes WHERE subject_id = :user_id"),
                {"user_id": user_id},
            )
            for scope_type, scope_values in (
                ("department", departments),
                ("project", projects),
            ):
                if scope_values:
                    await session.execute(text("""
                        INSERT INTO subject_scopes(subject_id, scope_type, scope_key)
                        SELECT :user_id, :scope_type,
                               unnest(CAST(:scope_keys AS text[]))
                    """), {
                        "user_id": user_id,
                        "scope_type": scope_type,
                        "scope_keys": sorted(scope_values),
                    })
            if (
                not bool(row["inserted"])
                and (
                    old_groups != groups
                    or old_roles != {role.value for role in roles}
                )
            ):
                row = (await session.execute(text("""
                    UPDATE subjects SET security_version = security_version + 1,
                      updated_at = now()
                    WHERE user_id = :user_id
                    RETURNING user_id, status, security_version
                """), {"user_id": user_id})).mappings().one()
            entitlements = await self._entitlements(session, user_id)
            subject = Subject(
                user_id=str(row["user_id"]),
                issuer=issuer,
                sub=provider_sub,
                email=email,
                canonical_domain=email.rsplit("@", 1)[1],
                display_name=str(claims.get("name", "")),
                status=SubjectStatus(str(row["status"])),
                security_version=int(row["security_version"]),
                roles=roles,
                groups=groups,
                departments=departments,
                projects=projects,
                temporary_entitlements=entitlements,
            )
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=user_id,
                action="identity.authority.sync",
                result="success",
                reason_code="server_mapping_applied",
                request_id=self.request_id,
                details={
                    "roles": sorted(role.value for role in roles),
                    "group_count": len(groups),
                    "department_count": len(departments),
                    "project_count": len(projects),
                },
            )
            return subject

    async def _entitlements(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> list[TemporaryEntitlement]:
        rows = (await session.execute(text("""
            SELECT action, resource_id, conditions, expires_at
            FROM entitlements
            WHERE subject_id = :user_id AND active AND effect = 'allow'
              AND expires_at IS NOT NULL AND expires_at > now()
        """), {"user_id": user_id})).mappings()
        return [
            TemporaryEntitlement(
                action=str(row["action"]),
                resource_id=str(row["resource_id"]) if row["resource_id"] else None,
                classification=dict(row["conditions"]).get("classification"),
                expires_at=row["expires_at"],
            )
            for row in rows
        ]

    async def get_by_identity(self, issuer: str, sub: str) -> Subject | None:
        async with self.factory() as session:
            row = (await session.execute(text("""
                SELECT user_id, issuer, provider_sub, email, canonical_domain,
                       display_name, status, security_version
                FROM subjects WHERE issuer = :issuer AND provider_sub = :sub
            """), {"issuer": issuer, "sub": sub})).mappings().one_or_none()
            if row is None:
                return None
            roles = {
                Role(value)
                for value in (await session.execute(text("""
                    SELECT r.key FROM subject_roles sr
                    JOIN roles r ON r.role_id = sr.role_id
                    WHERE sr.subject_id = :user_id
                      AND sr.valid_from <= now()
                      AND (sr.expires_at IS NULL OR sr.expires_at > now())
                """), {"user_id": row["user_id"]})).scalars()
            }
            groups = set((await session.execute(text("""
                SELECT g.provider_group_key FROM subject_groups sg
                JOIN groups g ON g.group_id = sg.group_id
                WHERE sg.subject_id = :user_id
                  AND sg.valid_from <= now()
                  AND (sg.expires_at IS NULL OR sg.expires_at > now())
            """), {"user_id": row["user_id"]})).scalars())
            scopes = (await session.execute(text("""
                SELECT scope_type, scope_key FROM subject_scopes
                WHERE subject_id = :user_id AND valid_from <= now()
                  AND (expires_at IS NULL OR expires_at > now())
            """), {"user_id": row["user_id"]})).all()
            return Subject(
                user_id=str(row["user_id"]),
                issuer=str(row["issuer"]),
                sub=str(row["provider_sub"]),
                email=str(row["email"] or ""),
                canonical_domain=str(row["canonical_domain"] or ""),
                display_name=str(row["display_name"]),
                status=SubjectStatus(str(row["status"])),
                security_version=int(row["security_version"]),
                roles=roles or {Role.STAFF},
                groups=groups,
                departments={item[1] for item in scopes if item[0] == "department"},
                projects={item[1] for item in scopes if item[0] == "project"},
                temporary_entitlements=await self._entitlements(session, row["user_id"]),
            )

    async def get_by_user_id(self, user_id: UUID) -> Subject | None:
        async with self.factory() as session:
            identity = (await session.execute(text("""
                SELECT issuer,provider_sub FROM subjects WHERE user_id=:user_id
            """), {"user_id": user_id})).one_or_none()
        if identity is None:
            return None
        return await self.get_by_identity(str(identity[0]), str(identity[1]))

    async def replace_authority(self, subject: Subject) -> Subject:
        return await self.mutate_authority(
            subject,
            request_id=self.request_id,
            actor_id=UUID(subject.user_id),
        )

    async def mutate_authority(
        self,
        subject: Subject,
        *,
        request_id: str,
        actor_id: UUID,
        inject_failure: bool = False,
    ) -> Subject:
        async with self.factory() as session, session.begin():
            await ensure_mutation_allowed(session)
            row = (await session.execute(text("""
                UPDATE subjects SET status = :status,
                  security_version = security_version + 1, updated_at = now()
                WHERE user_id = :user_id
                RETURNING security_version
            """), {
                "status": subject.status.value,
                "user_id": UUID(subject.user_id),
            })).one()
            subject.security_version = int(row[0])
            await session.execute(
                text("DELETE FROM subject_roles WHERE subject_id = :user_id"),
                {"user_id": UUID(subject.user_id)},
            )
            await session.execute(text("""
                INSERT INTO subject_roles(subject_id, role_id)
                SELECT :user_id, role_id FROM roles WHERE key = ANY(:roles)
            """), {
                "user_id": UUID(subject.user_id),
                "roles": sorted(role.value for role in subject.roles),
            })
            await session.execute(
                text("DELETE FROM subject_groups WHERE subject_id = :user_id"),
                {"user_id": UUID(subject.user_id)},
            )
            for group_key in subject.groups:
                await session.execute(text("""
                    INSERT INTO groups(issuer, provider_group_key, name)
                    VALUES (:issuer, :group_key, :group_key)
                    ON CONFLICT (issuer, provider_group_key) DO NOTHING
                """), {"issuer": subject.issuer, "group_key": group_key})
            if subject.groups:
                await session.execute(text("""
                    INSERT INTO subject_groups(subject_id, group_id)
                    SELECT :user_id, group_id FROM groups
                    WHERE issuer=:issuer AND provider_group_key=ANY(:groups)
                """), {
                    "user_id": UUID(subject.user_id),
                    "issuer": subject.issuer,
                    "groups": sorted(subject.groups),
                })
            await session.execute(
                text("DELETE FROM subject_scopes WHERE subject_id = :user_id"),
                {"user_id": UUID(subject.user_id)},
            )
            for scope_type, values in (
                ("department", subject.departments),
                ("project", subject.projects),
            ):
                if values:
                    await session.execute(text("""
                        INSERT INTO subject_scopes(subject_id, scope_type, scope_key)
                        SELECT :user_id, :scope_type,
                               unnest(CAST(:scope_keys AS text[]))
                    """), {
                        "user_id": UUID(subject.user_id),
                        "scope_type": scope_type,
                        "scope_keys": sorted(values),
                    })
            await session.execute(
                text("DELETE FROM entitlements WHERE subject_id = :user_id"),
                {"user_id": UUID(subject.user_id)},
            )
            for entitlement in subject.temporary_entitlements:
                resource_id: UUID | None = None
                if entitlement.resource_id:
                    try:
                        resource_id = UUID(entitlement.resource_id)
                    except ValueError:
                        resource_id = None
                await session.execute(text("""
                    INSERT INTO entitlements(
                      subject_id, resource_id, action, effect, conditions,
                      expires_at, granted_by, reason
                    ) VALUES (
                      :subject_id, :resource_id, :action, 'allow',
                      CAST(:conditions AS jsonb), :expires_at, :granted_by,
                      'authority_sync'
                    )
                """), {
                    "subject_id": UUID(subject.user_id),
                    "resource_id": resource_id,
                    "action": entitlement.action,
                    "conditions": __import__("json").dumps({
                        "classification": entitlement.classification,
                    }),
                    "expires_at": entitlement.expires_at,
                    "granted_by": actor_id,
                })
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor_id,
                action="identity.authority.mutate",
                result="success",
                reason_code="authority_updated",
                request_id=request_id,
                details={
                    "subject_id": subject.user_id,
                    "roles": sorted(role.value for role in subject.roles),
                    "groups": sorted(subject.groups),
                    "departments": sorted(subject.departments),
                    "projects": sorted(subject.projects),
                    "entitlement_count": len(subject.temporary_entitlements),
                    "status": subject.status.value,
                },
            )
            if inject_failure:
                raise RuntimeError("injected_authority_failure")
        return subject
