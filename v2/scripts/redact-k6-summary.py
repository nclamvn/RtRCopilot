#!/usr/bin/env python3
"""Remove authentication material from a k6 JSON summary in place."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: redact-k6-summary.py SUMMARY_JSON")

    summary = Path(sys.argv[1]).resolve()
    payload = json.loads(summary.read_text(encoding="utf-8"))
    setup_data = payload.get("setup_data")
    if isinstance(setup_data, dict):
        for key in tuple(setup_data):
            if key.lower() in {"cookie", "authorization", "token", "secret"}:
                setup_data[key] = "[REDACTED]"

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{summary.name}.", dir=summary.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
        temporary.chmod(summary.stat().st_mode)
        temporary.replace(summary)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
