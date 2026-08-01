"""TIP-013 parity — load the REAL phase-1 pilot answering logic against a
SYNTHETIC knowledge package.

The pilot (`phase1_pilot/copilot_server.py`) is the behavioral contract for V1.
Its deterministic MOCK retrieval (`search` + `confident` + `mock_answer`) is the
oracle we compare V2 against. We must **read the oracle's answering logic without
touching or mutating its real store**: the real package lives at
`l3_pipeline/GOI_L3.yaml`, which is company data and strictly off-limits in Phase A.

Approach (the sanctioned "captured synthetic oracle snapshot"): we read the pilot
module source and execute it in an isolated namespace whose ``__file__`` points at
a synthetic fixture directory. The module computes ``HERE = Path(__file__).parent``
and its ``find()`` helper resolves ``GOI_L3.yaml`` / the system prompt / ``ui.html``
from ``HERE`` first — so it loads ONLY our synthetic fixtures. The real
``l3_pipeline`` corpus is never read, and nothing is ever written (the module's
HTTP server binds only under ``if __name__ == "__main__"``, which we never enter).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_LIB = Path(__file__).resolve()
REPO_ROOT = _LIB.parents[3]
PILOT_SRC = REPO_ROOT / "phase1_pilot" / "copilot_server.py"
DEFAULT_FIXTURE_DIR = _LIB.parents[1] / "parity" / "pilot_fixtures"

# A pilot answer is a "null" (no company answer) when it carries a GAP line or the
# intentionally-withheld marker; otherwise the pilot returned a record answer.
_NULL_MARKERS = ("\nGAP:", "KHÔNG CÓ TRONG GÓI")
_RECORD_TAG = re.compile(r"\[([A-Z0-9][A-Z0-9._-]{1,})")


def load_pilot_namespace(fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> dict[str, Any]:
    """Execute the pilot module against the synthetic fixture dir; return its globals."""
    if not PILOT_SRC.exists():  # pragma: no cover - defensive
        raise FileNotFoundError(f"pilot source not found: {PILOT_SRC}")
    source = PILOT_SRC.read_text(encoding="utf-8")
    namespace: dict[str, Any] = {
        "__name__": "pilot_oracle_synthetic",
        "__file__": str(fixture_dir / "copilot_server.py"),
    }
    guarded = ("ANTHROPIC_API_KEY", "COPILOT_PACK", "COPILOT_AUTH_MODE", "COPILOT_PASSCODE")
    saved = {key: os.environ.get(key) for key in guarded}
    os.environ.pop("ANTHROPIC_API_KEY", None)  # force MOCK (deterministic) mode
    os.environ.pop("COPILOT_PASSCODE", None)
    os.environ["COPILOT_PACK"] = "staff"
    os.environ["COPILOT_AUTH_MODE"] = "accounts"
    try:
        code = compile(source, str(PILOT_SRC), "exec")
        exec(code, namespace)  # noqa: S102 - controlled, reads only synthetic fixtures
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return namespace


class PilotOracle:
    """Thin, read-only wrapper over the pilot's deterministic MOCK answering."""

    def __init__(self, fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> None:
        self._ns = load_pilot_namespace(fixture_dir)
        self.record_ids = sorted(self._ns["BY_ID"].keys())

    def answer(self, question: str) -> str:
        return str(self._ns["mock_answer"](question))

    @staticmethod
    def is_null(answer: str) -> bool:
        return any(marker in answer for marker in _NULL_MARKERS)

    def outcome(self, question: str) -> dict[str, Any]:
        """Return {answer, state, cited_records} for one question."""
        answer = self.answer(question)
        null = self.is_null(answer)
        known = set(self.record_ids)
        cited = (
            []
            if null
            else [tag for tag in _RECORD_TAG.findall(answer) if tag in known]
        )
        return {
            "answer": answer,
            "state": "null" if null else "answered",
            "cited_records": cited,
        }
