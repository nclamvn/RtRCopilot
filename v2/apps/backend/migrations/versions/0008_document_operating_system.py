"""Add governed templates, deterministic render manifests and issuance."""

from alembic import op

revision = "0008_document_operating_system"
down_revision = "0007_hybrid_rag_grounded_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE resources DROP CONSTRAINT resources_resource_type_check;
    ALTER TABLE resources ADD CONSTRAINT resources_resource_type_check
      CHECK (resource_type IN (
        'source','document','document_version','object','rendition','record',
        'template','template_version'
      ));

    CREATE TABLE templates (
      template_id uuid PRIMARY KEY REFERENCES resources(resource_id),
      stable_key text NOT NULL UNIQUE CHECK (stable_key ~ '^[a-z0-9][a-z0-9._-]{1,127}$'),
      display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 200),
      description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
      category text NOT NULL CHECK (char_length(category) BETWEEN 1 AND 100),
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      document_class text NOT NULL CHECK (document_class IN ('internal','official','legal')),
      lifecycle text NOT NULL DEFAULT 'draft' CHECK (lifecycle IN
        ('draft','in_review','approved','retired')),
      current_version_id uuid NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_templates_ledger
      ON templates(lifecycle,lower(display_name),template_id);

    CREATE TABLE template_versions (
      version_id uuid PRIMARY KEY REFERENCES resources(resource_id),
      template_id uuid NOT NULL REFERENCES templates(template_id),
      version_ordinal integer NOT NULL CHECK (version_ordinal > 0),
      format text NOT NULL CHECK (format IN ('docx','xlsx','pptx','pdf')),
      source_object_id uuid NOT NULL REFERENCES object_blobs(object_id),
      source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
      field_schema jsonb NOT NULL,
      renderer_kind text NOT NULL CHECK (renderer_kind IN
        ('docx_declarative','xlsx_declarative','pptx_declarative','pdf_declarative')),
      renderer_version text NOT NULL CHECK (renderer_version ~ '^[a-z0-9._-]{1,64}$'),
      status text NOT NULL DEFAULT 'draft' CHECK (status IN
        ('draft','in_review','approved','retired')),
      created_by uuid NOT NULL REFERENCES subjects(user_id),
      approved_by uuid NULL REFERENCES subjects(user_id),
      created_at timestamptz NOT NULL DEFAULT now(),
      approved_at timestamptz NULL,
      retired_at timestamptz NULL,
      UNIQUE(template_id,version_ordinal),
      UNIQUE(template_id,source_sha256)
    );
    ALTER TABLE templates ADD CONSTRAINT fk_template_current_version
      FOREIGN KEY (current_version_id) REFERENCES template_versions(version_id)
      DEFERRABLE INITIALLY DEFERRED;
    CREATE INDEX ix_template_versions_status
      ON template_versions(template_id,status,version_ordinal DESC);

    CREATE TABLE template_bindings (
      binding_id uuid PRIMARY KEY,
      template_version_id uuid NOT NULL REFERENCES template_versions(version_id),
      field_path text NOT NULL CHECK (field_path ~ '^[a-z][a-z0-9_.]{0,127}$'),
      field_type text NOT NULL CHECK (field_type IN
        ('string','multiline','integer','decimal','boolean','date','enum','list','table')),
      source text NOT NULL CHECK (source IN ('user','locked_fact','derived')),
      required boolean NOT NULL DEFAULT false,
      rules jsonb NOT NULL DEFAULT '{}',
      record_key text NULL,
      provenance_contract jsonb NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((source='locked_fact') = (record_key IS NOT NULL)),
      UNIQUE(template_version_id,field_path)
    );

    CREATE TABLE render_jobs (
      render_job_id uuid PRIMARY KEY,
      requester_id uuid NOT NULL REFERENCES subjects(user_id),
      idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 8 AND 200),
      canonical_input_hash char(64) NOT NULL CHECK (canonical_input_hash ~ '^[0-9a-f]{64}$'),
      template_version_id uuid NOT NULL REFERENCES template_versions(version_id),
      sot_package_id uuid NULL REFERENCES sot_packages(package_id),
      sot_revision bigint NULL,
      state text NOT NULL CHECK (state IN
        ('pending','binding','rendering','validating','completed','failed','cancelled')),
      progress smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
      error_code text NULL,
      request_id text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      started_at timestamptz NULL,
      finished_at timestamptz NULL,
      UNIQUE(requester_id,idempotency_key),
      UNIQUE(requester_id,template_version_id,canonical_input_hash)
    );
    CREATE INDEX ix_render_jobs_requester
      ON render_jobs(requester_id,created_at DESC);

    ALTER TABLE upload_sessions
      ADD COLUMN publication_deferred boolean NOT NULL DEFAULT false;

    CREATE TABLE document_publication_outbox (
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
    CREATE INDEX ix_document_publication_outbox_state
      ON document_publication_outbox(state,updated_at);

    CREATE TABLE render_job_bindings (
      render_binding_id uuid PRIMARY KEY,
      render_job_id uuid NOT NULL REFERENCES render_jobs(render_job_id),
      field_path text NOT NULL,
      source text NOT NULL CHECK (source IN ('user','locked_fact','derived')),
      canonical_value jsonb NOT NULL,
      record_key text NULL,
      record_version_id uuid NULL REFERENCES record_versions(version_id),
      record_checksum char(64) NULL,
      evidence_key text NULL,
      evidence_checksum char(64) NULL,
      source_checksum char(64) NULL,
      locator jsonb NOT NULL DEFAULT '{}',
      provenance_level text NULL,
      verification_state text NULL,
      freshness_state text NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(render_job_id,field_path)
    );

    CREATE TABLE generated_files (
      generated_file_id uuid PRIMARY KEY,
      render_job_id uuid NOT NULL REFERENCES render_jobs(render_job_id),
      document_id uuid NOT NULL REFERENCES documents(document_id),
      version_id uuid NOT NULL UNIQUE REFERENCES document_versions(version_id),
      object_id uuid NOT NULL REFERENCES object_blobs(object_id),
      output_format text NOT NULL CHECK (output_format IN ('docx','xlsx','pptx','pdf')),
      ordinal integer NOT NULL CHECK (ordinal > 0),
      checksum char(64) NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
      render_manifest jsonb NOT NULL,
      lifecycle text NOT NULL DEFAULT 'draft' CHECK (lifecycle IN
        ('draft','in_review','approved','issued','revoked','rejected')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(render_job_id,ordinal),
      UNIQUE(document_id,checksum)
    );
    CREATE INDEX ix_generated_files_job ON generated_files(render_job_id,ordinal DESC);

    CREATE TABLE approvals (
      approval_id uuid PRIMARY KEY,
      generated_file_id uuid NOT NULL REFERENCES generated_files(generated_file_id),
      stage text NOT NULL CHECK (stage IN ('review','approval')),
      reviewer_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      decision text NOT NULL CHECK (decision IN ('approved','rejected')),
      checksum char(64) NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
      attestation_hash char(64) NOT NULL CHECK (attestation_hash ~ '^[0-9a-f]{64}$'),
      reason text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 2000),
      decided_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(generated_file_id,stage)
    );

    CREATE TABLE document_issuances (
      issuance_id uuid PRIMARY KEY,
      generated_file_id uuid NOT NULL UNIQUE REFERENCES generated_files(generated_file_id),
      issue_number text NOT NULL UNIQUE CHECK (issue_number ~ '^RTR-[0-9]{4}-[A-F0-9]{12}$'),
      issuer_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      issued_checksum char(64) NOT NULL CHECK (issued_checksum ~ '^[0-9a-f]{64}$'),
      issued_at timestamptz NOT NULL DEFAULT now(),
      revoked_by uuid NULL REFERENCES subjects(user_id),
      revoked_at timestamptz NULL,
      revocation_reason text NULL,
      CHECK ((revoked_at IS NULL) = (revoked_by IS NULL)),
      CHECK (revoked_at IS NULL OR char_length(revocation_reason) BETWEEN 1 AND 2000)
    );

    CREATE OR REPLACE FUNCTION prevent_document_os_canonical_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'document operating system canonical history is immutable';
    END $$;
    CREATE OR REPLACE FUNCTION guard_template_version_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR OLD.status='retired' THEN
        RAISE EXCEPTION 'approved template version is immutable';
      END IF;
      IF OLD.status='approved' AND (
        NEW.status<>'retired' OR NEW.template_id<>OLD.template_id
        OR NEW.version_ordinal<>OLD.version_ordinal OR NEW.format<>OLD.format
        OR NEW.source_object_id<>OLD.source_object_id
        OR NEW.source_sha256<>OLD.source_sha256 OR NEW.field_schema<>OLD.field_schema
        OR NEW.renderer_kind<>OLD.renderer_kind
        OR NEW.renderer_version<>OLD.renderer_version
      ) THEN
        RAISE EXCEPTION 'approved template version is immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER approved_template_version_immutable
      BEFORE UPDATE OR DELETE ON template_versions
      FOR EACH ROW WHEN (OLD.status IN ('approved','retired'))
      EXECUTE FUNCTION guard_template_version_mutation();
    CREATE TRIGGER render_bindings_immutable
      BEFORE UPDATE OR DELETE ON render_job_bindings
      FOR EACH ROW EXECUTE FUNCTION prevent_document_os_canonical_mutation();
    CREATE TRIGGER generated_checksum_immutable
      BEFORE UPDATE OF checksum,render_manifest,version_id,object_id ON generated_files
      FOR EACH ROW EXECUTE FUNCTION prevent_document_os_canonical_mutation();
    CREATE TRIGGER approvals_immutable
      BEFORE UPDATE OR DELETE ON approvals
      FOR EACH ROW EXECUTE FUNCTION prevent_document_os_canonical_mutation();
    CREATE TRIGGER issuance_history_immutable
      BEFORE DELETE ON document_issuances
      FOR EACH ROW EXECUTE FUNCTION prevent_document_os_canonical_mutation();

    GRANT SELECT,INSERT,UPDATE ON templates,template_versions,render_jobs,
      generated_files,document_issuances,document_publication_outbox TO rtr_app;
    GRANT SELECT,INSERT ON template_bindings,render_job_bindings,approvals TO rtr_app;
    REVOKE DELETE ON templates,template_versions,template_bindings,render_jobs,
      render_job_bindings,generated_files,approvals,document_issuances,
      document_publication_outbox FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER issuance_history_immutable ON document_issuances;
    DROP TRIGGER approvals_immutable ON approvals;
    DROP TRIGGER generated_checksum_immutable ON generated_files;
    DROP TRIGGER render_bindings_immutable ON render_job_bindings;
    DROP TRIGGER approved_template_version_immutable ON template_versions;
    DROP FUNCTION guard_template_version_mutation();
    DROP FUNCTION prevent_document_os_canonical_mutation();
    DROP TABLE document_issuances;
    DROP TABLE approvals;
    DROP TABLE generated_files;
    DROP TABLE render_job_bindings;
    DROP TABLE document_publication_outbox;
    ALTER TABLE upload_sessions DROP COLUMN publication_deferred;
    DROP TABLE render_jobs;
    DROP TABLE template_bindings;
    ALTER TABLE templates DROP CONSTRAINT fk_template_current_version;
    DROP TABLE template_versions;
    DROP TABLE templates;
    ALTER TABLE resources DROP CONSTRAINT resources_resource_type_check;
    ALTER TABLE resources ADD CONSTRAINT resources_resource_type_check
      CHECK (resource_type IN
        ('source','document','document_version','object','rendition','record'));
    """)
