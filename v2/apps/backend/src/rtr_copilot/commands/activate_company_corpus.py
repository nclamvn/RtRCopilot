"""Explicit local activation gate for the approved company file corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from rtr_copilot.enterprise_corpus.company_files import activate_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--knowledge-root", required=True, type=Path)
    parser.add_argument("--approved-by", required=True, type=uuid.UUID)
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if not args.approve:
        parser.error("activation requires --approve")
    result = asyncio.run(activate_manifest(
        args.manifest,
        args.knowledge_root,
        args.approved_by,
    ))
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
