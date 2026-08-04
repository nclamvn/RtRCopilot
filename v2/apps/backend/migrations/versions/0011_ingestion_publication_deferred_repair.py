"""Repair publication_deferred on upload_sessions for drifted local databases.

The column belongs logically to migration 0008. Some long-lived local databases
were stamped with 0008 before that statement was present, so their revision can
be current while their physical schema is incomplete. This forward-only repair
is idempotent for both drifted databases and clean installations.
"""

from alembic import op

revision = "0011_ingestion_pub_deferred"
down_revision = "0010_file_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE upload_sessions
      ADD COLUMN IF NOT EXISTS publication_deferred boolean NOT NULL DEFAULT false;
    """)


def downgrade() -> None:
    # Do not remove the column: it is part of the canonical 0008 schema. A
    # downgrade from this repair only moves the revision marker back to 0010.
    op.execute("SELECT 1")
