import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from rtr_copilot.config import Settings


def test_invalid_configuration_does_not_echo_secrets() -> None:
    sentinels = {
        "POSTGRES_DSN": "sentinel-postgres-dsn",
        "REDIS_URL": "sentinel-redis-url",
        "S3_ENDPOINT": "sentinel-s3-url",
        "S3_ACCESS_KEY": "sentinel-user",
        "S3_SECRET_KEY": "sentinel-password",
        "S3_BUCKET": "sentinel-bucket",
    }
    environment = {**os.environ, **sentinels}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from rtr_copilot.config import get_settings; get_settings()",
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Invalid configuration:" in output
    assert "postgres_dsn:" in output
    assert "redis_url:" in output
    assert "s3_endpoint:" in output
    for sentinel in sentinels.values():
        assert sentinel not in output


def test_production_identity_config_fails_fast_without_echoing_values() -> None:
    sentinels = {
        "POSTGRES_DSN": "postgresql://user:password@localhost:5432/db",
        "REDIS_URL": "redis://localhost:6379/0",
        "S3_ENDPOINT": "http://localhost:9000",
        "S3_ACCESS_KEY": "ACCESS_SENTINEL",
        "S3_SECRET_KEY": "PASSWORD_SENTINEL",
        "S3_BUCKET": "sentinel-bucket",
        "APP_ENV": "production",
        "PUBLIC_BASE_URL": "http://sentinel-callback.invalid",
        "OIDC_ISSUER": "https://sentinel-issuer.invalid",
        "OIDC_CLIENT_ID": "sentinel-client",
        "OIDC_CLIENT_SECRET": "sentinel-secret",
        "DEV_OIDC_ENABLED": "false",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from rtr_copilot.config import get_settings; get_settings()",
        ],
        capture_output=True,
        check=False,
        env={**os.environ, **sentinels},
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "public_base_url:https_required" in output
    for sentinel in sentinels.values():
        if sentinel not in {"production", "false"}:
            assert sentinel not in output

# --- TIP-012 Task 1 (AC-03): production boot guard on secret hygiene -------


def production_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "postgres_dsn": "postgresql://app_user:unique-runtime-pw-1@db.internal:5432/rtr",
        "migration_dsn": "postgresql://owner_user:unique-owner-pw-1@db.internal:5432/rtr",
        "redis_url": "redis://cache.internal:6379/0",
        "s3_endpoint": "http://objects.internal:9000",
        "s3_access_key": "prod-access-key",
        "s3_secret_key": "prod-secret-key-with-entropy",
        "s3_bucket": "rtr-copilot",
        "app_env": "production",
        "public_base_url": "https://copilot.rtrobotics.com",
        "oidc_issuer": "https://login.identity.example/tenant/v2.0",
        "oidc_client_id": "prod-client-id",
        "oidc_client_secret": "prod-oidc-client-secret-value",
        "dev_oidc_enabled": False,
        "sot_signing_secret": "a-dedicated-production-signing-secret-48-bytes!!",
    }
    base.update(overrides)
    return base


def development_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "postgres_dsn": "postgresql://user:password@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "s3_endpoint": "http://localhost:9000",
        "s3_access_key": "local",
        "s3_secret_key": "local-secret",
        "s3_bucket": "rtr-test",
        "app_env": "development",
    }
    base.update(overrides)
    return base


def test_green_production_configuration_boots() -> None:
    settings = Settings(**production_kwargs())  # type: ignore[arg-type]
    assert settings.app_env == "production"
    assert settings.session_cookie_secure_effective is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "postgres_dsn",
            "postgresql://rtr_app:change-this-runtime-password@postgres:5432/rtr_copilot",
        ),
        (
            "migration_dsn",
            "postgresql://rtr_owner:change-this-local-password@postgres:5432/rtr_copilot",
        ),
        ("redis_url", "redis://:password@cache.internal:6379/0"),
        ("s3_access_key", "rtr-local"),
        ("s3_access_key", "minioadmin"),
        ("s3_secret_key", "change-this-local-secret"),
        ("s3_secret_key", "minioadmin"),
        ("oidc_client_secret", "changeme"),
        (
            "sot_signing_secret",
            "replace-with-a-dedicated-random-secret-at-least-32-bytes",
        ),
        (
            "sot_signing_secret",
            "development-only-sot-signing-secret-32bytes",
        ),
    ],
)
def test_production_refuses_every_known_default_secret(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(**production_kwargs(**{field: value}))  # type: ignore[arg-type]
    assert f"default_secret:{field}" in str(excinfo.value)


def test_production_refusal_lists_every_defaulted_secret_at_once() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(**production_kwargs(  # type: ignore[arg-type]
            s3_access_key="rtr-local",
            s3_secret_key="change-this-local-secret",
        ))
    message = str(excinfo.value)
    assert "default_secret:s3_access_key,s3_secret_key" in message


def test_production_refuses_session_cookie_secure_off() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(**production_kwargs(session_cookie_secure=False))  # type: ignore[arg-type]
    assert "session_cookie_secure:required_in_production" in str(excinfo.value)


def test_production_refuses_plaintext_oidc_issuer() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(**production_kwargs(  # type: ignore[arg-type]
            oidc_issuer="http://login.identity.example/tenant/v2.0",
        ))
    assert "oidc_issuer:https_required" in str(excinfo.value)


def test_session_cookie_secure_defaults_follow_environment() -> None:
    plain_dev = Settings(**development_kwargs())  # type: ignore[arg-type]
    assert plain_dev.session_cookie_secure_effective is False

    behind_tls_ingress = Settings(**development_kwargs(  # type: ignore[arg-type]
        public_base_url="https://rtr.local",
    ))
    assert behind_tls_ingress.session_cookie_secure_effective is True

    explicit_on = Settings(**development_kwargs(  # type: ignore[arg-type]
        session_cookie_secure=True,
    ))
    assert explicit_on.session_cookie_secure_effective is True

    explicit_off = Settings(**development_kwargs(  # type: ignore[arg-type]
        public_base_url="https://rtr.local",
        session_cookie_secure=False,
    ))
    assert explicit_off.session_cookie_secure_effective is False


def test_production_boot_guard_fails_closed_without_echoing_secret_values() -> None:
    shipped_defaults = {
        "POSTGRES_DSN": (
            "postgresql://rtr_app:change-this-runtime-password@postgres:5432/rtr_copilot"
        ),
        "MIGRATION_DSN": (
            "postgresql://rtr_owner:change-this-local-password@postgres:5432/rtr_copilot"
        ),
        "REDIS_URL": "redis://redis:6379/0",
        "S3_ENDPOINT": "http://minio:9000",
        "S3_ACCESS_KEY": "rtr-local",
        "S3_SECRET_KEY": "change-this-local-secret",
        "S3_BUCKET": "rtr-copilot",
        "SOT_SIGNING_SECRET": (
            "replace-with-a-dedicated-random-secret-at-least-32-bytes"
        ),
        "APP_ENV": "production",
        "PUBLIC_BASE_URL": "https://copilot.rtrobotics.com",
        "OIDC_ISSUER": "https://login.identity.example/tenant/v2.0",
        "OIDC_CLIENT_ID": "prod-client-id",
        "OIDC_CLIENT_SECRET": "changeme",
        "DEV_OIDC_ENABLED": "false",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from rtr_copilot.config import get_settings; get_settings()",
        ],
        capture_output=True,
        check=False,
        env={**os.environ, **shipped_defaults},
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "configuration_rejected" in output
    for key in [
        "postgres_dsn",
        "migration_dsn",
        "s3_access_key",
        "s3_secret_key",
        "oidc_client_secret",
        "sot_signing_secret",
    ]:
        assert f"{key}:known_default_forbidden" in output
    for secret_value in [
        "change-this-runtime-password",
        "change-this-local-password",
        "change-this-local-secret",
        "replace-with-a-dedicated-random-secret-at-least-32-bytes",
        "changeme",
    ]:
        assert secret_value not in output


def test_decision_diagnostics_default_off() -> None:
    """TIP-030: the refusal-diagnostic channel must be opt-in only —
    production honest-null responses stay unchanged unless an operator
    explicitly enables it (isolated e2e stacks)."""
    from rtr_copilot.config import Settings
    assert Settings().rag_expose_decision_diagnostics is False
