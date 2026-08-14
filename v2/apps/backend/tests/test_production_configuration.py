from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = PROJECT_ROOT / "scripts" / "validate_production_env.py"


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("production_env_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def production_values(**overrides: str) -> dict[str, str]:
    owner_password = "owner-password-with-entropy-001"
    runtime_password = "runtime-password-with-entropy-002"
    values = {
        "APP_ENV": "production",
        "RTR_BUILD_SHA": "0123456789abcdef0123456789abcdef01234567",
        "POSTGRES_PASSWORD": owner_password,
        "POSTGRES_RUNTIME_PASSWORD": runtime_password,
        "MIGRATION_DSN": (
            f"postgresql://rtr_owner:{owner_password}@postgres:5432/rtr_copilot"
        ),
        "POSTGRES_DSN": (
            f"postgresql://rtr_app:{runtime_password}@postgres:5432/rtr_copilot"
        ),
        "REDIS_URL": "redis://redis:6379/0",
        "S3_ENDPOINT": "http://minio:9000",
        "S3_ACCESS_KEY": "s3-access-key-with-entropy-003",
        "S3_SECRET_KEY": "s3-secret-key-with-entropy-004",
        "S3_BUCKET": "rtr-copilot",
        "PUBLIC_BASE_URL": "https://copilot.rtrobotics.com",
        "OIDC_ISSUER": "https://login.company-id.com/tenant/v2.0",
        "OIDC_CLIENT_ID": "rtr-copilot-production-client",
        "OIDC_CLIENT_SECRET": "oidc-secret-with-entropy-005",
        "OIDC_ALLOWED_DOMAINS": "rtrobotics.com",
        "OIDC_GROUP_MAPPING": "{}",
        "DEV_OIDC_ENABLED": "false",
        "SESSION_COOKIE_SECURE": "true",
        "SOT_SIGNING_SECRET": "sot-signing-secret-with-entropy-006",
        "RAG_PROVIDER_MODE": "external",
        "RAG_EMBEDDING_PROVIDER": "openai",
        "RAG_EXTERNAL_CLASSIFICATION_ALLOWLIST": "internal",
        "RAG_EXTERNAL_ENDPOINT_POLICY": "approved-policy-2026-001",
        "RAG_EXTERNAL_CREDENTIAL_SOURCE": "secret-manager/rtr/openai",
        "RAG_ANSWER_LLM_REQUIRED": "true",
        "OPENAI_API_KEY": "openai-key-with-entropy-007",
        "BACKUP_DESTINATION": "s3://encrypted-backups/rtr-copilot",
        "INGRESS_HOST": "copilot.rtrobotics.com",
        "INGRESS_BIND_ADDRESS": "10.0.0.10",
        "INGRESS_HSTS_MAX_AGE": "31536000",
        "INGRESS_TLS_MODE": "/certs/fullchain.pem /certs/privkey.pem",
        "INGRESS_CERTS_DIR": "/etc/rtr-copilot/tls",
        "RAG_EXPOSE_DECISION_DIAGNOSTICS": "false",
        "RTR_CONNECTOR_APPROVED_HOSTS": "",
        "RTR_CRM_CONNECTOR_BASE_URL": "",
        "RTR_CRM_CONNECTOR_TOKEN": "",
    }
    values.update(overrides)
    return values


def _env_file(tmp_path: Path, mode: int = 0o600) -> Path:
    path = tmp_path / ".env.production"
    path.write_text("APP_ENV=production\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _certificate_ok(
    certificate: Path,
    private_key: Path,
    hostname: str,
) -> tuple[list[str], str | None]:
    del certificate, private_key, hostname
    return [], "a" * 64


def _validate(
    tmp_path: Path,
    values: dict[str, str] | None = None,
    *,
    mode: int = 0o600,
) -> dict[str, Any]:
    env_path = _env_file(tmp_path, mode)
    return validator.validate_environment(
        values or production_values(),
        env_path=env_path,
        expected_build="0123456789abcdef0123456789abcdef01234567",
        certificate_checker=_certificate_ok,
    )


def test_complete_production_contract_passes_without_configuration_content(
    tmp_path: Path,
) -> None:
    report = _validate(tmp_path)

    assert report["status"] == "pass"
    assert report["errors"] == []
    assert report["checks"]["corporate_domain_count"] == 1
    assert "rtrobotics.com" not in json.dumps(report)
    assert "openai-key-with-entropy" not in json.dumps(report)


def test_placeholder_secret_is_blocked_without_leaking_value(tmp_path: Path) -> None:
    sentinel = "replace-with-SUPER-SECRET-SENTINEL"
    report = _validate(
        tmp_path,
        production_values(OPENAI_API_KEY=sentinel),
    )

    encoded = json.dumps(report)
    assert report["status"] == "blocked"
    assert "openai_api_key:placeholder_forbidden" in report["errors"]
    assert sentinel not in encoded


def test_origin_mismatch_and_reserved_hosts_are_blocked(tmp_path: Path) -> None:
    report = _validate(
        tmp_path,
        production_values(
            PUBLIC_BASE_URL="https://copilot.example.invalid",
            INGRESS_HOST="different.rtrobotics.com",
        ),
    )

    assert "public_base_url:reserved_host_forbidden" in report["errors"]
    assert "ingress_host:public_origin_mismatch" in report["errors"]


def test_environment_file_permissions_are_fail_closed(tmp_path: Path) -> None:
    report = _validate(tmp_path, mode=0o640)

    assert "environment_file:permissions_too_broad" in report["errors"]


def test_connector_activation_and_development_tls_are_blocked(tmp_path: Path) -> None:
    report = _validate(
        tmp_path,
        production_values(
            RTR_CRM_CONNECTOR_TOKEN="connector-secret-with-entropy",
            INGRESS_HSTS_MAX_AGE="604800",
            INGRESS_TLS_MODE="internal",
        ),
    )

    assert "enterprise_connectors:must_remain_off" in report["errors"]
    assert "ingress_hsts_max_age:one_year_required" in report["errors"]
    assert "ingress_tls_mode:certificate_pair_required" in report["errors"]


@pytest.mark.parametrize("expression", ["${SECRET}", "$(secret-command)"])
def test_parser_rejects_unmaterialized_shell_expressions(
    tmp_path: Path,
    expression: str,
) -> None:
    path = tmp_path / "production.env"
    path.write_text(f"OPENAI_API_KEY={expression}\n", encoding="utf-8")

    values, errors = validator.parse_env_file(path)

    assert values["OPENAI_API_KEY"] == expression
    assert "openai_api_key:must_be_materialized" in errors
