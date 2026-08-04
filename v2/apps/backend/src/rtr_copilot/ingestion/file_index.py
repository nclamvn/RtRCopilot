"""Deterministic private-context indexing from verified rendition payloads."""

import hashlib
import json
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.ingestion.extractors import Artifact
from rtr_copilot.rag.adapters import OfflineHashEmbedding, normalize_query


def _item(value: Any, locator: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    rendered = str(value or "").strip()
    return (rendered, locator) if rendered else None


def searchable_units(artifact: Artifact) -> list[tuple[str, dict[str, Any]]]:
    """Extract bounded, locator-bearing text units from known safe JSON renditions."""
    if artifact.mime_type != "application/json":
        return []
    try:
        payload = json.loads(artifact.payload)
    except (TypeError, ValueError):
        return []
    units: list[tuple[str, dict[str, Any]] | None] = []
    kind = artifact.kind
    if kind == "page_text_json":
        units.extend(_item(row.get("text"), {"page": row.get("page")})
                     for row in payload.get("pages", []))
    elif kind == "structured_text_json":
        units.extend(_item(row.get("text"), {"paragraph": row.get("paragraph")})
                     for row in payload.get("paragraphs", []))
        units.extend(_item(" | ".join(map(str, row)), {"table": table.get("table")})
                     for table in payload.get("tables", [])
                     for row in table.get("rows", []))
        for field in ("headers", "footers", "footnotes"):
            units.extend(_item(row.get("text"), {field[:-1]: row.get(field[:-1])})
                         for row in payload.get(field, []))
        for slide in payload.get("slides", []):
            units.extend(_item(shape.get("text"), {
                "slide": slide.get("slide"), "shape": shape.get("shape"),
            }) for shape in slide.get("shapes", []))
            units.append(_item(slide.get("notes"), {"slide": slide.get("slide")}))
    elif kind == "sheet_preview_json":
        units.extend(_item(
            " | ".join(str(cell.get("value", "")) for cell in row.get("cells", [])),
            {
                "sheet": sheet.get("sheet"),
                "cell": next((cell.get("cell") for cell in row.get("cells", [])), None),
            },
        ) for sheet in payload.get("sheets", []) for row in sheet.get("rows", []))
    elif kind == "ocr_json":
        units.extend(_item(row.get("text"), {
            "page": row.get("page"), "region": row.get("region"),
        }) for row in payload.get("regions", []))
    elif kind == "transcript_json":
        units.extend(_item(row.get("text"), {"t": row.get("start_ms")})
                     for row in payload.get("segments", []))
    return [unit for unit in units if unit is not None]


async def index_artifact(
    session: AsyncSession,
    *,
    version_id: uuid.UUID,
    rendition_id: uuid.UUID,
    source_sha256: str,
    artifact: Artifact,
    embedding: OfflineHashEmbedding,
) -> int:
    units: Iterable[tuple[str, dict[str, Any]]] = searchable_units(artifact)
    count = 0
    for ordinal, (display_text, locator) in enumerate(units, start=1):
        normalized = normalize_query(display_text)
        if not normalized:
            continue
        file_chunk_id = uuid.uuid5(version_id, f"{rendition_id}:{ordinal}")
        await session.execute(text("""
            INSERT INTO file_chunks(
              file_chunk_id,document_version_id,rendition_id,chunk_key,
              display_text,normalized_text,text_sha256,source_sha256,
              rendition_sha256,rendition_kind,locator,ordinal,embedding
            ) VALUES (
              :chunk_id,:version_id,:rendition_id,:chunk_key,:display_text,
              :normalized_text,:text_sha256,:source_sha256,:rendition_sha256,
              :rendition_kind,CAST(:locator AS jsonb),:ordinal,
              CAST(:embedding AS vector)
            ) ON CONFLICT (document_version_id,rendition_id,ordinal) DO NOTHING
        """), {
            "chunk_id": file_chunk_id,
            "version_id": version_id,
            "rendition_id": rendition_id,
            "chunk_key": f"file:{version_id}:{rendition_id}:{ordinal:08d}",
            "display_text": display_text,
            "normalized_text": normalized,
            "text_sha256": hashlib.sha256(display_text.encode()).hexdigest(),
            "source_sha256": source_sha256,
            "rendition_sha256": artifact.sha256,
            "rendition_kind": artifact.kind,
            "locator": json.dumps(locator),
            "ordinal": ordinal,
            "embedding": json.dumps(embedding.embed(normalized)),
        })
        count += 1
    return count
