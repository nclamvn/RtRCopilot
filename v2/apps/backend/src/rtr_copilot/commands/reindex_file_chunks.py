"""Backfill private-context chunks from already verified JSON renditions."""

import argparse
import asyncio
import hashlib
import io
import json
from typing import Any, cast

from sqlalchemy import text

from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.extractors import Artifact
from rtr_copilot.ingestion.file_index import index_artifact
from rtr_copilot.rag.adapters import OfflineHashEmbedding
from rtr_copilot.storage.s3 import S3ObjectStorage


async def backfill(*, limit: int | None = None) -> dict[str, int]:
    settings = get_settings()
    uow = UnitOfWork()
    storage = S3ObjectStorage(settings)
    async with uow.factory() as session:
        rows = (await session.execute(text("""
            SELECT rd.rendition_id,rd.version_id,rd.kind,rd.mime_type,
              rd.quality_state,rd.quality_summary,rd.provenance,
              ob.object_key,ob.sha256,v.sha256 source_sha256
            FROM renditions rd
            JOIN object_blobs ob ON ob.object_id=rd.object_id
            JOIN document_versions v ON v.version_id=rd.version_id
            JOIN resources rr ON rr.resource_id=rd.rendition_id
            WHERE rd.status='ready' AND rd.mime_type='application/json'
              AND rr.lifecycle_state='active'
              AND NOT EXISTS (
                SELECT 1 FROM file_chunks fc
                WHERE fc.rendition_id=rd.rendition_id
              )
            ORDER BY rd.version_id,rd.rendition_id
            LIMIT :limit
        """), {"limit": limit})).mappings().all()
    indexed_renditions = indexed_chunks = skipped = 0
    embedding = OfflineHashEmbedding(settings.rag_embedding_dimension)
    for row in rows:
        target = io.BytesIO()
        await storage.download_to(str(row["object_key"]), target)
        payload = target.getvalue()
        if hashlib.sha256(payload).hexdigest() != str(row["sha256"]):
            skipped += 1
            continue
        provenance = dict(row["provenance"] or {})
        origin = provenance.get("origin", "native")
        if origin not in {"native", "ocr", "transcript", "render"}:
            origin = "native"
        artifact = Artifact(
            kind=str(row["kind"]),
            mime_type=str(row["mime_type"]),
            payload=payload,
            origin=cast(Any, origin),
            quality_state=cast(Any, row["quality_state"] or "complete"),
            quality=dict(row["quality_summary"] or {}),
        )
        async with uow.transaction() as session:
            count = await index_artifact(
                session,
                version_id=row["version_id"],
                rendition_id=row["rendition_id"],
                source_sha256=str(row["source_sha256"]),
                artifact=artifact,
                embedding=embedding,
            )
        indexed_renditions += 1
        indexed_chunks += count
    return {
        "eligible_renditions": len(rows),
        "indexed_renditions": indexed_renditions,
        "indexed_chunks": indexed_chunks,
        "skipped_checksum": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(backfill(limit=args.limit)), sort_keys=True))


if __name__ == "__main__":
    main()
