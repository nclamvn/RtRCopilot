"""Print content-free provenance for the exact evaluation runtime."""

from __future__ import annotations

import asyncio
import json

from rtr_copilot.config import get_settings
from rtr_copilot.rag.evaluation_provenance import load_evaluation_provenance


async def amain() -> int:
    settings = get_settings()
    snapshot = await load_evaluation_provenance(
        ontology_path=settings.rag_ontology_path,
    )
    print(json.dumps({
        "schema_version": 1,
        "build_identity": settings.rtr_build_sha,
        "database_digest": snapshot.database_digest,
        "ontology_digest": snapshot.ontology_digest,
        "schema_revision": snapshot.schema_revision,
        "active_record_count": snapshot.active_record_count,
        "active_generation_count": snapshot.active_generation_count,
        "active_chunk_count": snapshot.active_chunk_count,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
