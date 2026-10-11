"""Bound render ownership and fence obsolete attempts without a new runtime."""

from alembic import op

revision = "0016_document_render_lease"
down_revision = "0015_generation_term_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE render_jobs
      ADD COLUMN attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
      ADD COLUMN max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 20),
      ADD COLUMN lease_token uuid NULL,
      ADD COLUMN lease_expires_at timestamptz NULL;
    CREATE INDEX ix_render_jobs_recovery ON render_jobs(state,lease_expires_at,created_at)
      WHERE state IN ('pending','binding','rendering','validating');
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX ix_render_jobs_recovery;
    ALTER TABLE render_jobs DROP COLUMN lease_expires_at,DROP COLUMN lease_token,
      DROP COLUMN max_attempts,DROP COLUMN attempt;
    """)
