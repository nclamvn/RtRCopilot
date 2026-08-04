"""Add immutable private-context chunks and polymorphic citations."""

from alembic import op

revision = "0010_file_retrieval"
down_revision = "0009_governance_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE file_chunks (
      file_chunk_id uuid PRIMARY KEY,
      document_version_id uuid NOT NULL REFERENCES document_versions(version_id),
      rendition_id uuid NOT NULL REFERENCES renditions(rendition_id),
      chunk_key text NOT NULL UNIQUE,
      display_text text NOT NULL,
      normalized_text text NOT NULL,
      text_sha256 char(64) NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
      source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
      rendition_sha256 char(64) NOT NULL CHECK (rendition_sha256 ~ '^[0-9a-f]{64}$'),
      rendition_kind text NOT NULL,
      locator jsonb NOT NULL,
      ordinal integer NOT NULL CHECK (ordinal > 0),
      lexical tsvector GENERATED ALWAYS AS
        (to_tsvector('simple', normalized_text)) STORED,
      embedding vector(64) NOT NULL,
      lifecycle text NOT NULL DEFAULT 'active'
        CHECK (lifecycle IN ('active','superseded','failed')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(document_version_id,rendition_id,ordinal)
    );
    CREATE INDEX ix_file_chunks_version_active
      ON file_chunks(document_version_id,chunk_key) WHERE lifecycle='active';
    CREATE INDEX ix_file_chunks_lexical ON file_chunks USING gin(lexical);
    CREATE INDEX ix_file_chunks_embedding
      ON file_chunks USING hnsw (embedding vector_cosine_ops);

    ALTER TABLE answer_citations
      ALTER COLUMN chunk_id DROP NOT NULL,
      ALTER COLUMN record_version_id DROP NOT NULL,
      ADD COLUMN file_chunk_id uuid NULL REFERENCES file_chunks(file_chunk_id),
      ADD COLUMN document_version_id uuid NULL
        REFERENCES document_versions(version_id),
      ADD COLUMN zone_label text NOT NULL DEFAULT 'sot'
        CHECK (zone_label IN ('sot','private')),
      ADD CONSTRAINT ck_answer_citation_source_xor CHECK (
        (chunk_id IS NOT NULL AND file_chunk_id IS NULL
          AND record_version_id IS NOT NULL AND document_version_id IS NULL
          AND zone_label='sot')
        OR
        (chunk_id IS NULL AND file_chunk_id IS NOT NULL
          AND record_version_id IS NULL AND document_version_id IS NOT NULL
          AND zone_label='private')
      );
    ALTER TABLE answer_citations
      DROP CONSTRAINT answer_citations_answer_run_id_chunk_id_key;
    CREATE UNIQUE INDEX uq_answer_citations_sot_chunk
      ON answer_citations(answer_run_id,chunk_id) WHERE chunk_id IS NOT NULL;
    CREATE UNIQUE INDEX uq_answer_citations_file_chunk
      ON answer_citations(answer_run_id,file_chunk_id)
      WHERE file_chunk_id IS NOT NULL;
    GRANT SELECT,INSERT ON file_chunks TO rtr_app;
    REVOKE UPDATE,DELETE ON file_chunks FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX uq_answer_citations_file_chunk;
    DROP INDEX uq_answer_citations_sot_chunk;
    ALTER TABLE answer_citations DROP CONSTRAINT ck_answer_citation_source_xor;
    DELETE FROM answer_citations WHERE file_chunk_id IS NOT NULL;
    ALTER TABLE answer_citations
      DROP COLUMN zone_label,
      DROP COLUMN document_version_id,
      DROP COLUMN file_chunk_id,
      ALTER COLUMN record_version_id SET NOT NULL,
      ALTER COLUMN chunk_id SET NOT NULL,
      ADD CONSTRAINT answer_citations_answer_run_id_chunk_id_key
        UNIQUE(answer_run_id,chunk_id);
    DROP TABLE file_chunks;
    """)
