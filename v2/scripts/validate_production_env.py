#!/usr/bin/env python3
"""Content-free validation for the production deployment environment.

The validator reads a fully materialized Docker env file without sourcing it,
never emits a value, and verifies the deployment-only controls that the
application Settings model cannot see (TLS material, ingress coherence and
secret-file permissions).
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import shlex
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
BUILD_IDENTITY = re.compile(r"^[0-9a-f]{12,64}$")
DOMAIN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}$",
)
PLACEHOLDER_MARKERS = (
    "__set_",
    "change-this",
    "replace-with",
    "changeme",
    "example.invalid",
    "identity.example",
    "your-",
    "<required",
)
REQUIRED_KEYS = frozenset({
    "APP_ENV",
    "RTR_BUILD_SHA",
    "POSTGRES_PASSWORD",
    "POSTGRES_RUNTIME_PASSWORD",
    "MIGRATION_DSN",
    "POSTGRES_DSN",
    "REDIS_URL",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
    "PUBLIC_BASE_URL",
    "OIDC_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_ALLOWED_DOMAINS",
    "OIDC_GROUP_MAPPING",
    "DEV_OIDC_ENABLED",
    "SESSION_COOKIE_SECURE",
    "SOT_SIGNING_SECRET",
    "RAG_PROVIDER_MODE",
    "RAG_EMBEDDING_PROVIDER",
    "RAG_EXTERNAL_CLASSIFICATION_ALLOWLIST",
    "RAG_EXTERNAL_ENDPOINT_POLICY",
    "RAG_EXTERNAL_CREDENTIAL_SOURCE",
    "OPENAI_API_KEY",
    "BACKUP_DESTINATION",
    "INGRESS_HOST",
    "INGRESS_BIND_ADDRESS",
    "INGRESS_HSTS_MAX_AGE",
    "INGRESS_TLS_MODE",
    "INGRESS_CERTS_DIR",
})
SECRET_KEYS = (
    "POSTGRES_PASSWORD",
    "POSTGRES_RUNTIME_PASSWORD",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "OIDC_CLIENT_SECRET",
    "SOT_SIGNING_SECRET",
    "OPENAI_API_KEY",
)
CONNECTOR_KEYS = (
    "RTR_CONNECTOR_APPROVED_HOSTS",
    "RTR_CRM_CONNECTOR_BASE_URL",
    "RTR_CRM_CONNECTOR_TOKEN",
)
CertificateChecker = Callable[[Path, Path, str], tuple[list[str], str | None]]


def parse_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}, ["environment_file:unreadable"]

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            errors.append(f"line_{line_number}:export_not_allowed")
            continue
        if "=" not in line:
            errors.append(f"line_{line_number}:assignment_required")
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not ENV_KEY.fullmatch(key):
            errors.append(f"line_{line_number}:invalid_key")
            continue
        if key in values:
            errors.append(f"{key.lower()}:duplicate")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if "${" in value or "$(" in value:
            errors.append(f"{key.lower()}:must_be_materialized")
        values[key] = value
    return values, errors


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return not lowered or any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _safe_url_host(
    values: dict[str, str],
    key: str,
    errors: list[str],
) -> str | None:
    value = values.get(key, "")
    try:
        parsed = urlsplit(value)
    except ValueError:
        errors.append(f"{key.lower()}:invalid_url")
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        errors.append(f"{key.lower()}:https_required")
        return None
    hostname = parsed.hostname.lower()
    if (
        hostname == "localhost"
        or hostname.endswith((".invalid", ".example", ".test", ".localhost"))
    ):
        errors.append(f"{key.lower()}:reserved_host_forbidden")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_loopback or address.is_unspecified):
        errors.append(f"{key.lower()}:non_routable_host_forbidden")
    if parsed.username or parsed.password:
        errors.append(f"{key.lower()}:userinfo_forbidden")
    if key == "PUBLIC_BASE_URL" and (parsed.path not in {"", "/"} or parsed.query):
        errors.append("public_base_url:origin_only")
    return hostname


def _dsn_password(value: str) -> str:
    try:
        return unquote(urlsplit(value).password or "")
    except ValueError:
        return ""


def _run_openssl(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["openssl", *args],
        check=False,
        capture_output=True,
    )


def validate_certificate_material(
    certificate: Path,
    private_key: Path,
    hostname: str,
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    if shutil.which("openssl") is None:
        return ["tls:openssl_unavailable"], None
    if not certificate.is_file():
        errors.append("tls_certificate:file_missing")
    if not private_key.is_file():
        errors.append("tls_private_key:file_missing")
    if errors:
        return errors, None
    if stat.S_IMODE(private_key.stat().st_mode) & 0o077:
        errors.append("tls_private_key:permissions_too_broad")

    cert_check = _run_openssl("x509", "-in", str(certificate), "-noout")
    key_check = _run_openssl("pkey", "-in", str(private_key), "-noout")
    expiry_check = _run_openssl(
        "x509", "-in", str(certificate), "-noout", "-checkend", "604800",
    )
    host_check = _run_openssl(
        "x509", "-in", str(certificate), "-noout", "-checkhost", hostname,
    )
    if cert_check.returncode != 0:
        errors.append("tls_certificate:invalid_pem")
    if key_check.returncode != 0:
        errors.append("tls_private_key:invalid_pem")
    if expiry_check.returncode != 0:
        errors.append("tls_certificate:expires_within_seven_days")
    if host_check.returncode != 0:
        errors.append("tls_certificate:hostname_mismatch")
    if not errors:
        cert_pub = _run_openssl(
            "x509", "-in", str(certificate), "-pubkey", "-noout",
        )
        key_pub = _run_openssl(
            "pkey", "-in", str(private_key), "-pubout",
        )
        if (
            cert_pub.returncode != 0
            or key_pub.returncode != 0
            or cert_pub.stdout != key_pub.stdout
        ):
            errors.append("tls_private_key:certificate_mismatch")
    digest = (
        hashlib.sha256(certificate.read_bytes()).hexdigest()
        if not errors
        else None
    )
    return errors, digest


def validate_environment(
    values: dict[str, str],
    *,
    env_path: Path,
    expected_build: str,
    certificate_checker: CertificateChecker = validate_certificate_material,
) -> dict[str, Any]:
    errors: list[str] = []
    missing = sorted(key for key in REQUIRED_KEYS if not values.get(key, "").strip())
    errors.extend(f"{key.lower()}:required" for key in missing)

    mode_restricted = False
    try:
        mode_restricted = stat.S_IMODE(env_path.stat().st_mode) & 0o077 == 0
    except OSError:
        errors.append("environment_file:unreadable")
    if not mode_restricted:
        errors.append("environment_file:permissions_too_broad")

    if values.get("APP_ENV") != "production":
        errors.append("app_env:production_required")
    build_identity = values.get("RTR_BUILD_SHA", "")
    if not BUILD_IDENTITY.fullmatch(build_identity):
        errors.append("rtr_build_sha:clean_identity_required")
    elif build_identity != expected_build:
        errors.append("rtr_build_sha:candidate_mismatch")

    public_host = _safe_url_host(values, "PUBLIC_BASE_URL", errors)
    oidc_host = _safe_url_host(values, "OIDC_ISSUER", errors)
    ingress_host = values.get("INGRESS_HOST", "").strip().lower()
    if ingress_host and not DOMAIN.fullmatch(ingress_host):
        errors.append("ingress_host:invalid_domain")
    if public_host and ingress_host and public_host != ingress_host:
        errors.append("ingress_host:public_origin_mismatch")
    if oidc_host == public_host and oidc_host is not None:
        errors.append("oidc_issuer:must_be_independent")

    if values.get("DEV_OIDC_ENABLED", "").lower() != "false":
        errors.append("dev_oidc_enabled:forbidden_in_production")
    if values.get("SESSION_COOKIE_SECURE", "").lower() != "true":
        errors.append("session_cookie_secure:required_in_production")

    domains = sorted({
        item.strip().lower()
        for item in values.get("OIDC_ALLOWED_DOMAINS", "").split(",")
        if item.strip()
    })
    if not domains:
        errors.append("oidc_allowed_domains:required")
    elif any(not DOMAIN.fullmatch(domain) for domain in domains):
        errors.append("oidc_allowed_domains:invalid")
    try:
        group_mapping = json.loads(values.get("OIDC_GROUP_MAPPING", ""))
        if not isinstance(group_mapping, dict):
            raise TypeError
    except (json.JSONDecodeError, TypeError):
        errors.append("oidc_group_mapping:object_required")

    for key in REQUIRED_KEYS:
        if key in values and _is_placeholder(values[key]):
            errors.append(f"{key.lower()}:placeholder_forbidden")

    secrets = {key: values.get(key, "") for key in SECRET_KEYS}
    if any(len(value) < 20 for value in secrets.values()):
        errors.append("secret_catalog:minimum_entropy_length")
    populated_secret_values = [value for value in secrets.values() if value]
    if len(populated_secret_values) != len(set(populated_secret_values)):
        errors.append("secret_catalog:reuse_forbidden")
    if _dsn_password(values.get("MIGRATION_DSN", "")) != values.get(
        "POSTGRES_PASSWORD", ""
    ):
        errors.append("migration_dsn:owner_password_mismatch")
    if _dsn_password(values.get("POSTGRES_DSN", "")) != values.get(
        "POSTGRES_RUNTIME_PASSWORD", ""
    ):
        errors.append("postgres_dsn:runtime_password_mismatch")

    allowlist = {
        item.strip().lower()
        for item in values.get("RAG_EXTERNAL_CLASSIFICATION_ALLOWLIST", "").split(",")
        if item.strip()
    }
    if values.get("RAG_PROVIDER_MODE") != "external":
        errors.append("rag_provider_mode:external_required")
    if values.get("RAG_EMBEDDING_PROVIDER") != "openai":
        errors.append("rag_embedding_provider:openai_required")
    if "internal" not in allowlist:
        errors.append("rag_external_classification_allowlist:internal_required")
    if values.get("RAG_ANSWER_LLM_REQUIRED", "true").lower() != "true":
        errors.append("rag_answer_llm_required:true_required")

    active_connectors = [key for key in CONNECTOR_KEYS if values.get(key, "").strip()]
    if active_connectors:
        errors.append("enterprise_connectors:must_remain_off")
    if values.get("RAG_EXPOSE_DECISION_DIAGNOSTICS", "false").lower() == "true":
        errors.append("rag_expose_decision_diagnostics:forbidden_in_production")

    try:
        hsts = int(values.get("INGRESS_HSTS_MAX_AGE", "0"))
    except ValueError:
        hsts = 0
    if hsts < 31_536_000:
        errors.append("ingress_hsts_max_age:one_year_required")
    try:
        ipaddress.ip_address(values.get("INGRESS_BIND_ADDRESS", ""))
    except ValueError:
        errors.append("ingress_bind_address:ip_required")

    tls_parts: list[str] = []
    try:
        tls_parts = shlex.split(values.get("INGRESS_TLS_MODE", ""))
    except ValueError:
        errors.append("ingress_tls_mode:invalid")
    certificate_digest: str | None = None
    if tls_parts != ["/certs/fullchain.pem", "/certs/privkey.pem"]:
        errors.append("ingress_tls_mode:certificate_pair_required")
    elif ingress_host:
        cert_root = Path(values.get("INGRESS_CERTS_DIR", ""))
        if not cert_root.is_absolute():
            cert_root = env_path.parent / cert_root
        cert_errors, certificate_digest = certificate_checker(
            cert_root / "fullchain.pem",
            cert_root / "privkey.pem",
            ingress_host,
        )
        errors.extend(cert_errors)

    unique_errors = sorted(set(errors))
    domains_digest = hashlib.sha256(
        "\n".join(domains).encode("utf-8"),
    ).hexdigest()
    return {
        "schema_version": 1,
        "status": "pass" if not unique_errors else "blocked",
        "candidate_build": expected_build,
        "checks": {
            "environment_file_mode_restricted": mode_restricted,
            "application_environment": values.get("APP_ENV") == "production",
            "build_identity_exact": build_identity == expected_build,
            "https_public_origin": public_host is not None,
            "https_oidc_issuer": oidc_host is not None,
            "ingress_origin_aligned": public_host == ingress_host,
            "secure_cookie": values.get("SESSION_COOKIE_SECURE", "").lower()
            == "true",
            "dev_oidc_disabled": values.get("DEV_OIDC_ENABLED", "").lower()
            == "false",
            "corporate_domain_count": len(domains),
            "corporate_domains_digest": domains_digest,
            "secret_catalog_count": len([value for value in secrets.values() if value]),
            "external_internal_policy": "internal" in allowlist,
            "connectors_feature_off": not active_connectors,
            "hsts_one_year": hsts >= 31_536_000,
            "certificate_digest": certificate_digest,
        },
        "errors": unique_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--expected-build", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    values, parse_errors = parse_env_file(args.env_file)
    report = validate_environment(
        values,
        env_path=args.env_file,
        expected_build=args.expected_build,
    )
    if parse_errors:
        report["errors"] = sorted(set([*report["errors"], *parse_errors]))
        report["status"] = "blocked"
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
