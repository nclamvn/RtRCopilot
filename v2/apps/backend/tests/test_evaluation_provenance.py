"""Deterministic retrieval-snapshot provenance regressions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from rtr_copilot.rag.evaluation_provenance import retrieval_snapshot_digest


def snapshot() -> dict[str, Any]:
    return {
        "schema_revision": "0014_document_outbox_repair",
        "records": [{
            "source_key": "rtr.specs",
            "record_key": "HC-001",
            "content_sha256": "a" * 64,
            "classification": "internal",
            "owner_subject_id": "11111111-1111-4111-8111-111111111111",
            "department_id": None,
            "project_id": None,
            "provenance_level": "approved_internal",
            "verification_state": "approved",
            "freshness_state": "current",
        }],
        "generations": [{
            "source_key": "rtr.specs",
            "source_revision": 1,
            "index_fingerprint": "b" * 64,
            "embedding_model": "text-embedding-3-small",
            "embedding_version": "openai-v1",
            "embedding_dimension": 1536,
            "chunker_version": "rtr-chunker-v1",
        }],
        "chunks": [{
            "index_fingerprint": "b" * 64,
            "source_key": "rtr.specs",
            "record_key": "HC-001",
            "ordinal": 1,
            "text_sha256": "c" * 64,
            "record_checksum": "a" * 64,
            "evidence_checksum": None,
            "chunking_fingerprint": "d" * 64,
            "embedding_sha256": "e" * 64,
            "evidence_key": None,
            "locator": "{}",
            "source_label": "RtR specifications",
            "classification": "internal",
            "owner_subject_id": "11111111-1111-4111-8111-111111111111",
            "department_id": None,
            "project_id": None,
            "provenance_level": "approved_internal",
            "verification_state": "approved",
            "freshness_state": "current",
        }],
    }


def digest(value: dict[str, Any]) -> str:
    return retrieval_snapshot_digest(
        schema_revision=str(value["schema_revision"]),
        records=value["records"],
        generations=value["generations"],
        chunks=value["chunks"],
    )


def test_retrieval_snapshot_digest_is_deterministic_sha256() -> None:
    value = snapshot()
    first = digest(value)
    assert first == digest(deepcopy(value))
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")


def test_retrieval_snapshot_digest_covers_content_index_and_acl() -> None:
    baseline = snapshot()
    for section, field, replacement in (
        ("records", "content_sha256", "e" * 64),
        ("records", "classification", "restricted"),
        ("generations", "embedding_version", "openai-v2"),
        ("chunks", "text_sha256", "f" * 64),
        ("chunks", "embedding_sha256", "0" * 64),
        ("chunks", "department_id", "22222222-2222-4222-8222-222222222222"),
    ):
        changed = deepcopy(baseline)
        changed[section][0][field] = replacement
        assert digest(changed) != digest(baseline), (section, field)
