import hashlib
import json
import secrets
import uuid
from typing import Any, Protocol

from rtr_copilot.auth.models import Role, Subject, SubjectStatus


class SubjectRepository(Protocol):
    async def upsert_from_claims(
        self,
        claims: dict[str, Any],
        mapping: dict[str, Any],
    ) -> Subject: ...


class RedisSubjectRepository:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def upsert_from_claims(
        self,
        claims: dict[str, Any],
        mapping: dict[str, Any],
    ) -> Subject:
        issuer = str(claims["iss"])
        sub = str(claims["sub"])
        identity_hash = hashlib.sha256(f"{issuer}\0{sub}".encode()).hexdigest()
        identity_key = f"rtr:identity:{identity_hash}"
        existing_raw = await self.client.get(identity_key)
        existing = Subject.model_validate_json(existing_raw) if existing_raw else None
        email = str(claims["email"]).lower()
        groups = {str(group) for group in claims.get("groups", [])}
        roles = {Role.STAFF}
        departments: set[str] = set()
        projects: set[str] = set()
        for group in groups:
            rule = mapping.get(group, {})
            roles.update(Role(role) for role in rule.get("roles", []))
            departments.update(str(value) for value in rule.get("departments", []))
            projects.update(str(value) for value in rule.get("projects", []))
        security_changed = existing is not None and any((
            existing.roles != roles,
            existing.groups != groups,
            existing.departments != departments,
            existing.projects != projects,
        ))
        security_version = existing.security_version if existing else 1
        version_key = (
            f"rtr:subject-security-version:{existing.user_id}"
            if existing
            else None
        )
        if security_changed and version_key is not None:
            security_version = int(await self.client.incr(version_key))
        subject = Subject(
            user_id=existing.user_id if existing else str(uuid.uuid4()),
            issuer=issuer,
            sub=sub,
            email=email,
            canonical_domain=email.rsplit("@", 1)[1],
            display_name=str(claims.get("name", "")),
            status=existing.status if existing else SubjectStatus.ACTIVE,
            security_version=security_version,
            roles=roles,
            groups=groups,
            departments=departments,
            projects=projects,
            temporary_entitlements=existing.temporary_entitlements if existing else [],
        )
        if existing is None:
            created = await self.client.set(
                identity_key,
                subject.model_dump_json(),
                nx=True,
            )
            if not created:
                winner = await self.client.get(identity_key)
                if winner:
                    subject = Subject.model_validate_json(winner)
            await self.client.set(
                f"rtr:subject-security-version:{subject.user_id}",
                subject.security_version,
                nx=True,
            )
        serialized = subject.model_dump_json()
        await self.client.set(identity_key, serialized)
        await self.client.set(f"rtr:subject:{subject.user_id}", serialized)
        return subject

    async def replace_authority(self, subject: Subject) -> Subject:
        """Persist a security-relevant change and invalidate all prior sessions."""
        subject.security_version = int(await self.client.incr(
            f"rtr:subject-security-version:{subject.user_id}",
        ))
        serialized = subject.model_dump_json()
        await self.client.set(f"rtr:subject:{subject.user_id}", serialized)
        identity_hash = hashlib.sha256(
            f"{subject.issuer}\0{subject.sub}".encode(),
        ).hexdigest()
        await self.client.set(f"rtr:identity:{identity_hash}", serialized)
        return subject


class SessionStore:
    def __init__(self, client: Any, ttl_seconds: int) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds

    async def create(self, subject: Subject) -> str:
        session_id = secrets.token_urlsafe(32)
        await self.client.set(
            f"rtr:subject-security-version:{subject.user_id}",
            subject.security_version,
            nx=True,
        )
        await self.client.set(
            f"rtr:subject:{subject.user_id}",
            subject.model_dump_json(),
            nx=True,
        )
        payload = json.dumps({
            "user_id": subject.user_id,
            "security_version": subject.security_version,
        })
        await self.client.set(
            f"rtr:session:{session_id}",
            payload,
            ex=self.ttl_seconds,
        )
        return session_id

    async def sync_authority(self, subject: Subject) -> None:
        """Project canonical PostgreSQL authority into the Redis session boundary."""
        await self.client.set(
            f"rtr:subject-security-version:{subject.user_id}",
            subject.security_version,
        )
        await self.client.set(
            f"rtr:subject:{subject.user_id}",
            subject.model_dump_json(),
        )

    async def get(self, session_id: str | None) -> Subject | None:
        if not session_id:
            return None
        session_key = f"rtr:session:{session_id}"
        raw = await self.client.get(session_key)
        if not raw:
            return None
        try:
            envelope = json.loads(raw)
            user_id = str(envelope["user_id"])
            session_version = int(envelope["security_version"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await self.client.delete(session_key)
            return None
        subject_raw = await self.client.get(f"rtr:subject:{user_id}")
        version_raw = await self.client.get(f"rtr:subject-security-version:{user_id}")
        if not subject_raw or version_raw is None:
            await self.client.delete(session_key)
            return None
        subject = Subject.model_validate_json(subject_raw)
        if (
            session_version != int(version_raw)
            or subject.security_version != int(version_raw)
            or subject.status != SubjectStatus.ACTIVE
        ):
            await self.client.delete(session_key)
            return None
        return subject

    async def revoke(self, session_id: str | None) -> None:
        if session_id:
            await self.client.delete(f"rtr:session:{session_id}")

    async def rotate(self, session_id: str | None, subject: Subject) -> str:
        await self.revoke(session_id)
        return await self.create(subject)

    async def revoke_all(self, user_id: str) -> int:
        """Invalidate every session for a subject without enumerating session IDs."""
        version = int(
            await self.client.incr(f"rtr:subject-security-version:{user_id}"),
        )
        raw = await self.client.get(f"rtr:subject:{user_id}")
        if raw:
            subject = Subject.model_validate_json(raw)
            subject.security_version = version
            serialized = subject.model_dump_json()
            await self.client.set(f"rtr:subject:{user_id}", serialized)
            identity_hash = hashlib.sha256(
                f"{subject.issuer}\0{subject.sub}".encode(),
            ).hexdigest()
            await self.client.set(f"rtr:identity:{identity_hash}", serialized)
        return version


class TransactionStore:
    def __init__(self, client: Any, ttl_seconds: int = 300) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        await self.client.set(
            f"rtr:oidc:{namespace}:{key}",
            json.dumps(value),
            ex=self.ttl_seconds,
            nx=True,
        )

    async def consume(self, namespace: str, key: str) -> dict[str, Any] | None:
        raw = await self.client.getdel(f"rtr:oidc:{namespace}:{key}")
        return json.loads(raw) if raw else None
