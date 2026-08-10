"""TIP-014RE · Re-embed the active corpus with the configured adapter.

Switching ``rag_embedding_provider`` (or its model/dimension) does not touch
any stored vector by itself — chunks belong to immutable generations. This
command re-queues the reindex outbox row of every ACTIVE source revision and
drains the SAME ``ReindexService`` the worker runs:

* The generation fingerprint includes embedding model, version and
  dimension, so a changed adapter produces a NEW generation per source and
  the active pointer flips atomically. Old generations (and the citations
  pointing at their chunks) are untouched.
* If the fingerprint is unchanged (same adapter/config), ``process`` returns
  the existing generation — the command is idempotent and safely re-runnable.

Run inside the api/worker container after ``alembic upgrade head``:

    python -m rtr_copilot.commands.reembed_corpus
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from rtr_copilot.rag.reindex import ReindexError, ReindexService


async def _run() -> int:
    service = ReindexService()
    adapter = service.embedding
    print(
        "reembed adapter: "
        f"model={adapter.model} version={adapter.version} "
        f"dimension={adapter.dimension}",
    )
    async with service.uow.transaction() as session:
        requeued = (await session.execute(text("""
            UPDATE sot_reindex_outbox o SET status='pending'
            FROM sot_active_revisions ar
            WHERE o.run_id = ar.activated_run_id
              AND o.status = 'dispatched'
            RETURNING o.source_key, o.revision
        """))).all()
        orphans = (await session.execute(text("""
            SELECT ar.source_key, ar.revision FROM sot_active_revisions ar
            WHERE NOT EXISTS (
              SELECT 1 FROM sot_reindex_outbox o
              WHERE o.run_id = ar.activated_run_id
            )
        """))).all()
    for source_key, revision in requeued:
        print(f"requeued {source_key} rev {revision}")
    if orphans:
        # Every activation inserts an outbox row, so an active revision
        # without one is a broken invariant — fail loudly, never silently
        # leave part of the corpus on the old embedding space.
        for source_key, revision in orphans:
            print(
                f"ERROR: active revision without outbox row: "
                f"{source_key} rev {revision}",
                file=sys.stderr,
            )
        return 2
    processed = 0
    skipped = 0
    for _ in range(1000):
        outbox_id = await service.pending_outbox_id()
        if outbox_id is None:
            break
        try:
            await service.process(outbox_id)
        except ReindexError as error:
            if str(error) != "outbox_not_current_active_revision":
                raise
            # Legacy debris: a pending row whose revision has since been
            # superseded or retired (integration-test sources accumulate
            # these in the demo database). Its work is obsolete by
            # definition — mark it dispatched so the drain terminates, and
            # say so out loud (observed live 09/08: the drain crashed on
            # such a row after 34 healthy sources).
            async with service.uow.transaction() as session:
                await session.execute(text("""
                    UPDATE sot_reindex_outbox
                    SET status='dispatched', dispatched_at=now()
                    WHERE outbox_id=:outbox_id
                """), {"outbox_id": outbox_id})
            skipped += 1
            print(f"skipped obsolete outbox {outbox_id} (revision no longer active)")
            continue
        # ``process`` marks the row dispatched on the full-build path, but
        # its idempotent early-return (fingerprint unchanged → generation
        # already active) leaves the requeued row pending — the drain would
        # spin on it forever. Mark dispatched unconditionally.
        async with service.uow.transaction() as session:
            await session.execute(text("""
                UPDATE sot_reindex_outbox
                SET status='dispatched', dispatched_at=now()
                WHERE outbox_id=:outbox_id AND status <> 'dispatched'
            """), {"outbox_id": outbox_id})
        processed += 1
        print(f"reembedded outbox {outbox_id}")
    print(
        f"reembed complete: requeued={len(requeued)} "
        f"processed={processed} skipped_obsolete={skipped}",
    )
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
