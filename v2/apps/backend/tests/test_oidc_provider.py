import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from rtr_copilot.auth.oidc import OIDCError, ProductionOIDCProvider
from rtr_copilot.config import Settings

ISSUER = "https://identity.example"
CLIENT_ID = "rtr-copilot"
KEY_ID = "test-key"


def settings() -> Settings:
    return Settings(
        postgres_dsn="postgresql://user:password@localhost/db",
        redis_url="redis://localhost/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="local",
        s3_secret_key="local-secret",
        s3_bucket="rtr-test",
        app_env="test",
        public_base_url="http://localhost:3000",
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret="test-client-secret",
        oidc_allowed_domains="rtrobotics.com",
    )


def metadata() -> dict[str, str]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
    }


def key_pair() -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})
    return private_key, public_jwk


def claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "subject-1",
        "aud": CLIENT_ID,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": "expected-nonce",
        "email": "person@rtrobotics.com",
        "email_verified": True,
    }
    values.update(overrides)
    return values


def oidc_transport(
    id_token: str,
    jwk: dict[str, Any],
    observed: dict[str, Any] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=metadata())
        if request.url.path == "/token":
            if observed is not None:
                observed["token_body"] = parse_qs(request.content.decode())
            return httpx.Response(200, json={"id_token": id_token})
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_discovery_and_authorization_url_include_oidc_and_pkce() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=metadata()),
    )
    provider = ProductionOIDCProvider(settings(), transport)
    discovered = await provider.discovery()
    url = await provider.authorization_url(
        state="state-value",
        nonce="nonce-value",
        code_challenge="challenge-value",
    )
    query = parse_qs(urlparse(url).query)
    assert discovered["jwks_uri"] == f"{ISSUER}/jwks"
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-value"]
    assert query["nonce"] == ["nonce-value"]
    assert query["code_challenge"] == ["challenge-value"]
    assert query["code_challenge_method"] == ["S256"]


@pytest.mark.asyncio
async def test_exchange_verifies_rs256_jwks_and_sends_code_verifier() -> None:
    private_key, jwk = key_pair()
    token = jwt.encode(claims(), private_key, algorithm="RS256", headers={"kid": KEY_ID})
    observed: dict[str, Any] = {}
    provider = ProductionOIDCProvider(
        settings(),
        oidc_transport(token, jwk, observed),
    )
    verified = await provider.exchange(
        code="authorization-code",
        code_verifier="pkce-verifier",
        expected_nonce="expected-nonce",
    )
    assert verified["sub"] == "subject-1"
    assert observed["token_body"]["code"] == ["authorization-code"]
    assert observed["token_body"]["code_verifier"] == ["pkce-verifier"]


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("bad_signature", "provider_exchange_failed"),
        ("bad_audience", "provider_exchange_failed"),
        ("bad_issuer", "provider_exchange_failed"),
        ("expired", "provider_exchange_failed"),
        ("bad_nonce", "nonce_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_exchange_rejects_invalid_token_claims(
    mutation: str,
    expected_error: str,
) -> None:
    trusted_key, jwk = key_pair()
    signing_key = trusted_key
    values: dict[str, Any] = {}
    if mutation == "bad_signature":
        signing_key, _ = key_pair()
    elif mutation == "bad_audience":
        values["aud"] = "wrong-client"
    elif mutation == "bad_issuer":
        values["iss"] = "https://attacker.invalid"
    elif mutation == "expired":
        values["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    elif mutation == "bad_nonce":
        values["nonce"] = "wrong-nonce"
    token = jwt.encode(
        claims(**values),
        signing_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )
    provider = ProductionOIDCProvider(settings(), oidc_transport(token, jwk))
    with pytest.raises(OIDCError, match=expected_error):
        await provider.exchange(
            code="authorization-code",
            code_verifier="pkce-verifier",
            expected_nonce="expected-nonce",
        )


@pytest.mark.asyncio
async def test_provider_timeout_is_fail_closed() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    provider = ProductionOIDCProvider(settings(), httpx.MockTransport(timeout))
    with pytest.raises(OIDCError, match="provider_unavailable"):
        await provider.discovery()


@pytest.mark.asyncio
async def test_provider_http_error_is_fail_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=metadata())
        return httpx.Response(503)

    provider = ProductionOIDCProvider(settings(), httpx.MockTransport(handler))
    with pytest.raises(OIDCError, match="provider_exchange_failed"):
        await provider.exchange(
            code="authorization-code",
            code_verifier="pkce-verifier",
            expected_nonce="expected-nonce",
        )
