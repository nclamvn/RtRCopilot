"""Explicit server-side configuration; never discover legacy credentials."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model: str | None = None
    test_mode: bool = False
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
        return cls(
            data_dir=Path(os.environ.get("WORKSPACE_DATA_DIR", ".workspace-data")).resolve(),
            model=os.environ.get("WORKSPACE_MODEL") or None,
            test_mode=os.environ.get("WORKSPACE_TEST_MODE") == "1",
        )
