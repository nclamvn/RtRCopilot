"""Reference-only packets and explicit bounded memory; no copied SOT facts."""

from alembic import op

revision = "0017_context_memory"
down_revision = "0016_document_render_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE context_packets (
      packet_id uuid PRIMARY KEY,
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      scope_kind text NOT NULL CHECK (scope_kind IN ('private','project','department')),
      scope_key uuid NULL,
      use_class text NOT NULL CHECK (use_class IN ('sales','proposal','attestation')),
      ontology_digest char(64) NOT NULL,
      query_digest char(64) NOT NULL,
      source_refs jsonb NOT NULL CHECK (jsonb_typeof(source_refs)='array'),
      entity_ids text[] NOT NULL,
      memory_refs jsonb NOT NULL CHECK (jsonb_typeof(memory_refs)='array'),
      gap_codes text[] NOT NULL DEFAULT '{}',
      selection_truncated boolean NOT NULL DEFAULT false,
      max_bytes integer NOT NULL CHECK (max_bytes BETWEEN 1024 AND 65536),
      max_estimated_tokens integer NOT NULL CHECK (max_estimated_tokens BETWEEN 256 AND 16384),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((scope_kind='private' AND scope_key IS NULL)
        OR (scope_kind<>'private' AND scope_key IS NOT NULL)),
      CHECK (jsonb_array_length(source_refs)<=20 AND cardinality(entity_ids)<=10
        AND jsonb_array_length(memory_refs)<=20)
    );
    CREATE INDEX ix_context_packets_owner ON context_packets(owner_subject_id,created_at DESC);
    CREATE TABLE memory_entries (
      memory_id uuid PRIMARY KEY,
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      scope_kind text NOT NULL CHECK (scope_kind IN ('private','project','department')),
      scope_key uuid NULL,
      kind text NOT NULL CHECK (kind IN ('preference','task_note','inference')),
      note_text text NULL CHECK (octet_length(note_text)<=8000),
      source_refs jsonb NOT NULL CHECK (jsonb_typeof(source_refs)='array'
        AND jsonb_array_length(source_refs)<=20),
      use_class text NOT NULL CHECK (use_class IN ('sales','proposal','attestation')),
      revision integer NOT NULL DEFAULT 1 CHECK (revision>0),
      lifecycle text NOT NULL DEFAULT 'active' CHECK (lifecycle IN ('active','deleted')),
      expires_at timestamptz NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      deleted_at timestamptz NULL,
      CHECK ((scope_kind='private' AND scope_key IS NULL)
        OR (scope_kind<>'private' AND scope_key IS NOT NULL)),
      CHECK ((lifecycle='active' AND note_text IS NOT NULL)
        OR (lifecycle='deleted' AND note_text IS NULL)),
      CHECK (expires_at>created_at AND expires_at<=created_at+interval '30 days')
    );
    CREATE INDEX ix_memory_scope ON memory_entries(scope_kind,scope_key,owner_subject_id,updated_at)
      WHERE lifecycle='active';
    GRANT SELECT,INSERT ON context_packets TO rtr_app;
    GRANT SELECT,INSERT,UPDATE ON memory_entries TO rtr_app;
    REVOKE UPDATE,DELETE,TRUNCATE ON context_packets FROM rtr_app;
    REVOKE DELETE,TRUNCATE ON memory_entries FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE memory_entries; DROP TABLE context_packets;")
