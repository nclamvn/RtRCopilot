"""Explicit server-side configuration; never discover legacy credentials."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import json
from urllib.parse import urlsplit


def local_origins(value: str) -> tuple[str, ...]:
    """Explicit launcher configuration, never an arbitrary remote CORS grant."""
    if len(value) > 2048:
        raise ValueError("invalid_loopback_origins")
    values = json.loads(value)
    if not isinstance(values, list) or not 1 <= len(values) <= 12:
        raise ValueError("invalid_loopback_origins")
    result = []
    for item in values:
        if not isinstance(item, str):
            raise ValueError("invalid_loopback_origins")
        url = urlsplit(item)
        if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username is not None or url.password is not None
                or url.path not in {"", "/"} or url.query or url.fragment
                or url.port is None or not 1024 <= url.port <= 65535):
            raise ValueError("invalid_loopback_origins")
        host = "[::1]" if url.hostname == "::1" else url.hostname
        normalized = f"http://{host}:{url.port}"
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model: str | None = None
    test_mode: bool = False
    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.openai.com/v1"
    external_processing: bool = False
    fixture_tools_enabled: bool = False
    configuration_error: str | None = None
    deadline_seconds: float = 120
    request_limit: int = 8
    tool_limit: int = 16
    token_limit: int = 32000
    output_bytes_limit: int = 256000
    origins: tuple[str, ...] = (
        "http://localhost:3110", "http://127.0.0.1:3110",
        "http://localhost:8110", "http://127.0.0.1:8110",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        from .provider_config import load_profile
        profile, error = {}, None
        if os.environ.get("WORKSPACE_CONFIG"):
            try:
                profile = load_profile(Path(os.environ["WORKSPACE_CONFIG"]))
            except (ValueError, OSError):
                error = "private_configuration_invalid"
        origins = cls.__dataclass_fields__["origins"].default
        if "WORKSPACE_ORIGINS" in os.environ:
            try:
                origins = local_origins(os.environ["WORKSPACE_ORIGINS"])
            except (TypeError, ValueError):
                # Invalid local configuration must not silently widen/restore a
                # default origin. Mutation requests fail closed until repaired.
                origins, error = (), error or "invalid_loopback_origins"
        return cls(
            data_dir=Path(os.environ.get("WORKSPACE_DATA_DIR", ".workspace-data")).resolve(),
            model=os.environ.get("WORKSPACE_MODEL") or profile.get("model"),
            test_mode=os.environ.get("WORKSPACE_TEST_MODE") == "1",
            api_key=os.environ.get("WORKSPACE_API_KEY") or profile.get("api_key"),
            base_url=os.environ.get("WORKSPACE_BASE_URL") or profile.get("base_url", "https://api.openai.com/v1"),
            external_processing=(os.environ["WORKSPACE_EXTERNAL_PROCESSING"] == "1") if "WORKSPACE_EXTERNAL_PROCESSING" in os.environ else profile.get("external_processing", False),
            fixture_tools_enabled=(os.environ["WORKSPACE_FIXTURE_TOOLS"] == "1") if "WORKSPACE_FIXTURE_TOOLS" in os.environ else profile.get("fixture_tools_enabled", False),
            configuration_error=error,
            origins=origins,
        )
