import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rtr_copilot.sot.package import fingerprint_tree


def _record_candidates(root: Path, record_key: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.jsonl")):
        try:
            for line in path.read_text(errors="replace").splitlines():
                value = json.loads(line)
                if isinstance(value, dict) and (
                    value.get("record_key") == record_key
                    or value.get("id") == record_key
                ):
                    matches.append(value)
        except (OSError, json.JSONDecodeError):
            continue
    return matches


def probe_kernel_read_only(
    root: Path,
    record_key: str,
    *,
    now: datetime | None = None,
    token_max_age: timedelta = timedelta(days=7),
) -> dict[str, Any]:
    """Prove an invalid kernel import is blocked without mutating the kernel."""
    root = root.resolve()
    before = fingerprint_tree(root)
    reasons: list[str] = []
    candidates = _record_candidates(root, record_key)
    if not candidates:
        reasons.append("record_not_found")
    elif any(
        not item.get("provenance_level") or not item.get("source_refs")
        for item in candidates
    ):
        reasons.append("provenance_missing")
    token = root / "index" / ".publish_token"
    instant = now or datetime.now(UTC)
    if not token.is_file() or not token.read_text(errors="replace").strip():
        reasons.append("publish_token_missing")
    else:
        modified = datetime.fromtimestamp(token.stat().st_mtime, UTC)
        if instant - modified > token_max_age:
            reasons.append("publish_token_stale")
    fingerprints = root / "index" / "source_hashes.json"
    if not fingerprints.is_file():
        reasons.append("source_fingerprint_coverage_missing")
    else:
        try:
            value = json.loads(fingerprints.read_text())
            if not isinstance(value, dict) or not value:
                reasons.append("source_fingerprint_coverage_partial")
        except json.JSONDecodeError:
            reasons.append("source_fingerprint_coverage_invalid")
    after = fingerprint_tree(root)
    return {
        "record_key": record_key,
        "decision": "blocked" if reasons else "eligible",
        "reason_codes": sorted(set(reasons)),
        "read_only": before == after,
        "before_fingerprint": before,
        "after_fingerprint": after,
    }
