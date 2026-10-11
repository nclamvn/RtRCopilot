"""Immutable action contracts and bounded local domain accounting; no executor."""

from alembic import op

revision = "0018_action_contracts"
down_revision = "0017_context_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE capability_versions (
      capability_id text NOT NULL,
      version text NOT NULL,
      spec jsonb NOT NULL CHECK (jsonb_typeof(spec)='object'),
      contract_digest char(64) NOT NULL CHECK (contract_digest ~ '^[0-9a-f]{64}$'),
      schema_digest char(64) NOT NULL CHECK (schema_digest ~ '^[0-9a-f]{64}$'),
      admission text NOT NULL CHECK (admission IN ('admitted','revoked')),
      admitted_by uuid NOT NULL REFERENCES subjects(user_id),
      created_at timestamptz NOT NULL DEFAULT now(),
      revoked_at timestamptz NULL,
      PRIMARY KEY(capability_id,version),
      CHECK ((admission='revoked')=(revoked_at IS NOT NULL))
    );
    CREATE TABLE action_plans (
      plan_id uuid PRIMARY KEY,
      root_plan_id uuid NOT NULL REFERENCES action_plans(plan_id) DEFERRABLE INITIALLY DEFERRED,
      plan_version integer NOT NULL CHECK (plan_version>0),
      actor_id uuid NOT NULL REFERENCES subjects(user_id),
      workspace_id uuid NULL,
      idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 8 AND 200),
      plan_digest char(64) NOT NULL CHECK (plan_digest ~ '^[0-9a-f]{64}$'),
      payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
      supersedes_plan_id uuid NULL REFERENCES action_plans(plan_id),
      request_id text NOT NULL,
      build_id text NOT NULL CHECK (char_length(build_id) BETWEEN 7 AND 64),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(actor_id,idempotency_key), UNIQUE(root_plan_id,plan_version)
    );
    CREATE INDEX ix_action_plans_actor ON action_plans(actor_id,created_at DESC);
    CREATE TABLE action_runs (
      run_id uuid PRIMARY KEY,
      plan_id uuid NOT NULL UNIQUE REFERENCES action_plans(plan_id),
      state text NOT NULL CHECK (state IN ('contract_ready','awaiting_approval','cancelled')),
      budget_limits jsonb NOT NULL CHECK (jsonb_typeof(budget_limits)='object'),
      budget_reserved jsonb NOT NULL CHECK (jsonb_typeof(budget_reserved)='object'),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE action_approvals (
      approval_id uuid PRIMARY KEY,
      plan_id uuid NOT NULL REFERENCES action_plans(plan_id),
      reviewer_id uuid NOT NULL REFERENCES subjects(user_id),
      binding jsonb NOT NULL CHECK (jsonb_typeof(binding)='object'),
      decision text NOT NULL CHECK (decision IN ('approved','rejected')),
      expires_at timestamptz NOT NULL,
      revoked_at timestamptz NULL,
      revoked_by uuid NULL REFERENCES subjects(user_id),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((revoked_at IS NULL)=(revoked_by IS NULL))
    );
    CREATE INDEX ix_action_approvals_plan ON action_approvals(plan_id,created_at DESC);
    CREATE TABLE action_events (
      sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
      event_id uuid PRIMARY KEY,
      run_id uuid NOT NULL REFERENCES action_runs(run_id),
      event_key char(64) NOT NULL CHECK (event_key ~ '^[0-9a-f]{64}$'),
      event_type text NOT NULL CHECK (event_type IN
        ('plan_admitted','approval_recorded','approval_revoked','ready_validated','budget_reserved')),
      reason_code text NOT NULL CHECK (reason_code ~ '^[a-z][a-z_]{1,63}$'),
      plan_digest char(64) NOT NULL CHECK (plan_digest ~ '^[0-9a-f]{64}$'),
      correlation_digest char(64) NOT NULL CHECK (correlation_digest ~ '^[0-9a-f]{64}$'),
      usage jsonb NULL CHECK (usage IS NULL OR jsonb_typeof(usage)='object'),
      request_id text NOT NULL,
      build_id text NOT NULL CHECK (char_length(build_id) BETWEEN 7 AND 64),
      occurred_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(run_id,event_key)
    );
    CREATE TABLE action_receipts (
      receipt_id uuid PRIMARY KEY,
      run_id uuid NOT NULL REFERENCES action_runs(run_id),
      plan_digest char(64) NOT NULL CHECK (plan_digest ~ '^[0-9a-f]{64}$'),
      kind text NOT NULL CHECK (kind IN ('contract_admission','contract_validation')),
      outcome text NOT NULL CHECK (outcome IN ('contract_ready','awaiting_approval')),
      request_id text NOT NULL,
      build_id text NOT NULL CHECK (char_length(build_id) BETWEEN 7 AND 64),
      occurred_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE OR REPLACE FUNCTION action_contract_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'action contract history is immutable'; END $$;
    CREATE TRIGGER action_plans_immutable BEFORE UPDATE OR DELETE ON action_plans
      FOR EACH ROW EXECUTE FUNCTION action_contract_immutable();
    CREATE TRIGGER action_events_immutable BEFORE UPDATE OR DELETE ON action_events
      FOR EACH ROW EXECUTE FUNCTION action_contract_immutable();
    CREATE TRIGGER action_receipts_immutable BEFORE UPDATE OR DELETE ON action_receipts
      FOR EACH ROW EXECUTE FUNCTION action_contract_immutable();
    CREATE OR REPLACE FUNCTION action_capability_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR (to_jsonb(NEW)-'admission'-'revoked_at') IS DISTINCT FROM
         (to_jsonb(OLD)-'admission'-'revoked_at') OR OLD.admission='revoked'
         OR NEW.admission<>'revoked' THEN
        RAISE EXCEPTION 'admitted action capability is immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER capability_versions_immutable BEFORE UPDATE OR DELETE ON capability_versions
      FOR EACH ROW EXECUTE FUNCTION action_capability_immutable();
    CREATE OR REPLACE FUNCTION action_approval_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR (to_jsonb(NEW)-'revoked_at'-'revoked_by') IS DISTINCT FROM
         (to_jsonb(OLD)-'revoked_at'-'revoked_by') OR OLD.revoked_at IS NOT NULL
         OR NEW.revoked_at IS NULL THEN
        RAISE EXCEPTION 'action approval binding is immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER action_approvals_immutable BEFORE UPDATE OR DELETE ON action_approvals
      FOR EACH ROW EXECUTE FUNCTION action_approval_immutable();
    CREATE OR REPLACE FUNCTION action_run_bounded() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE dimension text;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'action run is immutable'; END IF;
      IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'state'-'budget_reserved'-'updated_at') IS DISTINCT FROM
                           (to_jsonb(OLD)-'state'-'budget_reserved'-'updated_at') THEN
        RAISE EXCEPTION 'action run limits are immutable';
      END IF;
      IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.budget_reserved) key)
         IS DISTINCT FROM ARRAY['model_calls','spend_microusd','tokens','tool_calls','wall_seconds']
         OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.budget_limits) key)
         IS DISTINCT FROM ARRAY['model_calls','spend_microusd','tokens','tool_calls','wall_seconds'] THEN
        RAISE EXCEPTION 'action budget dimensions invalid';
      END IF;
      FOREACH dimension IN ARRAY ARRAY['model_calls','spend_microusd','tokens','tool_calls','wall_seconds']
      LOOP
        IF jsonb_typeof(NEW.budget_reserved->dimension)<>'number'
           OR jsonb_typeof(NEW.budget_limits->dimension)<>'number'
           OR (NEW.budget_reserved->>dimension)::numeric % 1 <> 0
           OR (NEW.budget_limits->>dimension)::numeric % 1 <> 0
           OR (NEW.budget_reserved->>dimension)::numeric < 0
           OR (NEW.budget_limits->>dimension)::numeric < 0
           OR (NEW.budget_reserved->>dimension)::numeric > (NEW.budget_limits->>dimension)::numeric
           OR (TG_OP='UPDATE' AND (NEW.budget_reserved->>dimension)::numeric
                                 < (OLD.budget_reserved->>dimension)::numeric) THEN
          RAISE EXCEPTION 'action budget exhausted or invalid';
        END IF;
      END LOOP;
      RETURN NEW;
    END $$;
    CREATE TRIGGER action_runs_bounded BEFORE INSERT OR UPDATE OR DELETE ON action_runs
      FOR EACH ROW EXECUTE FUNCTION action_run_bounded();
    GRANT SELECT,INSERT ON action_plans,action_events,action_receipts TO rtr_app;
    GRANT SELECT,INSERT,UPDATE ON capability_versions,action_runs,action_approvals TO rtr_app;
    GRANT USAGE,SELECT ON SEQUENCE action_events_sequence_seq TO rtr_app;
    REVOKE UPDATE,DELETE,TRUNCATE ON action_plans,action_events,action_receipts FROM rtr_app;
    REVOKE DELETE,TRUNCATE ON capability_versions,action_runs,action_approvals FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE action_receipts,action_events,action_approvals,action_runs,action_plans,
      capability_versions;
    DROP FUNCTION action_run_bounded(),action_approval_immutable(),
      action_capability_immutable(),action_contract_immutable();
    """)
