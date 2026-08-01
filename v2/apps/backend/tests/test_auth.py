from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from rtr_copilot.api.main import app
from rtr_copilot.auth import api as auth_api
from rtr_copilot.auth.audit import AuditEvent
from rtr_copilot.auth.models import Role, Subject, SubjectStatus, TemporaryEntitlement
from rtr_copilot.auth.oidc import (
    OIDCError,
    decode_dev_code,
    encode_dev_code,
    pkce_challenge,
    validate_claims,
)
from rtr_copilot.auth.storage import RedisSubjectRepository, SessionStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = str(value)
        if ex is not None:
            self.expiry[key] = ex
        return True

    async def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.expiry.pop(key, None)
        return int(existed)

    async def getdel(self, key: str) -> str | None:
        value = self.values.get(key)
        await self.delete(key)
        return value

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    async def aclose(self) -> None:
        return None


class MemoryAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def claims(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "iss": "https://issuer.example",
        "sub": "subject-1",
        "email": "person@rtrobotics.com",
        "email_verified": True,
        "nonce": "nonce-1",
        "name": "Same Name",
        "groups": [],
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("override", "nonce", "reason"),
    [
        ({"nonce": "wrong"}, "nonce-1", "nonce_mismatch"),
        ({"email_verified": False}, "nonce-1", "email_unverified"),
        ({"email": "person@example.com"}, "nonce-1", "domain_denied"),
        ({"email": "missing-at"}, "nonce-1", "domain_denied"),
        ({"iss": ""}, "nonce-1", "subject_missing"),
        ({"sub": ""}, "nonce-1", "subject_missing"),
    ],
)
def test_oidc_claim_rejections(
    override: dict[str, Any],
    nonce: str,
    reason: str,
) -> None:
    with pytest.raises(OIDCError, match=reason):
        validate_claims(
            claims(**override),
            nonce,
            frozenset({"rtrobotics.com", "rtrobotics.me"}),
        )


def test_oidc_valid_claims() -> None:
    assert validate_claims(
        claims(),
        "nonce-1",
        frozenset({"rtrobotics.com"}),
    )["sub"] == "subject-1"


def test_pkce_is_deterministic_and_not_plaintext() -> None:
    challenge = pkce_challenge("verifier")
    assert challenge == pkce_challenge("verifier")
    assert challenge != "verifier"


@pytest.mark.asyncio
async def test_identity_is_immutable_and_mapping_is_server_side() -> None:
    redis = FakeRedis()
    repository = RedisSubjectRepository(redis)
    mapping = {
        "leaders": {
            "roles": ["leader"],
            "departments": ["engineering"],
            "projects": ["atlas"],
        },
    }
    first = await repository.upsert_from_claims(
        claims(groups=["leaders"], roles=["admin"]),
        mapping,
    )
    second = await repository.upsert_from_claims(
        claims(email="renamed@rtrobotics.me", groups=[]),
        mapping,
    )
    other = await repository.upsert_from_claims(
        claims(sub="subject-2", email="other@rtrobotics.com"),
        mapping,
    )
    assert first.user_id == second.user_id
    assert first.user_id != other.user_id
    assert first.display_name == other.display_name
    assert first.roles == {Role.STAFF, Role.LEADER}
    assert Role.ADMIN not in first.roles
    assert first.departments == {"engineering"}
    assert first.projects == {"atlas"}
    assert second.roles == {Role.STAFF}


@pytest.mark.asyncio
async def test_session_ttl_rotation_revoke_and_no_tokens() -> None:
    redis = FakeRedis()
    store = SessionStore(redis, ttl_seconds=900)
    subject = Subject(
        user_id="user-1",
        issuer="issuer",
        sub="sub",
        email="user@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        temporary_entitlements=[TemporaryEntitlement(
            action="view",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )],
    )
    original = await store.create(subject)
    assert redis.expiry[f"rtr:session:{original}"] == 900
    assert "access_token" not in redis.values[f"rtr:session:{original}"]
    rotated = await store.rotate(original, subject)
    assert rotated != original
    assert await store.get(original) is None
    assert (await store.get(rotated)).user_id == "user-1"  # type: ignore[union-attr]
    await store.revoke(rotated)
    assert await store.get(rotated) is None


@pytest.mark.asyncio
async def test_role_change_invalidates_every_concurrent_session() -> None:
    redis = FakeRedis()
    repository = RedisSubjectRepository(redis)
    store = SessionStore(redis, ttl_seconds=900)
    current = await repository.upsert_from_claims(claims(), {})
    first = await store.create(current)
    second = await store.create(current)

    current.roles = {Role.STAFF, Role.LEADER}
    updated = await repository.replace_authority(current)

    assert updated.security_version == 2
    assert await store.get(first) is None
    assert await store.get(second) is None
    replacement = await store.create(updated)
    assert (await store.get(replacement)).roles == {Role.STAFF, Role.LEADER}  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_oidc_group_role_remap_invalidates_existing_sessions() -> None:
    redis = FakeRedis()
    repository = RedisSubjectRepository(redis)
    store = SessionStore(redis, ttl_seconds=900)
    current = await repository.upsert_from_claims(claims(groups=[]), {})
    old_session = await store.create(current)

    updated = await repository.upsert_from_claims(
        claims(groups=["leaders"]),
        {"leaders": {"roles": ["leader"], "departments": ["engineering"]}},
    )

    assert updated.security_version == 2
    assert updated.roles == {Role.STAFF, Role.LEADER}
    assert await store.get(old_session) is None


@pytest.mark.asyncio
async def test_revoke_all_and_status_change_kill_every_session() -> None:
    redis = FakeRedis()
    repository = RedisSubjectRepository(redis)
    store = SessionStore(redis, ttl_seconds=900)
    current = await repository.upsert_from_claims(claims(), {})
    sessions = [await store.create(current), await store.create(current)]

    assert await store.revoke_all(current.user_id) == 2
    assert all([await store.get(session_id) is None for session_id in sessions])

    current.security_version = 2
    active_session = await store.create(current)
    current.status = SubjectStatus.DISABLED
    await repository.replace_authority(current)
    assert await store.get(active_session) is None


def test_fake_flow_cookie_replay_and_protected_deny(monkeypatch: MonkeyPatch) -> None:
    redis = FakeRedis()
    audit = MemoryAudit()
    monkeypatch.setattr(auth_api.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(auth_api, "audit", audit)
    monkeypatch.setattr(
        auth_api,
        "identity_repository",
        lambda _request_id: RedisSubjectRepository(redis),
    )
    with TestClient(app, follow_redirects=False) as client:
        login = client.get("/auth/login", headers={"X-Request-ID": "login-id"})
        assert login.status_code == 302
        authorize_path = login.headers["location"].replace("/api/auth/", "/auth/")
        authorize = client.get(authorize_path)
        callback_url = urlparse(authorize.headers["location"])
        callback_path = callback_url.path.replace("/api/auth/", "/auth/")
        callback = client.get(f"{callback_path}?{callback_url.query}")
        assert callback.status_code == 302
        cookie = callback.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Secure" not in cookie
        replay = client.get(f"{callback_path}?{callback_url.query}")
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "oidc_rejected"

        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["roles"] == ["staff"]
        denied = client.get("/auth/dev/protected")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "classification_denied"
        logout = client.post("/auth/logout")
        assert logout.status_code == 200
        assert client.get("/auth/me").status_code == 401
    assert [item.action for item in audit.events] == [
        "auth.login",
        "auth.login",
        "policy.view",
        "auth.session_revoke",
        "auth.logout",
    ]
    serialized = "".join(item.model_dump_json() for item in audit.events)
    for forbidden in ["token", "cookie", "secret", "raw"]:
        assert forbidden not in serialized.lower()


def test_auth_error_openapi_and_runtime_match(monkeypatch: MonkeyPatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(auth_api.Redis, "from_url", lambda *_args, **_kwargs: redis)
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()
        me_responses = document["paths"]["/auth/me"]["get"]["responses"]
        protected_responses = document["paths"]["/auth/dev/protected"]["get"]["responses"]
        assert me_responses["401"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/ErrorResponse",
        )
        assert protected_responses["401"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/ErrorResponse",
        )
        assert protected_responses["403"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/ErrorResponse",
        )
        for path in ("/auth/me", "/auth/dev/protected"):
            response = client.get(path, headers={"X-Request-ID": "typed-error"})
            assert response.status_code == 401
            assert response.json() == {
                "error": {
                    "code": "authentication_required",
                    "message": "Sign in required",
                },
                "request_id": "typed-error",
            }


def test_fake_flow_rejects_pkce_failure(monkeypatch: MonkeyPatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(auth_api.Redis, "from_url", lambda *_args, **_kwargs: redis)
    with TestClient(app, follow_redirects=False) as client:
        login = client.get("/auth/login")
        authorize_path = login.headers["location"].replace("/api/auth/", "/auth/")
        authorize = client.get(authorize_path)
        callback_url = urlparse(authorize.headers["location"])
        parameters = parse_qs(callback_url.query)
        payload = decode_dev_code(parameters["code"][0])
        payload["code_challenge"] = "tampered"
        callback_path = callback_url.path.replace("/api/auth/", "/auth/")
        rejected = client.get(
            callback_path,
            params={"state": parameters["state"][0], "code": encode_dev_code(payload)},
        )
        assert rejected.status_code == 401
        assert rejected.json()["error"]["code"] == "oidc_rejected"


def test_session_cookie_is_secure_behind_https_ingress(monkeypatch: MonkeyPatch) -> None:
    """TIP-012 Task 1: served through the TLS ingress the session cookie
    must carry Secure + HttpOnly + SameSite (derived from PUBLIC_BASE_URL)."""
    from rtr_copilot.config import get_settings

    redis = FakeRedis()
    monkeypatch.setattr(auth_api.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(auth_api, "audit", MemoryAudit())
    monkeypatch.setattr(
        auth_api,
        "identity_repository",
        lambda _request_id: RedisSubjectRepository(redis),
    )
    base = get_settings()
    ingress_settings = type(base).model_validate({
        **base.model_dump(),
        "public_base_url": "https://rtr.local",
    })
    assert ingress_settings.session_cookie_secure_effective is True
    monkeypatch.setattr(auth_api, "get_settings", lambda: ingress_settings)
    with TestClient(app, follow_redirects=False) as client:
        login = client.get("/auth/login")
        assert login.status_code == 302
        authorize = client.get(login.headers["location"].replace("/api/auth/", "/auth/"))
        callback_url = urlparse(authorize.headers["location"])
        assert callback_url.scheme == "https"
        assert callback_url.hostname == "rtr.local"
        callback = client.get(
            f"{callback_url.path.replace('/api/auth/', '/auth/')}?{callback_url.query}",
        )
        assert callback.status_code == 302
        cookie = callback.headers["set-cookie"]
        assert "Secure" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
