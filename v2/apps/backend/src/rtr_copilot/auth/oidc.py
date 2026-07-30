import base64
import hashlib
import json
import secrets
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
import jwt

from rtr_copilot.config import Settings


class OIDCError(RuntimeError):
    pass


class OIDCProvider(Protocol):
    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str: ...

    async def exchange(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> dict[str, Any]: ...


def token_url(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def validate_claims(
    claims: dict[str, Any],
    expected_nonce: str,
    allowed_domains: frozenset[str],
) -> dict[str, Any]:
    if not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
        raise OIDCError("nonce_mismatch")
    if claims.get("email_verified") is not True:
        raise OIDCError("email_unverified")
    email = str(claims.get("email", "")).lower()
    if "@" not in email or email.rsplit("@", 1)[1] not in allowed_domains:
        raise OIDCError("domain_denied")
    if not claims.get("iss") or not claims.get("sub"):
        raise OIDCError("subject_missing")
    return claims


class ProductionOIDCProvider:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.timeout = httpx.Timeout(5.0)
        self.transport = transport

    def http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self.transport)

    async def discovery(self) -> dict[str, Any]:
        if self.settings.oidc_issuer is None:
            raise OIDCError("provider_not_configured")
        url = str(self.settings.oidc_issuer).rstrip("/") + "/.well-known/openid-configuration"
        try:
            async with self.http_client() as client:
                response = await client.get(url)
                response.raise_for_status()
                metadata = dict(response.json())
            if metadata.get("issuer", "").rstrip("/") != str(
                self.settings.oidc_issuer,
            ).rstrip("/"):
                raise OIDCError("provider_issuer_mismatch")
            for required in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not metadata.get(required):
                    raise OIDCError("provider_metadata_invalid")
            return metadata
        except OIDCError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise OIDCError("provider_unavailable") from None

    @property
    def redirect_uri(self) -> str:
        return str(self.settings.public_base_url).rstrip("/") + "/api/auth/callback"

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        metadata = await self.discovery()
        query = urlencode({
            "client_id": self.settings.oidc_client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": self.redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })
        return f"{metadata['authorization_endpoint']}?{query}"

    async def exchange(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> dict[str, Any]:
        metadata = await self.discovery()
        try:
            async with self.http_client() as client:
                response = await client.post(
                    metadata["token_endpoint"],
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.redirect_uri,
                        "client_id": self.settings.oidc_client_id,
                        "client_secret": self.settings.oidc_client_secret,
                        "code_verifier": code_verifier,
                    },
                )
                response.raise_for_status()
                token = response.json()
                jwks_response = await client.get(str(metadata["jwks_uri"]))
                jwks_response.raise_for_status()
                jwks_payload = dict(jwks_response.json())
            id_token = str(token["id_token"])
            token_kid = str(jwt.get_unverified_header(id_token).get("kid", ""))
            signing_key = next(
                (
                    candidate.key
                    for candidate in jwt.PyJWKSet.from_dict(jwks_payload).keys
                    if candidate.key_id == token_kid
                ),
                None,
            )
            if signing_key is None:
                raise OIDCError("signing_key_not_found")
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=["RS256"],
                audience=self.settings.oidc_client_id,
                issuer=str(self.settings.oidc_issuer).rstrip("/"),
            )
            return validate_claims(claims, expected_nonce, self.settings.allowed_domains)
        except OIDCError:
            raise
        except (
            httpx.HTTPError,
            KeyError,
            TypeError,
            ValueError,
            jwt.PyJWTError,
        ):
            raise OIDCError("provider_exchange_failed") from None


def encode_dev_code(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_dev_code(code: str) -> dict[str, Any]:
    try:
        return dict(json.loads(base64.urlsafe_b64decode(code.encode())))
    except (ValueError, json.JSONDecodeError):
        raise OIDCError("invalid_code") from None
