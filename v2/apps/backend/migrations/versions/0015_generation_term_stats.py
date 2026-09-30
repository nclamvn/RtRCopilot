"""Add immutable per-generation lexical term frequencies for corpus-aware IDF."""

from alembic import op

revision = "0015_generation_term_stats"
down_revision = "0014_document_outbox_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE search_generation_term_stats (
      generation_id uuid NOT NULL
        REFERENCES search_generations(generation_id) ON DELETE CASCADE,
      term text NOT NULL CHECK (term <> ''),
      chunk_frequency integer NOT NULL CHECK (chunk_frequency > 0),
      PRIMARY KEY (generation_id,term)
    );
    CREATE INDEX ix_search_generation_term_stats_lookup
      ON search_generation_term_stats(term,generation_id);

    INSERT INTO search_generation_term_stats(
      generation_id,term,chunk_frequency
    )
    SELECT c.generation_id,lexeme.term,count(*)::integer
    FROM chunks c
    CROSS JOIN LATERAL unnest(tsvector_to_array(c.lexical)) AS lexeme(term)
    WHERE c.lifecycle='active'
    GROUP BY c.generation_id,lexeme.term;

    GRANT SELECT,INSERT ON search_generation_term_stats TO rtr_app;
    REVOKE UPDATE,DELETE,TRUNCATE ON search_generation_term_stats FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_generation_term_stats")
