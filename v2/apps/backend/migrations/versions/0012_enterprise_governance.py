"""Add enterprise corpus, ontology and evaluation governance ledgers."""

from alembic import op

revision = "0012_enterprise_governance"
down_revision = "0011_ingestion_pub_deferred"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE enterprise_domains (
      domain_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      domain_key text NOT NULL UNIQUE
        CHECK (domain_key ~ '^[a-z][a-z0-9._-]{1,127}$'),
      display_name text NOT NULL
        CHECK (char_length(display_name) BETWEEN 1 AND 200),
      description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 4000),
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      minimum_eval_cases integer NOT NULL DEFAULT 3
        CHECK (minimum_eval_cases BETWEEN 1 AND 1000),
      state text NOT NULL DEFAULT 'proposed' CHECK (state IN
        ('proposed','active','rejected','suspended','retired')),
      proposed_by uuid NOT NULL REFERENCES subjects(user_id),
      approved_by uuid NULL REFERENCES subjects(user_id),
      decision_reason text NULL CHECK (decision_reason IS NULL OR
        char_length(decision_reason) BETWEEN 1 AND 2000),
      proposed_at timestamptz NOT NULL DEFAULT now(),
      decided_at timestamptz NULL,
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK (approved_by IS NULL OR approved_by <> proposed_by),
      CHECK ((state = 'proposed') = (approved_by IS NULL)),
      CHECK ((state = 'proposed') = (decision_reason IS NULL)),
      CHECK ((state = 'proposed') = (decided_at IS NULL))
    );
    CREATE INDEX ix_enterprise_domains_state
      ON enterprise_domains(state, domain_key);

    CREATE TABLE enterprise_corpus_manifests (
      manifest_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      domain_id uuid NOT NULL REFERENCES enterprise_domains(domain_id),
      version integer NOT NULL CHECK (version > 0),
      manifest_digest char(64) NOT NULL UNIQUE
        CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
      sources jsonb NOT NULL CHECK
        (jsonb_typeof(sources) = 'array' AND jsonb_array_length(sources) > 0),
      source_count integer NOT NULL CHECK (source_count BETWEEN 1 AND 10000),
      state text NOT NULL DEFAULT 'proposed' CHECK (state IN
        ('proposed','validated','active','rejected','superseded')),
      validated_snapshot_digest char(64) NULL CHECK
        (validated_snapshot_digest IS NULL OR
         validated_snapshot_digest ~ '^[0-9a-f]{64}$'),
      proposed_by uuid NOT NULL REFERENCES subjects(user_id),
      validated_by uuid NULL REFERENCES subjects(user_id),
      decided_by uuid NULL REFERENCES subjects(user_id),
      decision_reason text NULL CHECK (decision_reason IS NULL OR
        char_length(decision_reason) BETWEEN 1 AND 2000),
      proposed_at timestamptz NOT NULL DEFAULT now(),
      validated_at timestamptz NULL,
      decided_at timestamptz NULL,
      UNIQUE(domain_id, version),
      CHECK (source_count = jsonb_array_length(sources)),
      CHECK (state NOT IN ('validated','active','superseded') OR
        validated_snapshot_digest IS NOT NULL),
      CHECK ((validated_snapshot_digest IS NULL) = (validated_at IS NULL)),
      CHECK ((state IN ('active','rejected','superseded')) =
        (decided_by IS NOT NULL)),
      CHECK ((state IN ('active','rejected','superseded')) =
        (decision_reason IS NOT NULL)),
      CHECK ((state IN ('active','rejected','superseded')) =
        (decided_at IS NOT NULL)),
      CHECK (decided_by IS NULL OR decided_by <> proposed_by)
    );
    CREATE UNIQUE INDEX ux_enterprise_corpus_active_domain
      ON enterprise_corpus_manifests(domain_id) WHERE state = 'active';
    CREATE INDEX ix_enterprise_corpus_state
      ON enterprise_corpus_manifests(state, proposed_at DESC);

    CREATE TABLE enterprise_ontology_revisions (
      revision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      registry_id text NOT NULL
        CHECK (registry_id ~ '^[a-z0-9][a-z0-9._-]{2,127}$'),
      version integer NOT NULL CHECK (version > 0),
      ontology_digest char(64) NOT NULL UNIQUE
        CHECK (ontology_digest ~ '^[0-9a-f]{64}$'),
      payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
      entity_count integer NOT NULL CHECK (entity_count BETWEEN 1 AND 100000),
      state text NOT NULL DEFAULT 'proposed' CHECK (state IN
        ('proposed','approved','rejected','active','superseded')),
      proposed_by uuid NOT NULL REFERENCES subjects(user_id),
      decided_by uuid NULL REFERENCES subjects(user_id),
      decision_reason text NULL CHECK (decision_reason IS NULL OR
        char_length(decision_reason) BETWEEN 1 AND 2000),
      activated_by uuid NULL REFERENCES subjects(user_id),
      evaluation_run_id uuid NULL,
      proposed_at timestamptz NOT NULL DEFAULT now(),
      decided_at timestamptz NULL,
      activated_at timestamptz NULL,
      UNIQUE(registry_id, version),
      CHECK (decided_by IS NULL OR decided_by <> proposed_by),
      CHECK ((state = 'proposed') = (decided_by IS NULL)),
      CHECK ((state = 'proposed') = (decision_reason IS NULL)),
      CHECK ((state = 'proposed') = (decided_at IS NULL)),
      CHECK ((state IN ('active','superseded')) = (activated_by IS NOT NULL)),
      CHECK ((state IN ('active','superseded')) = (evaluation_run_id IS NOT NULL)),
      CHECK ((state IN ('active','superseded')) = (activated_at IS NOT NULL))
    );
    CREATE UNIQUE INDEX ux_enterprise_ontology_single_active
      ON enterprise_ontology_revisions((state)) WHERE state = 'active';
    CREATE INDEX ix_enterprise_ontology_state
      ON enterprise_ontology_revisions(state, proposed_at DESC);

    CREATE TABLE enterprise_evaluation_suites (
      suite_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      suite_key text NOT NULL
        CHECK (suite_key ~ '^[a-z][a-z0-9._-]{1,127}$'),
      version integer NOT NULL CHECK (version > 0),
      suite_digest char(64) NOT NULL UNIQUE
        CHECK (suite_digest ~ '^[0-9a-f]{64}$'),
      definition jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
      case_count integer NOT NULL CHECK (case_count BETWEEN 1 AND 10000),
      domain_count integer NOT NULL CHECK (domain_count BETWEEN 1 AND 1000),
      state text NOT NULL DEFAULT 'proposed' CHECK (state IN
        ('proposed','approved','rejected','retired')),
      proposed_by uuid NOT NULL REFERENCES subjects(user_id),
      decided_by uuid NULL REFERENCES subjects(user_id),
      decision_reason text NULL CHECK (decision_reason IS NULL OR
        char_length(decision_reason) BETWEEN 1 AND 2000),
      proposed_at timestamptz NOT NULL DEFAULT now(),
      decided_at timestamptz NULL,
      UNIQUE(suite_key, version),
      CHECK (decided_by IS NULL OR decided_by <> proposed_by),
      CHECK ((state = 'proposed') = (decided_by IS NULL)),
      CHECK ((state = 'proposed') = (decision_reason IS NULL)),
      CHECK ((state = 'proposed') = (decided_at IS NULL))
    );
    CREATE INDEX ix_enterprise_suites_state
      ON enterprise_evaluation_suites(state, proposed_at DESC);

    CREATE TABLE enterprise_evaluation_runs (
      run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      suite_id uuid NOT NULL REFERENCES enterprise_evaluation_suites(suite_id),
      ontology_revision_id uuid NOT NULL
        REFERENCES enterprise_ontology_revisions(revision_id),
      ontology_digest char(64) NOT NULL
        CHECK (ontology_digest ~ '^[0-9a-f]{64}$'),
      suite_digest char(64) NOT NULL CHECK (suite_digest ~ '^[0-9a-f]{64}$'),
      corpus_snapshot_digest char(64) NOT NULL
        CHECK (corpus_snapshot_digest ~ '^[0-9a-f]{64}$'),
      evaluation_subject_digest char(64) NOT NULL
        CHECK (evaluation_subject_digest ~ '^[0-9a-f]{64}$'),
      status text NOT NULL CHECK (status IN ('passed','failed','incomplete')),
      passed_count integer NOT NULL CHECK (passed_count >= 0),
      failed_count integer NOT NULL CHECK (failed_count >= 0),
      critical_failed_count integer NOT NULL CHECK (critical_failed_count >= 0),
      domain_metrics jsonb NOT NULL CHECK (jsonb_typeof(domain_metrics) = 'object'),
      result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
      result_digest char(64) NOT NULL UNIQUE
        CHECK (result_digest ~ '^[0-9a-f]{64}$'),
      executed_by uuid NOT NULL REFERENCES subjects(user_id),
      started_at timestamptz NOT NULL,
      finished_at timestamptz NOT NULL,
      CHECK (finished_at >= started_at),
      CHECK (passed_count + failed_count > 0),
      CHECK ((status = 'passed') =
        (failed_count = 0 AND critical_failed_count = 0))
    );
    CREATE INDEX ix_enterprise_eval_runs_suite
      ON enterprise_evaluation_runs(suite_id, finished_at DESC);

    ALTER TABLE enterprise_ontology_revisions
      ADD CONSTRAINT fk_enterprise_ontology_eval_run
      FOREIGN KEY (evaluation_run_id)
      REFERENCES enterprise_evaluation_runs(run_id)
      DEFERRABLE INITIALLY DEFERRED;

    CREATE TABLE enterprise_release_attestations (
      attestation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      registry_id text NOT NULL,
      ontology_revision_id uuid NOT NULL
        REFERENCES enterprise_ontology_revisions(revision_id),
      evaluation_run_id uuid NOT NULL REFERENCES enterprise_evaluation_runs(run_id),
      ontology_digest char(64) NOT NULL
        CHECK (ontology_digest ~ '^[0-9a-f]{64}$'),
      corpus_snapshot_digest char(64) NOT NULL
        CHECK (corpus_snapshot_digest ~ '^[0-9a-f]{64}$'),
      suite_digest char(64) NOT NULL CHECK (suite_digest ~ '^[0-9a-f]{64}$'),
      result_digest char(64) NOT NULL CHECK (result_digest ~ '^[0-9a-f]{64}$'),
      release_digest char(64) NOT NULL UNIQUE
        CHECK (release_digest ~ '^[0-9a-f]{64}$'),
      state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','superseded')),
      approved_by uuid NOT NULL REFERENCES subjects(user_id),
      activated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX ux_enterprise_release_single_active
      ON enterprise_release_attestations((state)) WHERE state = 'active';

    CREATE OR REPLACE FUNCTION guard_enterprise_domain_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'enterprise domain history is immutable'; END IF;
      IF (to_jsonb(NEW) - ARRAY['state','approved_by','decision_reason','decided_at','updated_at'])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['state','approved_by','decision_reason','decided_at','updated_at']) THEN
        RAISE EXCEPTION 'enterprise domain content is immutable';
      END IF;
      IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
        (OLD.state='proposed' AND NEW.state IN ('active','rejected')) OR
        (OLD.state='active' AND NEW.state IN ('suspended','retired')) OR
        (OLD.state='suspended' AND NEW.state IN ('active','retired'))
      ) THEN RAISE EXCEPTION 'invalid enterprise domain transition'; END IF;
      RETURN NEW;
    END $$;

    CREATE OR REPLACE FUNCTION guard_enterprise_manifest_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'enterprise corpus history is immutable'; END IF;
      IF (to_jsonb(NEW) - ARRAY['state','validated_snapshot_digest','validated_by',
           'decided_by','decision_reason','validated_at','decided_at'])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['state','validated_snapshot_digest','validated_by',
           'decided_by','decision_reason','validated_at','decided_at']) THEN
        RAISE EXCEPTION 'enterprise corpus content is immutable';
      END IF;
      IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
        (OLD.state='proposed' AND NEW.state IN ('validated','rejected')) OR
        (OLD.state='validated' AND NEW.state IN ('active','rejected')) OR
        (OLD.state='active' AND NEW.state='superseded')
      ) THEN RAISE EXCEPTION 'invalid enterprise corpus transition'; END IF;
      RETURN NEW;
    END $$;

    CREATE OR REPLACE FUNCTION guard_enterprise_ontology_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'enterprise ontology history is immutable'; END IF;
      IF (to_jsonb(NEW) - ARRAY['state','decided_by','decision_reason','activated_by',
           'evaluation_run_id','decided_at','activated_at'])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['state','decided_by','decision_reason','activated_by',
           'evaluation_run_id','decided_at','activated_at']) THEN
        RAISE EXCEPTION 'enterprise ontology content is immutable';
      END IF;
      IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
        (OLD.state='proposed' AND NEW.state IN ('approved','rejected')) OR
        (OLD.state='approved' AND NEW.state='active') OR
        (OLD.state='active' AND NEW.state='superseded')
      ) THEN RAISE EXCEPTION 'invalid enterprise ontology transition'; END IF;
      RETURN NEW;
    END $$;

    CREATE OR REPLACE FUNCTION guard_enterprise_suite_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'enterprise suite history is immutable'; END IF;
      IF (to_jsonb(NEW) - ARRAY['state','decided_by','decision_reason','decided_at'])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['state','decided_by','decision_reason','decided_at']) THEN
        RAISE EXCEPTION 'enterprise suite content is immutable';
      END IF;
      IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
        (OLD.state='proposed' AND NEW.state IN ('approved','rejected')) OR
        (OLD.state='approved' AND NEW.state='retired')
      ) THEN RAISE EXCEPTION 'invalid enterprise suite transition'; END IF;
      RETURN NEW;
    END $$;

    CREATE OR REPLACE FUNCTION prevent_enterprise_history_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'enterprise evaluation history is immutable'; END $$;

    CREATE OR REPLACE FUNCTION guard_enterprise_release_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'enterprise release history is immutable'; END IF;
      IF (to_jsonb(NEW) - 'state') IS DISTINCT FROM (to_jsonb(OLD) - 'state')
        OR NOT (OLD.state='active' AND NEW.state='superseded') THEN
        RAISE EXCEPTION 'enterprise release attestation is immutable';
      END IF;
      RETURN NEW;
    END $$;

    CREATE TRIGGER enterprise_domains_guarded BEFORE UPDATE OR DELETE
      ON enterprise_domains FOR EACH ROW EXECUTE FUNCTION guard_enterprise_domain_mutation();
    CREATE TRIGGER enterprise_corpus_guarded BEFORE UPDATE OR DELETE
      ON enterprise_corpus_manifests FOR EACH ROW EXECUTE FUNCTION guard_enterprise_manifest_mutation();
    CREATE TRIGGER enterprise_ontology_guarded BEFORE UPDATE OR DELETE
      ON enterprise_ontology_revisions FOR EACH ROW EXECUTE FUNCTION guard_enterprise_ontology_mutation();
    CREATE TRIGGER enterprise_suites_guarded BEFORE UPDATE OR DELETE
      ON enterprise_evaluation_suites FOR EACH ROW EXECUTE FUNCTION guard_enterprise_suite_mutation();
    CREATE TRIGGER enterprise_runs_immutable BEFORE UPDATE OR DELETE
      ON enterprise_evaluation_runs FOR EACH ROW EXECUTE FUNCTION prevent_enterprise_history_mutation();
    CREATE TRIGGER enterprise_releases_guarded BEFORE UPDATE OR DELETE
      ON enterprise_release_attestations FOR EACH ROW EXECUTE FUNCTION guard_enterprise_release_mutation();

    GRANT SELECT,INSERT,UPDATE ON enterprise_domains,
      enterprise_corpus_manifests,enterprise_ontology_revisions,
      enterprise_evaluation_suites,enterprise_release_attestations TO rtr_app;
    GRANT SELECT,INSERT ON enterprise_evaluation_runs TO rtr_app;
    REVOKE UPDATE ON enterprise_evaluation_runs FROM rtr_app;
    REVOKE DELETE ON enterprise_domains,enterprise_corpus_manifests,
      enterprise_ontology_revisions,enterprise_evaluation_suites,
      enterprise_evaluation_runs,enterprise_release_attestations FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER enterprise_releases_guarded ON enterprise_release_attestations;
    DROP TRIGGER enterprise_runs_immutable ON enterprise_evaluation_runs;
    DROP TRIGGER enterprise_suites_guarded ON enterprise_evaluation_suites;
    DROP TRIGGER enterprise_ontology_guarded ON enterprise_ontology_revisions;
    DROP TRIGGER enterprise_corpus_guarded ON enterprise_corpus_manifests;
    DROP TRIGGER enterprise_domains_guarded ON enterprise_domains;
    DROP FUNCTION guard_enterprise_release_mutation();
    DROP FUNCTION prevent_enterprise_history_mutation();
    DROP FUNCTION guard_enterprise_suite_mutation();
    DROP FUNCTION guard_enterprise_ontology_mutation();
    DROP FUNCTION guard_enterprise_manifest_mutation();
    DROP FUNCTION guard_enterprise_domain_mutation();
    DROP TABLE enterprise_release_attestations;
    ALTER TABLE enterprise_ontology_revisions
      DROP CONSTRAINT fk_enterprise_ontology_eval_run;
    DROP TABLE enterprise_evaluation_runs;
    DROP TABLE enterprise_evaluation_suites;
    DROP TABLE enterprise_ontology_revisions;
    DROP TABLE enterprise_corpus_manifests;
    DROP TABLE enterprise_domains;
    """)
