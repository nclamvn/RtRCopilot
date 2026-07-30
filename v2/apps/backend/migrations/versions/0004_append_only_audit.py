"""Create append-only, hash-chained audit storage and runtime grants."""

from alembic import op

revision = "0004_append_only_audit"
down_revision = "0003_resource_object_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE audit_events (
      sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
      event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      occurred_at timestamptz NOT NULL DEFAULT now(),
      actor_kind text NOT NULL CHECK (actor_kind IN ('user','service','anonymous')),
      actor_user_id uuid NULL REFERENCES subjects(user_id),
      action text NOT NULL,
      result text NOT NULL CHECK (result IN ('allow','deny','success','failure')),
      reason_code text NOT NULL,
      request_id text NOT NULL,
      session_fingerprint text NULL,
      resource_id uuid NULL REFERENCES resources(resource_id),
      resource_type text NULL,
      matched_policy_ids uuid[] NOT NULL DEFAULT '{}',
      details jsonb NOT NULL DEFAULT '{}',
      previous_hash char(64) NULL,
      event_hash char(64) NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
      serialization_version integer NOT NULL DEFAULT 1
    );
    CREATE INDEX ix_audit_occurred ON audit_events(occurred_at);
    CREATE INDEX ix_audit_actor ON audit_events(actor_user_id, sequence);
    CREATE INDEX ix_audit_resource ON audit_events(resource_id, sequence);
    CREATE INDEX ix_audit_request ON audit_events(request_id);
    CREATE TABLE audit_chain_anchor (
      singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
      expected_count bigint NOT NULL DEFAULT 0 CHECK (expected_count >= 0),
      head_sequence bigint NULL,
      head_hash char(64) NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    INSERT INTO audit_chain_anchor(singleton) VALUES (true);

    CREATE OR REPLACE FUNCTION reject_audit_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'audit_events is append-only';
    END $$;
    CREATE TRIGGER audit_no_update_delete
      BEFORE UPDATE OR DELETE ON audit_events
      FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
    CREATE TRIGGER audit_no_truncate
      BEFORE TRUNCATE ON audit_events
      FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();

    CREATE OR REPLACE FUNCTION protect_audit_anchor()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'UPDATE'
         AND current_setting('rtr.audit_anchor_update', true) = 'allowed' THEN
        RETURN NEW;
      END IF;
      RAISE EXCEPTION 'audit_chain_anchor is protected';
    END $$;
    CREATE TRIGGER audit_anchor_no_mutation
      BEFORE UPDATE OR DELETE ON audit_chain_anchor
      FOR EACH ROW EXECUTE FUNCTION protect_audit_anchor();
    CREATE TRIGGER audit_anchor_no_truncate
      BEFORE TRUNCATE ON audit_chain_anchor
      FOR EACH STATEMENT EXECUTE FUNCTION protect_audit_anchor();

    CREATE OR REPLACE FUNCTION append_audit_event(
      p_event_id uuid,
      p_occurred_at timestamptz,
      p_actor_kind text,
      p_actor_user_id uuid,
      p_action text,
      p_result text,
      p_reason_code text,
      p_request_id text,
      p_session_fingerprint text,
      p_resource_id uuid,
      p_resource_type text,
      p_matched_policy_ids uuid[],
      p_details jsonb,
      p_previous_hash char(64),
      p_event_hash char(64),
      p_serialization_version integer
    ) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
      current_head char(64);
      current_count bigint;
      inserted_sequence bigint;
    BEGIN
      PERFORM pg_advisory_xact_lock(827004);
      IF lower(p_details::text) ~
        '(token|cookie|authorization|password|secret|code_verifier|raw_oidc|access_token|id_token)'
      THEN
        RAISE EXCEPTION 'audit details contain forbidden material';
      END IF;
      SELECT head_hash, expected_count INTO current_head, current_count
        FROM audit_chain_anchor WHERE singleton FOR UPDATE;
      IF current_head IS DISTINCT FROM p_previous_hash THEN
        RAISE EXCEPTION 'audit chain head mismatch';
      END IF;
      INSERT INTO audit_events (
        event_id, occurred_at, actor_kind, actor_user_id, action, result,
        reason_code, request_id, session_fingerprint, resource_id,
        resource_type, matched_policy_ids, details, previous_hash,
        event_hash, serialization_version
      ) VALUES (
        p_event_id, p_occurred_at, p_actor_kind, p_actor_user_id, p_action,
        p_result, p_reason_code, p_request_id, p_session_fingerprint,
        p_resource_id, p_resource_type, p_matched_policy_ids, p_details,
        p_previous_hash, p_event_hash, p_serialization_version
      ) RETURNING sequence INTO inserted_sequence;
      PERFORM set_config('rtr.audit_anchor_update', 'allowed', true);
      UPDATE audit_chain_anchor SET
        expected_count = current_count + 1,
        head_sequence = inserted_sequence,
        head_hash = p_event_hash,
        updated_at = now()
      WHERE singleton;
      RETURN p_event_id;
    END $$;

    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rtr_app') THEN
        CREATE ROLE rtr_app NOLOGIN;
      END IF;
    END $$;
    GRANT USAGE ON SCHEMA public TO rtr_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rtr_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rtr_app;
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit_events FROM rtr_app;
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit_chain_anchor FROM rtr_app;
    REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM rtr_app;
    GRANT EXECUTE ON FUNCTION append_audit_event(
      uuid,timestamptz,text,uuid,text,text,text,text,text,uuid,text,uuid[],
      jsonb,char(64),char(64),integer
    ) TO rtr_app;
    REVOKE CREATE ON SCHEMA public FROM rtr_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rtr_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS append_audit_event(
      uuid,timestamptz,text,uuid,text,text,text,text,text,uuid,text,uuid[],
      jsonb,char(64),char(64),integer
    );
    DROP TRIGGER audit_anchor_no_truncate ON audit_chain_anchor;
    DROP TRIGGER audit_anchor_no_mutation ON audit_chain_anchor;
    DROP FUNCTION protect_audit_anchor();
    DROP TABLE audit_chain_anchor;
    DROP TRIGGER audit_no_truncate ON audit_events;
    DROP TRIGGER audit_no_update_delete ON audit_events;
    DROP FUNCTION reject_audit_mutation();
    DROP TABLE audit_events;
    """)
