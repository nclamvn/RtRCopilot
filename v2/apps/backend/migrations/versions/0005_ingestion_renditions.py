"""Add durable ingestion, delivery and rendition provenance."""

from alembic import op

revision = "0005_ingestion_renditions"
down_revision = "0004_append_only_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE upload_sessions (
      upload_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      parent_resource_id uuid NOT NULL REFERENCES resources(resource_id),
      document_id uuid NULL REFERENCES documents(document_id),
      object_id uuid NOT NULL UNIQUE REFERENCES object_blobs(object_id),
      version_id uuid NULL UNIQUE REFERENCES document_versions(version_id),
      validation_job_id uuid NULL,
      requested_by uuid NOT NULL REFERENCES subjects(user_id),
      request_id text NOT NULL,
      state text NOT NULL CHECK (state IN (
        'receiving','quarantined','validating','scanning','accepted',
        'rejected','failed'
      )),
      progress smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
      logical_name text NOT NULL,
      original_filename text NOT NULL,
      declared_mime text NULL,
      detected_mime text NULL,
      sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
      byte_size bigint NOT NULL CHECK (byte_size >= 0),
      error_code text NULL,
      error_fingerprint char(64) NULL,
      retryable boolean NOT NULL DEFAULT false,
      failed_stage text NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz NULL
    );
    CREATE INDEX ix_upload_parent_actor
      ON upload_sessions(parent_resource_id, requested_by, created_at);
    CREATE INDEX ix_upload_state_age ON upload_sessions(state, created_at);

    CREATE TABLE ingestion_jobs (
      job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      upload_id uuid NULL REFERENCES upload_sessions(upload_id),
      version_id uuid NULL REFERENCES document_versions(version_id),
      resource_id uuid NOT NULL REFERENCES resources(resource_id),
      job_type text NOT NULL CHECK (job_type IN
        ('validate','extract','ocr','transcribe','render')),
      output_kind text NULL,
      pipeline_version text NOT NULL,
      pipeline_fingerprint char(64) NOT NULL,
      idempotency_key text UNIQUE NOT NULL,
      status text NOT NULL CHECK (status IN (
        'pending','leased','running','retry_wait','succeeded','failed',
        'quarantined','cancelled'
      )),
      attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
      max_attempts integer NOT NULL CHECK (max_attempts BETWEEN 1 AND 20),
      lease_owner text NULL,
      lease_expires_at timestamptz NULL,
      heartbeat_at timestamptz NULL,
      next_attempt_at timestamptz NULL,
      requested_by uuid NOT NULL REFERENCES subjects(user_id),
      request_id text NOT NULL,
      input_sha256 char(64) NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
      progress smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
      error_code text NULL,
      error_fingerprint char(64) NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      started_at timestamptz NULL,
      finished_at timestamptz NULL,
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK (upload_id IS NOT NULL OR version_id IS NOT NULL)
    );
    ALTER TABLE upload_sessions ADD CONSTRAINT fk_upload_validation_job
      FOREIGN KEY (validation_job_id) REFERENCES ingestion_jobs(job_id)
      DEFERRABLE INITIALLY DEFERRED;
    CREATE INDEX ix_ingestion_claim
      ON ingestion_jobs(status, next_attempt_at, lease_expires_at, created_at);
    CREATE INDEX ix_ingestion_version ON ingestion_jobs(version_id, job_type);

    CREATE TABLE ingestion_outbox (
      outbox_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      job_id uuid NOT NULL UNIQUE REFERENCES ingestion_jobs(job_id),
      payload jsonb NOT NULL,
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','dispatching','dispatched')),
      attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
      available_at timestamptz NOT NULL DEFAULT now(),
      dispatched_at timestamptz NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_outbox_dispatch
      ON ingestion_outbox(status, available_at, created_at);

    ALTER TABLE document_versions
      ADD COLUMN detected_mime text NULL,
      ADD COLUMN viewer_state text NOT NULL DEFAULT 'processing'
        CHECK (viewer_state IN (
          'processing','ready','partial','processing_failed','quarantined'
        ));

    ALTER TABLE renditions
      ADD COLUMN pipeline_fingerprint char(64) NULL,
      ADD COLUMN source_sha256 char(64) NULL,
      ADD COLUMN manifest_object_id uuid NULL REFERENCES object_blobs(object_id),
      ADD COLUMN quality_state text NULL
        CHECK (quality_state IN ('complete','partial','low_confidence')),
      ADD COLUMN quality_summary jsonb NOT NULL DEFAULT '{}',
      ADD COLUMN provenance jsonb NOT NULL DEFAULT '{}',
      ADD COLUMN job_id uuid NULL REFERENCES ingestion_jobs(job_id),
      ADD COLUMN attempt integer NULL,
      ADD COLUMN upstream_rendition_ids uuid[] NOT NULL DEFAULT '{}';
    CREATE UNIQUE INDEX uq_rendition_pipeline
      ON renditions(version_id, kind, pipeline_fingerprint)
      WHERE pipeline_fingerprint IS NOT NULL;
    """ )


def downgrade() -> None:
    op.execute("""
    DROP INDEX uq_rendition_pipeline;
    ALTER TABLE renditions
      DROP COLUMN upstream_rendition_ids,
      DROP COLUMN attempt,
      DROP COLUMN job_id,
      DROP COLUMN provenance,
      DROP COLUMN quality_summary,
      DROP COLUMN quality_state,
      DROP COLUMN manifest_object_id,
      DROP COLUMN source_sha256,
      DROP COLUMN pipeline_fingerprint;
    ALTER TABLE document_versions
      DROP COLUMN viewer_state,
      DROP COLUMN detected_mime;
    DROP TABLE ingestion_outbox;
    ALTER TABLE upload_sessions DROP CONSTRAINT fk_upload_validation_job;
    DROP TABLE ingestion_jobs;
    DROP TABLE upload_sessions;
    """)
