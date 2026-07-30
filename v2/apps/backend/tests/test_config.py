import os
import subprocess
import sys


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
