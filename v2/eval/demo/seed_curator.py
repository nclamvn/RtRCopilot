#!/usr/bin/env python3
"""TIP-013B LOCAL demo · seed the curator + owner subjects for onboarding.

The curated real-kernel packages are signed by the deterministic migration
curator (``kernel_adapter.CURATOR_ID``) and own their records as
``kernel_adapter.OWNER_ID``.  ``records.owner_subject_id`` and the audit
``actor_user_id`` both carry a foreign key to ``subjects(user_id)``, so those two
principals must exist before the curator-gated ``--apply`` runs.  This mirrors
exactly what ``tests/test_tip013_onboard_integration.py`` does with
``_insert_subject`` — it grants no privilege (roles are asserted by the manifest
+ the independent attestation-signature check), it only satisfies the FK.

Idempotent: ``ON CONFLICT DO NOTHING``.  Reads the app DSN from the same
settings/env the onboarding tool uses, so the LOCAL runner needs no extra config.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from migrate.kernel_adapter import CURATOR_ID, OWNER_ID  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from rtr_copilot.config import get_settings  # noqa: E402

_SUBJECTS: tuple[tuple[uuid.UUID, str], ...] = (
    (CURATOR_ID, "tip013b-migration-curator"),
    (OWNER_ID, "tip013b-migration-owner"),
)


async def _seed() -> None:
    settings = get_settings()
    dsn = str(settings.postgres_dsn).replace(
        "postgresql://", "postgresql+asyncpg://", 1,
    )
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            for subject_id, sub in _SUBJECTS:
                await conn.execute(
                    text(
                        """
                        INSERT INTO subjects
                          (user_id, issuer, provider_sub, email,
                           canonical_domain, display_name)
                        VALUES
                          (:id, 'tip013b-onboard', :sub, :email,
                           'rtrobotics.com', :name)
                        ON CONFLICT (user_id) DO NOTHING
                        """,
                    ),
                    {
                        "id": subject_id,
                        "sub": sub,
                        "email": f"{sub}@rtrobotics.com",
                        "name": sub,
                    },
                )
    finally:
        await engine.dispose()
    for subject_id, sub in _SUBJECTS:
        print(f"seeded subject {subject_id} ({sub})")


def main() -> int:
    asyncio.run(_seed())
    return 0


if __name__ == "__main__":
    sys.exit(main())
