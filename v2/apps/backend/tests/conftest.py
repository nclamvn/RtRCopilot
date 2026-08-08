import os
from urllib.parse import unquote, urlsplit


def _guard_integration_database() -> None:
    """Make it impossible for write-heavy integration tests to target live SOT.

    The integration suite publishes synthetic records by design.  Merely
    requiring ``INTEGRATION_DATABASE_DSN`` is not isolation: a developer can
    accidentally point it at the local operational database and poison search
    with approved-looking fixtures.  Every supported runner creates a database
    under one of these disposable prefixes and drops it after the gate.
    """
    dsn = os.getenv("INTEGRATION_DATABASE_DSN", "").strip()
    if not dsn:
        return
    database = unquote(urlsplit(dsn).path.lstrip("/"))
    disposable_prefixes = ("rtr_test_", "rtr_verify_", "rtr_tip")
    if not database.startswith(disposable_prefixes):
        raise RuntimeError(
            f"integration_database_not_disposable:{database or 'missing'}"
        )


_guard_integration_database()

os.environ.setdefault("POSTGRES_DSN", "postgresql://user:password@localhost:5432/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("S3_ACCESS_KEY", "local")
os.environ.setdefault("S3_SECRET_KEY", "local-secret")
os.environ.setdefault("S3_BUCKET", "rtr-test")
