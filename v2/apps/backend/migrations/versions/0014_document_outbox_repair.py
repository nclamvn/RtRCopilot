"""Repair the Document OS publication outbox on drifted databases.

The outbox is part of the canonical 0008 schema. A small number of long-lived
local databases were stamped after 0008 had run without the relation, so a
revision-only readiness check could report healthy while every render failed.
This forward-only repair is safe for both drifted and clean installations.
"""

from alembic import op

revision = "0014_document_outbox_repair"
down_revision = "0013_real_embedding_dim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS document_publication_outbox (
      outbox_id uuid PRIMARY KEY,
      render_job_id uuid NOT NULL UNIQUE REFERENCES render_jobs(render_job_id),
      state text NOT NULL DEFAULT 'pending' CHECK (state IN
        ('pending','preparing','finalized','failed','cancelled')),
      payload jsonb NOT NULL DEFAULT '{}',
      attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
      error_code text NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      finalized_at timestamptz NULL
    );
    CREATE INDEX IF NOT EXISTS ix_document_publication_outbox_state
      ON document_publication_outbox(state,updated_at);
    GRANT SELECT,INSERT,UPDATE ON document_publication_outbox TO rtr_app;
    REVOKE DELETE ON document_publication_outbox FROM rtr_app;
    """)


def downgrade() -> None:
    # The relation belongs to the canonical 0008 schema. Downgrading the
    # repair only moves the revision marker; it must not destroy live outbox
    # state or re-introduce the drift.
    op.execute("SELECT 1")
