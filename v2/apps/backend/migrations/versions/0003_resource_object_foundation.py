"""Create authorization resources and immutable object metadata."""

from alembic import op

revision = "0003_resource_object_foundation"
down_revision = "0002_identity_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE resources (
      resource_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      resource_type text NOT NULL CHECK (resource_type IN
        ('source','document','document_version','object','rendition')),
      owner_subject_id uuid NULL REFERENCES subjects(user_id),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      source_zone text NOT NULL CHECK (source_zone IN
        ('sot','research','private_context')),
      department_id uuid NULL,
      project_id uuid NULL,
      lifecycle_state text NOT NULL DEFAULT 'draft' CHECK (lifecycle_state IN
        ('draft','active','superseded','quarantined','deleted')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      deleted_at timestamptz NULL,
      retention_until timestamptz NULL,
      legal_hold boolean NOT NULL DEFAULT false
    );
    CREATE INDEX ix_resources_policy
      ON resources(classification, source_zone, lifecycle_state);
    CREATE INDEX ix_resources_owner ON resources(owner_subject_id);
    CREATE INDEX ix_resources_department ON resources(department_id);
    CREATE INDEX ix_resources_project ON resources(project_id);

    ALTER TABLE entitlements ADD CONSTRAINT fk_entitlement_resource
      FOREIGN KEY (resource_id) REFERENCES resources(resource_id);

    CREATE TABLE acl_entries (
      acl_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      resource_id uuid NOT NULL REFERENCES resources(resource_id),
      principal_type text NOT NULL CHECK (principal_type IN
        ('user','group','role','department','project')),
      principal_id uuid NOT NULL,
      action text NOT NULL,
      effect text NOT NULL CHECK (effect IN ('allow','deny')),
      conditions jsonb NOT NULL DEFAULT '{}',
      valid_from timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NULL,
      granted_by uuid NULL REFERENCES subjects(user_id),
      reason text,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX uq_acl_semantics ON acl_entries
      (resource_id, principal_type, principal_id, action, effect,
       md5(conditions::text), valid_from);
    CREATE INDEX ix_acl_active ON acl_entries(resource_id, action, expires_at);

    CREATE TABLE sources (
      source_id uuid PRIMARY KEY REFERENCES resources(resource_id),
      kind text NOT NULL,
      name text NOT NULL,
      canonical_uri text NULL,
      metadata jsonb NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE object_blobs (
      object_id uuid PRIMARY KEY REFERENCES resources(resource_id),
      bucket text NOT NULL,
      object_key text NOT NULL UNIQUE,
      sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
      byte_size bigint NOT NULL CHECK (byte_size >= 0),
      mime_type text NOT NULL,
      etag text NULL,
      encryption_key_ref text NULL,
      storage_state text NOT NULL CHECK (storage_state IN
        ('staged','available','quarantined','missing','deleted')),
      created_by uuid NULL REFERENCES subjects(user_id),
      created_at timestamptz NOT NULL DEFAULT now(),
      verified_at timestamptz NULL
    );
    CREATE INDEX ix_object_state ON object_blobs(storage_state, created_at);
    CREATE TABLE maintenance_state (
      singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
      enabled boolean NOT NULL DEFAULT false,
      reason text NULL,
      changed_at timestamptz NOT NULL DEFAULT now(),
      changed_by text NULL
    );
    INSERT INTO maintenance_state(singleton, enabled) VALUES (true, false);
    CREATE TABLE object_reconciliation_intents (
      intent_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      object_key text NOT NULL,
      operation text NOT NULL CHECK (operation IN ('delete','repair')),
      state text NOT NULL CHECK (state IN ('pending','completed','failed')),
      requested_by uuid NOT NULL REFERENCES subjects(user_id),
      request_id text NOT NULL,
      error_code text NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      completed_at timestamptz NULL
    );
    CREATE INDEX ix_reconciliation_pending
      ON object_reconciliation_intents(state, created_at);
    CREATE TABLE documents (
      document_id uuid PRIMARY KEY REFERENCES resources(resource_id),
      source_id uuid NULL REFERENCES sources(source_id),
      logical_name text NOT NULL,
      current_version_id uuid NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE document_versions (
      version_id uuid PRIMARY KEY REFERENCES resources(resource_id),
      document_id uuid NOT NULL REFERENCES documents(document_id),
      version_no integer NOT NULL CHECK (version_no > 0),
      object_id uuid NOT NULL REFERENCES object_blobs(object_id),
      original_filename text NOT NULL,
      mime_type text NOT NULL,
      sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
      byte_size bigint NOT NULL CHECK (byte_size >= 0),
      created_by uuid NULL REFERENCES subjects(user_id),
      created_at timestamptz NOT NULL DEFAULT now(),
      effective_at timestamptz NULL,
      review_after timestamptz NULL,
      expires_at timestamptz NULL,
      supersedes_version_id uuid NULL REFERENCES document_versions(version_id),
      UNIQUE(document_id, version_no),
      UNIQUE(document_id, object_id)
    );
    ALTER TABLE documents ADD CONSTRAINT fk_document_current_version
      FOREIGN KEY (current_version_id) REFERENCES document_versions(version_id)
      DEFERRABLE INITIALLY DEFERRED;
    CREATE TABLE renditions (
      rendition_id uuid PRIMARY KEY REFERENCES resources(resource_id),
      version_id uuid NOT NULL REFERENCES document_versions(version_id),
      kind text NOT NULL,
      object_id uuid NOT NULL REFERENCES object_blobs(object_id),
      mime_type text NOT NULL,
      status text NOT NULL CHECK (status IN
        ('pending','ready','failed','quarantined')),
      generator text NOT NULL,
      generator_version text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      error_code text NULL
    );
    CREATE OR REPLACE FUNCTION prevent_version_content_update()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.object_id <> OLD.object_id OR NEW.sha256 <> OLD.sha256
         OR NEW.byte_size <> OLD.byte_size OR NEW.mime_type <> OLD.mime_type THEN
        RAISE EXCEPTION 'activated document version content is immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER document_version_content_immutable
      BEFORE UPDATE ON document_versions
      FOR EACH ROW EXECUTE FUNCTION prevent_version_content_update();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER document_version_content_immutable ON document_versions;
    DROP FUNCTION prevent_version_content_update();
    DROP TABLE renditions;
    ALTER TABLE documents DROP CONSTRAINT fk_document_current_version;
    DROP TABLE document_versions;
    DROP TABLE documents;
    DROP TABLE object_reconciliation_intents;
    DROP TABLE maintenance_state;
    DROP TABLE object_blobs;
    DROP TABLE sources;
    DROP TABLE acl_entries;
    ALTER TABLE entitlements DROP CONSTRAINT fk_entitlement_resource;
    DROP TABLE resources;
    """)
