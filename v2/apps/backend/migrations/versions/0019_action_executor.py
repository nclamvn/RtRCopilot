"""Separate bounded execution ledger; DBOS history lives in a different database."""

from alembic import op

revision = "0019_action_executor"
down_revision = "0018_action_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE action_executions (
      run_id uuid PRIMARY KEY REFERENCES action_runs(run_id),
      workflow_id text NOT NULL UNIQUE,
      executor_version text NOT NULL,
      build_id text NOT NULL,
      state text NOT NULL CHECK(state IN ('queued','running','waiting','paused',
        'succeeded','partial','failed','cancelled','needs_review')),
      reason_code text NULL CHECK(reason_code IS NULL OR reason_code ~ '^[a-z][a-z_]{1,63}$'),
      cancel_requested boolean NOT NULL DEFAULT false,
      dispatch_pending boolean NOT NULL DEFAULT true,
      epoch integer NOT NULL DEFAULT 0 CHECK(epoch>=0),
      owner_token uuid NULL,
      lease_expires_at timestamptz NULL,
      tool_call_limit integer NOT NULL CHECK(tool_call_limit BETWEEN 1 AND 20),
      spent_tool_calls integer NOT NULL DEFAULT 0
        CHECK(spent_tool_calls>=0 AND spent_tool_calls<=tool_call_limit),
      deadline_at timestamptz NOT NULL,
      created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE action_step_attempts (
      attempt_id uuid PRIMARY KEY,
      run_id uuid NOT NULL REFERENCES action_executions(run_id),
      step_key text NOT NULL,
      attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3),
      epoch integer NOT NULL CHECK(epoch>0),
      owner_token uuid NOT NULL,
      source_key text NOT NULL,
      input_digest char(64) NOT NULL CHECK(input_digest ~ '^[0-9a-f]{64}$'),
      charged_calls integer NOT NULL CHECK(charged_calls BETWEEN 1 AND 8),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(run_id,step_key,attempt), UNIQUE(run_id,source_key),
      UNIQUE(attempt_id,run_id,step_key,attempt), UNIQUE(attempt_id,run_id,step_key)
    );
    CREATE TABLE action_execution_receipts (
      receipt_id uuid PRIMARY KEY,
      run_id uuid NOT NULL REFERENCES action_executions(run_id),
      attempt_id uuid NOT NULL REFERENCES action_step_attempts(attempt_id),
      step_key text NOT NULL,
      attempt integer NOT NULL,
      kind text NOT NULL CHECK(kind IN ('read_verified','job_accepted','artifact_verified',
        'failed','needs_review')),
      source_id uuid NULL,
      version_id uuid NULL,
      output_digest char(64) NOT NULL CHECK(output_digest ~ '^[0-9a-f]{64}$'),
      reused_source boolean NOT NULL DEFAULT false,
      occurred_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(run_id,step_key,attempt,kind),
      FOREIGN KEY(attempt_id,run_id,step_key,attempt)
        REFERENCES action_step_attempts(attempt_id,run_id,step_key,attempt)
    );
    CREATE TABLE action_execution_events (
      sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      run_id uuid NOT NULL REFERENCES action_executions(run_id),
      event_type text NOT NULL CHECK(event_type IN ('cancel_acknowledged','attempt_charged',
        'execution_terminal','execution_waiting')),
      reason_code text NOT NULL CHECK(reason_code ~ '^[a-z][a-z_]{1,63}$'),
      epoch integer NOT NULL,
      build_id text NOT NULL,
      occurred_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE action_source_links (
      render_job_id uuid PRIMARY KEY REFERENCES render_jobs(render_job_id),
      run_id uuid NOT NULL REFERENCES action_executions(run_id),
      attempt_id uuid NOT NULL REFERENCES action_step_attempts(attempt_id),
      step_key text NOT NULL,
      canonical_input_hash char(64) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY(attempt_id,run_id,step_key)
        REFERENCES action_step_attempts(attempt_id,run_id,step_key)
    );
    CREATE FUNCTION action_execution_bounded() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.tool_call_limit<>(SELECT (budget_limits->>'tool_calls')::integer
          FROM action_runs WHERE run_id=NEW.run_id)
         OR NEW.created_at>statement_timestamp()
         OR NEW.deadline_at>NEW.created_at+make_interval(secs=>
           (SELECT (budget_limits->>'wall_seconds')::integer
            FROM action_runs WHERE run_id=NEW.run_id)) THEN
        RAISE EXCEPTION 'action execution limits differ from parent';
      END IF;
      IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND (
        (to_jsonb(NEW)-ARRAY['state','reason_code','cancel_requested','dispatch_pending',
          'epoch','owner_token','lease_expires_at','spent_tool_calls','updated_at'])
        IS DISTINCT FROM
        (to_jsonb(OLD)-ARRAY['state','reason_code','cancel_requested','dispatch_pending',
          'epoch','owner_token','lease_expires_at','spent_tool_calls','updated_at'])
        OR NEW.spent_tool_calls<OLD.spent_tool_calls OR NEW.epoch<OLD.epoch
        OR (OLD.cancel_requested AND NOT NEW.cancel_requested)
        OR (OLD.state IN ('succeeded','partial','failed','cancelled','needs_review')
            AND NEW.state<>OLD.state))) THEN
        RAISE EXCEPTION 'action execution immutable or unbounded';
      END IF;
      IF TG_OP='UPDATE' AND OLD.state<>NEW.state AND NOT (
        (OLD.state='queued' AND NEW.state IN
          ('running','paused','partial','cancelled','failed','needs_review')) OR
        (OLD.state='running' AND NEW.state IN
          ('waiting','paused','succeeded','partial','failed','cancelled','needs_review')) OR
        (OLD.state='waiting' AND NEW.state IN
          ('running','paused','partial','failed','cancelled','needs_review')) OR
        (OLD.state='paused' AND NEW.state IN ('queued','failed','partial','needs_review',
          'cancelled'))) THEN
        RAISE EXCEPTION 'action execution transition invalid';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER action_executions_bounded BEFORE INSERT OR UPDATE OR DELETE
      ON action_executions FOR EACH ROW EXECUTE FUNCTION action_execution_bounded();
    CREATE TRIGGER action_attempts_immutable BEFORE UPDATE OR DELETE ON action_step_attempts
      FOR EACH ROW EXECUTE FUNCTION action_contract_immutable();
    CREATE TRIGGER action_execution_receipts_immutable BEFORE UPDATE OR DELETE
      ON action_execution_receipts FOR EACH ROW EXECUTE FUNCTION action_contract_immutable();
    CREATE TRIGGER action_execution_events_immutable BEFORE UPDATE OR DELETE
      ON action_execution_events FOR EACH ROW EXECUTE FUNCTION action_contract_immutable();
    CREATE TRIGGER action_source_links_immutable BEFORE UPDATE OR DELETE
      ON action_source_links FOR EACH ROW EXECUTE FUNCTION action_contract_immutable();
    GRANT SELECT,INSERT,UPDATE ON action_executions TO rtr_app;
    GRANT SELECT,INSERT ON action_step_attempts,action_execution_receipts,
      action_execution_events,action_source_links TO rtr_app;
    GRANT USAGE,SELECT ON SEQUENCE action_execution_events_sequence_seq TO rtr_app;
    REVOKE DELETE,TRUNCATE ON action_executions FROM rtr_app;
    REVOKE UPDATE,DELETE,TRUNCATE ON action_step_attempts,action_execution_receipts,
      action_execution_events,action_source_links FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("""
      DROP TABLE action_source_links,action_execution_events,action_execution_receipts,
        action_step_attempts,action_executions;
      DROP FUNCTION action_execution_bounded();
    """)
