"""Fail-loud verification for the checksum-bound KnowledgeBase delta batch.

This verifier is deliberately hermetic: it loads metadata, resolves files and
hashes bytes. It never constructs the ingestion campaign, database or embedding
adapter, so running it cannot export source content.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections.abc import Callable
from pathlib import Path

from rtr_copilot.enterprise_corpus.file_campaign import (
    EnterpriseFileManifest,
    enterprise_manifest_fingerprint,
    load_enterprise_file_manifest,
    plan_enterprise_files,
)


def _must_reject(label: str, operation: Callable[[], object]) -> str:
    try:
        operation()
    except (ValueError, OSError):
        return "pass"
    raise AssertionError(f"bite_failed:{label}")


def verify(manifest_path: Path, company_root: Path) -> dict[str, object]:
    manifest = load_enterprise_file_manifest(manifest_path)
    planned = plan_enterprise_files(manifest, company_root)
    if any(item.entry.classification != "restricted" for item in planned):
        raise AssertionError("classification_not_restricted")
    if any(item.entry.source_zone != "private_context" for item in planned):
        raise AssertionError("source_zone_not_private_context")

    duplicate = copy.deepcopy(manifest.model_dump(mode="python"))
    duplicate["entries"][1]["sha256"] = duplicate["entries"][0]["sha256"]
    checksum_drift = copy.deepcopy(manifest.model_dump(mode="python"))
    checksum_drift["entries"][0]["sha256"] = "0" * 64
    path_escape = copy.deepcopy(manifest.model_dump(mode="python"))
    path_escape["entries"][0]["path"] = "../outside.pdf"

    bites = {
        "duplicate_content": _must_reject(
            "duplicate_content",
            lambda: EnterpriseFileManifest.model_validate(duplicate),
        ),
        "checksum_drift": _must_reject(
            "checksum_drift",
            lambda: plan_enterprise_files(
                EnterpriseFileManifest.model_validate(checksum_drift),
                company_root,
            ),
        ),
        "path_escape": _must_reject(
            "path_escape",
            lambda: EnterpriseFileManifest.model_validate(path_escape),
        ),
    }
    return {
        "status": "pass",
        "mode": "hermetic_no_external",
        "file_count": len(planned),
        "byte_size": sum(item.byte_size for item in planned),
        "manifest_fingerprint": enterprise_manifest_fingerprint(manifest),
        "classification": "restricted",
        "source_zone": "private_context",
        "bites": bites,
        "external_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--company-root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(
        verify(args.manifest, args.company_root),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
