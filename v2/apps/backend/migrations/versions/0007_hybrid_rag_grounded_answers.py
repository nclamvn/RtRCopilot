"""Add policy-filtered hybrid retrieval and grounded answer storage."""

from alembic import op

revision = "0007_hybrid_rag_grounded_answers"
down_revision = "0006_sot_publish_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE search_generations (
      generation_id uuid PRIMARY KEY,
      source_key text NOT NULL,
      source_revision bigint NOT NULL CHECK (source_revision > 0),
      publish_run_id uuid NOT NULL REFERENCES sot_publish_runs(run_id),
      package_id uuid NOT NULL REFERENCES sot_packages(package_id),
      index_fingerprint char(64) NOT NULL CHECK (index_fingerprint ~ '^[0-9a-f]{64}$'),
      embedding_model text NOT NULL,
      embedding_version text NOT NULL,
      embedding_dimension integer NOT NULL CHECK (embedding_dimension=64),
      chunker_version text NOT NULL,
      lifecycle text NOT NULL CHECK (lifecycle IN
        ('building','validated','active','failed','superseded')),
      chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
      document_count integer NOT NULL DEFAULT 0 CHECK (document_count >= 0),
      started_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz NULL,
      failure_code text NULL,
      failure_fingerprint char(64) NULL,
      UNIQUE(source_key, source_revision, index_fingerprint)
    );
    CREATE INDEX ix_search_generation_source
      ON search_generations(source_key,source_revision DESC);

    CREATE TABLE active_search_generations (
      source_key text PRIMARY KEY,
      generation_id uuid NOT NULL UNIQUE REFERENCES search_generations(generation_id),
      source_revision bigint NOT NULL,
      index_fingerprint char(64) NOT NULL,
      activated_at timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE chunks (
      chunk_id uuid PRIMARY KEY,
      chunk_key text NOT NULL UNIQUE,
      generation_id uuid NOT NULL REFERENCES search_generations(generation_id),
      package_id uuid NOT NULL REFERENCES sot_packages(package_id),
      record_id uuid NOT NULL REFERENCES records(record_id),
      record_version_id uuid NOT NULL REFERENCES record_versions(version_id),
      evidence_span_id uuid NULL REFERENCES evidence_spans(span_id),
      record_key text NOT NULL,
      evidence_key text NULL,
      source_key text NOT NULL,
      source_revision bigint NOT NULL,
      source_zone text NOT NULL CHECK (source_zone='sot'),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      department_id uuid NULL,
      project_id uuid NULL,
      provenance_level text NOT NULL CHECK (provenance_level IN
        ('verified_primary','verified_secondary','approved_internal','claim')),
      verification_state text NOT NULL CHECK (verification_state IN
        ('verified','approved','claim')),
      freshness_state text NOT NULL CHECK (freshness_state IN
        ('current','stale','expired','unknown')),
      display_text text NOT NULL,
      normalized_text text NOT NULL,
      text_sha256 char(64) NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
      locator jsonb NOT NULL,
      source_label text NOT NULL,
      record_checksum char(64) NOT NULL,
      evidence_checksum char(64) NULL,
      ordinal integer NOT NULL CHECK (ordinal > 0),
      chunking_fingerprint char(64) NOT NULL,
      lexical tsvector GENERATED ALWAYS AS
        (to_tsvector('simple', normalized_text)) STORED,
      embedding vector(64) NOT NULL,
      lifecycle text NOT NULL CHECK (lifecycle IN
        ('building','active','superseded','failed')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(generation_id,record_version_id,evidence_span_id,ordinal)
    );
    CREATE INDEX ix_chunks_lexical ON chunks USING gin(lexical);
    CREATE INDEX ix_chunks_generation_active
      ON chunks(generation_id,chunk_key) WHERE lifecycle='active';
    CREATE INDEX ix_chunks_security
      ON chunks(generation_id,classification,department_id,project_id);
    CREATE INDEX ix_chunks_embedding
      ON chunks USING hnsw (embedding vector_cosine_ops);

    CREATE TABLE index_jobs (
      job_id uuid PRIMARY KEY,
      outbox_id uuid NOT NULL UNIQUE REFERENCES sot_reindex_outbox(outbox_id),
      generation_id uuid NOT NULL UNIQUE REFERENCES search_generations(generation_id),
      source_key text NOT NULL,
      source_revision bigint NOT NULL,
      publish_run_id uuid NOT NULL REFERENCES sot_publish_runs(run_id),
      status text NOT NULL CHECK (status IN
        ('pending','leased','running','retry_wait','succeeded','failed')),
      attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
      max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
      lease_owner text NULL,
      lease_expires_at timestamptz NULL,
      heartbeat_at timestamptz NULL,
      next_attempt_at timestamptz NULL,
      pipeline_version text NOT NULL,
      model_version text NOT NULL,
      progress jsonb NOT NULL DEFAULT '{}',
      request_id text NOT NULL,
      failure_code text NULL,
      failure_fingerprint char(64) NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz NULL
    );
    CREATE INDEX ix_index_jobs_claim
      ON index_jobs(status,next_attempt_at,lease_expires_at);

    CREATE TABLE conversations (
      conversation_id uuid PRIMARY KEY,
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      lifecycle text NOT NULL DEFAULT 'active' CHECK (lifecycle IN
        ('active','archived','deleted')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_conversations_owner
      ON conversations(owner_subject_id,updated_at DESC);

    CREATE TABLE messages (
      message_id uuid PRIMARY KEY,
      conversation_id uuid NOT NULL REFERENCES conversations(conversation_id),
      role text NOT NULL CHECK (role IN ('user','assistant')),
      sanitized_content text NOT NULL,
      content_sha256 char(64) NOT NULL,
      answer_state text NULL CHECK (answer_state IS NULL OR answer_state IN
        ('grounded','honest_null','failed')),
      provider text NULL,
      model text NULL,
      request_id text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_messages_conversation
      ON messages(conversation_id,created_at,message_id);

    CREATE TABLE answer_runs (
      answer_run_id uuid PRIMARY KEY,
      conversation_id uuid NULL REFERENCES conversations(conversation_id),
      question_message_id uuid NULL REFERENCES messages(message_id),
      answer_message_id uuid NULL REFERENCES messages(message_id),
      requester_id uuid NOT NULL REFERENCES subjects(user_id),
      request_id text NOT NULL,
      query_fingerprint char(64) NOT NULL,
      authorized_scope_fingerprint char(64) NOT NULL,
      retrieval_config jsonb NOT NULL,
      selected_chunk_ids uuid[] NOT NULL DEFAULT '{}',
      selected_scores jsonb NOT NULL DEFAULT '[]',
      provider_decision text NOT NULL,
      state text NOT NULL CHECK (state IN
        ('running','grounded','honest_null','failed')),
      reason_code text NULL,
      input_tokens integer NOT NULL DEFAULT 0,
      output_tokens integer NOT NULL DEFAULT 0,
      latency_ms integer NOT NULL DEFAULT 0,
      generation_ids uuid[] NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz NULL
    );
    CREATE INDEX ix_answer_runs_requester
      ON answer_runs(requester_id,created_at DESC);
    CREATE INDEX ix_answer_runs_request ON answer_runs(request_id);

    CREATE TABLE answer_citations (
      citation_id uuid PRIMARY KEY,
      answer_run_id uuid NOT NULL REFERENCES answer_runs(answer_run_id),
      marker text NOT NULL,
      chunk_id uuid NOT NULL REFERENCES chunks(chunk_id),
      record_key text NOT NULL,
      record_version_id uuid NOT NULL REFERENCES record_versions(version_id),
      evidence_key text NULL,
      record_checksum char(64) NOT NULL,
      evidence_checksum char(64) NULL,
      source_key text NOT NULL,
      source_revision bigint NOT NULL,
      provenance_level text NOT NULL,
      verification_state text NOT NULL,
      freshness_state text NOT NULL,
      source_label text NOT NULL,
      locator jsonb NOT NULL,
      redacted boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(answer_run_id,marker),
      UNIQUE(answer_run_id,chunk_id)
    );

    CREATE TABLE gaps (
      gap_id uuid PRIMARY KEY,
      question_fingerprint char(64) NOT NULL,
      sanitized_question text NOT NULL,
      sanitized_summary text NOT NULL,
      reason_category text NOT NULL CHECK (reason_category IN
        ('no_evidence','denied_or_unavailable','insufficient_confidence',
         'stale_only','grounding_failed')),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      requester_id uuid NOT NULL REFERENCES subjects(user_id),
      owner_subject_id uuid NULL REFERENCES subjects(user_id),
      routing_key text NOT NULL,
      occurrence_count integer NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
      lifecycle text NOT NULL DEFAULT 'open' CHECK (lifecycle IN
        ('open','triaged','resolved','dismissed')),
      answer_run_id uuid NOT NULL REFERENCES answer_runs(answer_run_id),
      resolving_record_id uuid NULL REFERENCES records(record_id),
      first_seen_at timestamptz NOT NULL DEFAULT now(),
      last_seen_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(question_fingerprint,requester_id,classification)
    );
    CREATE INDEX ix_gaps_route ON gaps(lifecycle,routing_key,last_seen_at DESC);

    CREATE FUNCTION has_effective_acl_deny(
      p_resource_id uuid, p_subject_id uuid, p_action text
    ) RETURNS boolean LANGUAGE sql STABLE AS $$
      SELECT EXISTS(
        SELECT 1 FROM acl_entries a
        WHERE a.resource_id=p_resource_id AND a.action=p_action
          AND a.effect='deny' AND a.valid_from<=now()
          AND (a.expires_at IS NULL OR a.expires_at>now())
          AND (
            (a.principal_type='user' AND a.principal_id=p_subject_id)
            OR (a.principal_type='group' AND EXISTS(
              SELECT 1 FROM subject_groups sg
              WHERE sg.subject_id=p_subject_id AND sg.group_id=a.principal_id
                AND sg.valid_from<=now()
                AND (sg.expires_at IS NULL OR sg.expires_at>now())
            ))
            OR (a.principal_type='role' AND EXISTS(
              SELECT 1 FROM subject_roles sr
              WHERE sr.subject_id=p_subject_id AND sr.role_id=a.principal_id
                AND sr.valid_from<=now()
                AND (sr.expires_at IS NULL OR sr.expires_at>now())
            ))
            OR (a.principal_type IN ('department','project') AND EXISTS(
              SELECT 1 FROM subject_scopes ss
              WHERE ss.subject_id=p_subject_id
                AND ss.scope_type=a.principal_type
                AND ss.scope_key=a.principal_id::text
                AND ss.valid_from<=now()
                AND (ss.expires_at IS NULL OR ss.expires_at>now())
            ))
          )
      )
    $$;
    REVOKE ALL ON FUNCTION has_effective_acl_deny(uuid,uuid,text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION has_effective_acl_deny(uuid,uuid,text) TO rtr_app;

    CREATE OR REPLACE FUNCTION prevent_rag_canonical_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'canonical retrieval content is immutable';
    END $$;
    CREATE TRIGGER chunks_immutable BEFORE UPDATE ON chunks
      FOR EACH ROW EXECUTE FUNCTION prevent_rag_canonical_mutation();
    CREATE TRIGGER citations_immutable BEFORE UPDATE ON answer_citations
      FOR EACH ROW EXECUTE FUNCTION prevent_rag_canonical_mutation();
    CREATE TRIGGER messages_immutable BEFORE UPDATE ON messages
      FOR EACH ROW EXECUTE FUNCTION prevent_rag_canonical_mutation();

    GRANT SELECT,INSERT,UPDATE ON
      search_generations,active_search_generations,chunks,index_jobs,
      conversations,messages,answer_runs,answer_citations,gaps TO rtr_app;
    REVOKE DELETE ON chunks,answer_citations,messages,search_generations,
      active_search_generations,index_jobs,answer_runs FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER messages_immutable ON messages;
    DROP TRIGGER citations_immutable ON answer_citations;
    DROP TRIGGER chunks_immutable ON chunks;
    DROP FUNCTION prevent_rag_canonical_mutation();
    DROP FUNCTION has_effective_acl_deny(uuid,uuid,text);
    DROP TABLE gaps;
    DROP TABLE answer_citations;
    DROP TABLE answer_runs;
    DROP TABLE messages;
    DROP TABLE conversations;
    DROP TABLE index_jobs;
    DROP TABLE chunks;
    DROP TABLE active_search_generations;
    DROP TABLE search_generations;
    """)
