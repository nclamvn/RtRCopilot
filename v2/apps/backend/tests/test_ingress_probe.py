"""TIP-012 Task 1 — through-ingress probes (AC-01, AC-02, AC-03).

These tests run against a live hardened stack (`make hardened-up`) and are
skipped otherwise. Configure with:

    INGRESS_PROBE_ORIGIN=https://rtr.local        (hostname must resolve to
    INGRESS_PROBE_HTTP_ORIGIN=http://rtr.local     127.0.0.1, e.g. /etc/hosts)

TLS verification is disabled because local runs use Caddy's internal CA;
`docker compose cp ingress:/data/caddy/pki/authorities/local/root.crt` exports
the root for browsers/curl.
"""

import os
import re

import httpx
import pytest

ORIGIN = os.getenv("INGRESS_PROBE_ORIGIN")
HTTP_ORIGIN = os.getenv(
    "INGRESS_PROBE_HTTP_ORIGIN",
    (ORIGIN or "").replace("https://", "http://"),
)
pytestmark = pytest.mark.skipif(
    not ORIGIN,
    reason="ingress probe origin not configured",
)

#: Values that must never appear in any ingress-served response: dev-default
#: credentials, DSN/URL shapes and internal service endpoints (compose DNS).
FORBIDDEN_FRAGMENTS = [
    "change-this-local-password",
    "change-this-runtime-password",
    "change-this-local-secret",
    "development-only-sot-signing-secret-32bytes",
    "replace-with-a-dedicated-random-secret-at-least-32-bytes",
    "postgres:5432",
    "redis:6379",
    "minio:9000",
    "api:8000",
    "web:3000",
    "clamav:3310",
    "http://minio",
    "http://postgres",
    "http://redis",
    "http://api",
    "http://web",
    "postgresql://",
    "redis://",
    "s3://",
    "rtr_owner",
    "rtr_app",
    "X-Amz-",
    "amazonaws",
]
#: Internal compose hostnames asserted as standalone words.
INTERNAL_HOSTNAMES = re.compile(
    r"\b(minio|postgres|redis|clamav)\b",
    re.IGNORECASE,
)

#: Surfaces probed for leaks: normal pages, API errors, traversal attempts.
PROBE_PATHS = [
    "/",
    "/nonexistent-page-should-404",
    "/api/status",
    "/api/auth/me",
    "/api/v1/definitely-not-a-route",
    "/api/v1/files/catalog",
    "/api/ask/not-a-family",
    "/api/governance/../../etc/passwd",
    "/api/files/%2e%2e/%2e%2e/etc/passwd",
    "/api/document-os/does-not-exist",
]


def client() -> httpx.Client:
    assert ORIGIN is not None
    # trust_env=False: the probe targets the local ingress directly and must
    # ignore any HTTPS_PROXY configured in the surrounding environment.
    return httpx.Client(base_url=ORIGIN, verify=False, timeout=15, trust_env=False)


def flatten(response: httpx.Response) -> str:
    headers = "\n".join(f"{key}: {value}" for key, value in response.headers.items())
    return headers + "\n" + response.text


def test_http_redirects_to_https() -> None:
    with httpx.Client(verify=False, timeout=15, trust_env=False) as http:
        response = http.get(f"{HTTP_ORIGIN}/", follow_redirects=False)
    assert response.status_code in {301, 308}
    assert response.headers["location"].startswith("https://")


def test_security_headers_on_pages() -> None:
    with client() as session:
        response = session.get("/", follow_redirects=True)
    assert response.status_code == 200
    assert "max-age=" in response.headers["strict-transport-security"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "referrer-policy" in response.headers
    assert "permissions-policy" in response.headers
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


def test_security_headers_on_api_error_responses() -> None:
    with client() as session:
        response = session.get("/api/v1/definitely-not-a-route")
    assert response.status_code == 404
    assert "max-age=" in response.headers["strict-transport-security"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_file_content_responses_stay_embeddable_same_origin_only() -> None:
    """The PDF viewer embeds /api/files/* same-origin; DENY would break it,
    so that path class gets SAMEORIGIN + frame-ancestors 'self' instead."""
    with client() as session:
        response = session.get("/api/files/some-version-id/content")
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert "max-age=" in response.headers["strict-transport-security"]


@pytest.mark.parametrize("path", PROBE_PATHS)
def test_no_internal_topology_or_secret_leaks(path: str) -> None:
    with client() as session:
        response = session.get(path)
    payload = flatten(response)
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment.lower() not in payload.lower(), (
            f"{path} leaked {fragment!r}"
        )
    match = INTERNAL_HOSTNAMES.search(payload)
    assert match is None, f"{path} leaked internal hostname {match.group(0)!r}"


def test_auth_flow_completes_through_ingress_with_secure_cookie() -> None:
    with client() as session:
        login = session.get("/api/auth/login", follow_redirects=False)
        assert login.status_code == 302
        authorize_path = login.headers["location"]
        assert authorize_path.startswith("/api/auth/dev/authorize")

        authorize = session.get(authorize_path, follow_redirects=False)
        assert authorize.status_code == 302
        callback_url = authorize.headers["location"]
        assert ORIGIN is not None
        assert callback_url.startswith(ORIGIN.rstrip("/")), (
            "dev OIDC callback must stay on the ingress origin "
            f"(got {callback_url!r}; is PUBLIC_BASE_URL set to the ingress?)"
        )

        callback = session.get(
            callback_url.removeprefix(ORIGIN.rstrip("/")),
            follow_redirects=False,
        )
        assert callback.status_code == 302
        cookie = callback.headers["set-cookie"]
        assert "Secure" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie

        me = session.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "staff@rtrobotics.com"

        for response in (login, authorize, callback, me):
            payload = flatten(response)
            for fragment in FORBIDDEN_FRAGMENTS:
                assert fragment.lower() not in payload.lower()
