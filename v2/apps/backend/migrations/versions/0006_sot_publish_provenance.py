"""Add the canonical SOT publish, provenance and reindex boundary."""

from alembic import op

revision = "0006_sot_publish_provenance"
down_revision = "0005_ingestion_renditions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE resources DROP CONSTRAINT resources_resource_type_check;
    ALTER TABLE resources ADD CONSTRAINT resources_resource_type_check
      CHECK (resource_type IN (
        'source','document','document_version','object','rendition','record'
      ));

    CREATE TABLE sot_packages (
      package_id uuid PRIMARY KEY,
      source_key text NOT NULL CHECK (source_key ~ '^[a-z0-9][a-z0-9._-]{1,127}$'),
      revision bigint NOT NULL CHECK (revision > 0),
      schema_version text NOT NULL,
      trust_zone text NOT NULL CHECK (trust_zone='sot'),
      manifest_sha256 char(64) NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
      payload_sha256 char(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
      producer text NOT NULL,
      generated_at timestamptz NOT NULL,
      ingested_at timestamptz NOT NULL DEFAULT now(),
      staging_name text NOT NULL,
      lifecycle text NOT NULL CHECK (lifecycle IN (
        'staged','validating','validated','publishing','active','rejected','superseded'
      )),
      validation_summary jsonb NOT NULL DEFAULT '{}',
      rejection_code text NULL,
      record_count integer NOT NULL DEFAULT 0 CHECK (record_count >= 0),
      evidence_count integer NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
      source_count integer NOT NULL DEFAULT 0 CHECK (source_count >= 0),
      UNIQUE(source_key, revision),
      UNIQUE(manifest_sha256, payload_sha256)
    );
    CREATE INDEX ix_sot_package_active
      ON sot_packages(source_key, revision DESC) WHERE lifecycle='active';

    CREATE TABLE records (
      record_id uuid PRIMARY KEY REFERENCES resources(resource_id),
      record_key text NOT NULL UNIQUE CHECK (record_key <> ''),
      source_key text NOT NULL,
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      department_id uuid NULL,
      project_id uuid NULL,
      lifecycle text NOT NULL DEFAULT 'staged' CHECK (lifecycle IN
        ('staged','active','superseded','deleted')),
      current_version_id uuid NULL,
      retention_until timestamptz NULL,
      legal_hold boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_records_active_key
      ON records(source_key, record_key) WHERE lifecycle='active';

    CREATE TABLE record_versions (
      version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      record_id uuid NOT NULL REFERENCES records(record_id),
      package_id uuid NOT NULL REFERENCES sot_packages(package_id),
      package_revision bigint NOT NULL,
      version_ordinal integer NOT NULL CHECK (version_ordinal > 0),
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      department_id uuid NULL,
      project_id uuid NULL,
      value_payload jsonb NOT NULL,
      searchable_text text NOT NULL,
      provenance_level text NOT NULL CHECK (provenance_level IN
        ('verified_primary','verified_secondary','approved_internal','claim')),
      confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
      verification_state text NOT NULL CHECK (verification_state IN
        ('verified','approved','claim')),
      fact_state text NOT NULL CHECK (fact_state IN
        ('approved','verified','claim')),
      effective_from timestamptz NOT NULL,
      effective_to timestamptz NULL,
      freshness_policy jsonb NOT NULL,
      freshness_due_at timestamptz NULL,
      freshness_state text NOT NULL CHECK (freshness_state IN
        ('current','stale','expired','unknown')),
      evidence_refs text[] NOT NULL DEFAULT '{}',
      source_refs text[] NOT NULL,
      acl_projection jsonb NOT NULL,
      content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
      supersedes_version_id uuid NULL REFERENCES record_versions(version_id),
      lifecycle text NOT NULL DEFAULT 'staged' CHECK (lifecycle IN
        ('staged','active','superseded','rejected')),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK (effective_to IS NULL OR effective_to > effective_from),
      UNIQUE(record_id, version_ordinal),
      UNIQUE(package_id, record_id)
    );
    ALTER TABLE records ADD CONSTRAINT fk_record_current_version
      FOREIGN KEY (current_version_id) REFERENCES record_versions(version_id)
      DEFERRABLE INITIALLY DEFERRED;
    CREATE INDEX ix_record_versions_active
      ON record_versions(record_id, package_revision DESC) WHERE lifecycle='active';
    CREATE INDEX ix_record_versions_freshness
      ON record_versions(freshness_state, freshness_due_at) WHERE lifecycle='active';
    CREATE INDEX ix_record_versions_provenance
      ON record_versions(provenance_level, verification_state);

    CREATE TABLE evidence_spans (
      span_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      evidence_key text NOT NULL,
      record_version_id uuid NOT NULL REFERENCES record_versions(version_id),
      package_id uuid NOT NULL REFERENCES sot_packages(package_id),
      source_ref text NOT NULL,
      source_document_id uuid NULL REFERENCES documents(document_id),
      source_version_id uuid NULL REFERENCES document_versions(version_id),
      source_blob_sha256 char(64) NULL,
      locator jsonb NOT NULL,
      quoted_text text NOT NULL,
      normalized_text text NOT NULL,
      evidence_sha256 char(64) NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
      source_label text NOT NULL,
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      lifecycle text NOT NULL DEFAULT 'staged' CHECK (lifecycle IN
        ('staged','active','superseded','rejected')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(package_id, evidence_key)
    );
    CREATE INDEX ix_evidence_active_version
      ON evidence_spans(record_version_id) WHERE lifecycle='active';
    CREATE INDEX ix_evidence_source ON evidence_spans(source_ref, evidence_sha256);

    CREATE TABLE sot_publish_runs (
      run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      package_id uuid NOT NULL UNIQUE REFERENCES sot_packages(package_id),
      source_key text NOT NULL,
      revision bigint NOT NULL,
      actor_user_id uuid NOT NULL REFERENCES subjects(user_id),
      request_id text NOT NULL,
      state text NOT NULL CHECK (state IN
        ('staged','validating','validated','publishing','active','rejected','failed')),
      validation_report jsonb NOT NULL DEFAULT '{}',
      started_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz NULL,
      candidate_checksum char(64) NOT NULL,
      previous_active_revision bigint NULL,
      previous_active_checksum char(64) NULL,
      record_count integer NOT NULL DEFAULT 0,
      evidence_count integer NOT NULL DEFAULT 0,
      deterministic_checksum char(64) NOT NULL,
      failure_code text NULL,
      failure_fingerprint char(64) NULL,
      audit_event_id uuid NULL REFERENCES audit_events(event_id)
    );
    CREATE INDEX ix_sot_runs_status ON sot_publish_runs(state, started_at);
    CREATE INDEX ix_sot_runs_request ON sot_publish_runs(request_id);

    CREATE TABLE sot_active_revisions (
      source_key text PRIMARY KEY,
      package_id uuid NOT NULL UNIQUE REFERENCES sot_packages(package_id),
      revision bigint NOT NULL,
      payload_sha256 char(64) NOT NULL,
      activated_run_id uuid NOT NULL UNIQUE REFERENCES sot_publish_runs(run_id),
      activated_at timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE sot_reindex_outbox (
      outbox_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      run_id uuid NOT NULL UNIQUE REFERENCES sot_publish_runs(run_id),
      source_key text NOT NULL,
      revision bigint NOT NULL,
      payload jsonb NOT NULL,
      status text NOT NULL DEFAULT 'pending' CHECK (status IN
        ('pending','dispatching','dispatched')),
      created_at timestamptz NOT NULL DEFAULT now(),
      dispatched_at timestamptz NULL
    );
    CREATE INDEX ix_sot_reindex_pending
      ON sot_reindex_outbox(status, created_at);

    CREATE OR REPLACE FUNCTION prevent_sot_content_update()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (to_jsonb(NEW)-'lifecycle') IS DISTINCT FROM
         (to_jsonb(OLD)-'lifecycle') THEN
        RAISE EXCEPTION 'published SOT content is immutable';
      END IF;
      IF NEW.lifecycle IS DISTINCT FROM OLD.lifecycle AND NOT (
        (OLD.lifecycle='staged' AND NEW.lifecycle IN ('active','rejected')) OR
        (OLD.lifecycle='active' AND NEW.lifecycle='superseded')
      ) THEN
        RAISE EXCEPTION 'invalid SOT lifecycle transition';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER record_version_content_immutable
      BEFORE UPDATE ON record_versions FOR EACH ROW
      EXECUTE FUNCTION prevent_sot_content_update();
    CREATE TRIGGER evidence_span_content_immutable
      BEFORE UPDATE ON evidence_spans FOR EACH ROW
      EXECUTE FUNCTION prevent_sot_content_update();

    GRANT SELECT, INSERT, UPDATE ON
      sot_packages,records,record_versions,evidence_spans,sot_publish_runs,
      sot_active_revisions,sot_reindex_outbox TO rtr_app;
    REVOKE DELETE ON
      sot_packages,records,record_versions,evidence_spans,sot_publish_runs,
      sot_active_revisions,sot_reindex_outbox FROM rtr_app;
    """ )


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER evidence_span_content_immutable ON evidence_spans;
    DROP TRIGGER record_version_content_immutable ON record_versions;
    DROP FUNCTION prevent_sot_content_update();
    DROP TABLE sot_reindex_outbox;
    DROP TABLE sot_active_revisions;
    DROP TABLE sot_publish_runs;
    DROP TABLE evidence_spans;
    ALTER TABLE records DROP CONSTRAINT fk_record_current_version;
    DROP TABLE record_versions;
    DROP TABLE records;
    DROP TABLE sot_packages;
    DELETE FROM acl_entries
      WHERE resource_id IN (
        SELECT resource_id FROM resources WHERE resource_type='record'
      );
    DELETE FROM resources WHERE resource_type='record';
    ALTER TABLE resources DROP CONSTRAINT resources_resource_type_check;
    ALTER TABLE resources ADD CONSTRAINT resources_resource_type_check
      CHECK (resource_type IN
        ('source','document','document_version','object','rendition'));
    """)
