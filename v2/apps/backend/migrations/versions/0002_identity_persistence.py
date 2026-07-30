"""Persist immutable identities and authorization assignments."""

from alembic import op

revision = "0002_identity_persistence"
down_revision = "0001_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE subjects (
      user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      issuer text NOT NULL,
      provider_sub text NOT NULL,
      email text,
      canonical_domain text,
      display_name text NOT NULL DEFAULT '',
      status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','disabled','pending')),
      security_version integer NOT NULL DEFAULT 1 CHECK (security_version > 0),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      last_seen_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (issuer, provider_sub)
    );
    CREATE TABLE groups (
      group_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      issuer text NOT NULL,
      provider_group_key text NOT NULL,
      name text NOT NULL,
      status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','disabled')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (issuer, provider_group_key)
    );
    CREATE TABLE roles (
      role_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      key text NOT NULL UNIQUE,
      description text NOT NULL DEFAULT '',
      status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','disabled')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    INSERT INTO roles (key, description) VALUES
      ('staff','Company staff'), ('leader','Organizational leader'),
      ('curator','Knowledge curator'), ('admin','Identity administrator')
    ON CONFLICT (key) DO NOTHING;
    CREATE TABLE subject_groups (
      subject_id uuid NOT NULL REFERENCES subjects(user_id),
      group_id uuid NOT NULL REFERENCES groups(group_id),
      assigned_by uuid NULL REFERENCES subjects(user_id),
      valid_from timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (subject_id, group_id, valid_from)
    );
    CREATE TABLE subject_roles (
      subject_id uuid NOT NULL REFERENCES subjects(user_id),
      role_id uuid NOT NULL REFERENCES roles(role_id),
      assigned_by uuid NULL REFERENCES subjects(user_id),
      valid_from timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (subject_id, role_id, valid_from)
    );
    CREATE TABLE subject_scopes (
      subject_id uuid NOT NULL REFERENCES subjects(user_id),
      scope_type text NOT NULL CHECK (scope_type IN ('department','project')),
      scope_key text NOT NULL,
      valid_from timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (subject_id, scope_type, scope_key, valid_from)
    );
    CREATE TABLE policies (
      policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      version integer NOT NULL DEFAULT 1 CHECK (version > 0),
      effect text NOT NULL CHECK (effect IN ('allow','deny')),
      action text NOT NULL,
      conditions jsonb NOT NULL DEFAULT '{}',
      priority integer NOT NULL DEFAULT 0,
      active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE entitlements (
      entitlement_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      version integer NOT NULL DEFAULT 1 CHECK (version > 0),
      subject_id uuid NOT NULL REFERENCES subjects(user_id),
      resource_id uuid NULL,
      action text NOT NULL,
      effect text NOT NULL CHECK (effect IN ('allow','deny')),
      conditions jsonb NOT NULL DEFAULT '{}',
      priority integer NOT NULL DEFAULT 0,
      active boolean NOT NULL DEFAULT true,
      expires_at timestamptz NULL,
      granted_by uuid NULL REFERENCES subjects(user_id),
      reason text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_subject_roles_active
      ON subject_roles(subject_id, expires_at);
    CREATE INDEX ix_subject_groups_active
      ON subject_groups(subject_id, expires_at);
    CREATE INDEX ix_subject_scopes_active
      ON subject_scopes(subject_id, scope_type, expires_at);
    CREATE INDEX ix_entitlements_subject_active
      ON entitlements(subject_id, active, expires_at);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE entitlements;
    DROP TABLE policies;
    DROP TABLE subject_scopes;
    DROP TABLE subject_roles;
    DROP TABLE subject_groups;
    DROP TABLE roles;
    DROP TABLE groups;
    DROP TABLE subjects;
    """)
