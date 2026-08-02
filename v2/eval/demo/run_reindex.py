#!/usr/bin/env python3
"""TIP-013B LOCAL demo · drain the SOT reindex outbox synchronously.

After the curator-gated ``--apply`` activates the SOT revisions, each activation
enqueues a ``sot_reindex_outbox`` row.  In production the long-running worker
drains it; for a one-shot LOCAL demo this drives the SAME
``ReindexService.process_next()`` the worker calls, in a bounded loop, until the
backlog is empty.  No new code path — it is the worker's own reindex step invoked
directly so the RAG index reflects the freshly-activated facts immediately.
"""

from __future__ import annotations

import asyncio
import sys

from rtr_copilot.rag.reindex import ReindexService


async def _drain(max_iterations: int = 1000) -> int:
    service = ReindexService()
    processed = 0
    for _ in range(max_iterations):
        outbox_id = await service.process_next()
        if outbox_id is None:
            break
        processed += 1
        print(f"reindexed outbox {outbox_id}")
    return processed


def main() -> int:
    processed = asyncio.run(_drain())
    print(f"reindex complete: {processed} outbox row(s) processed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
