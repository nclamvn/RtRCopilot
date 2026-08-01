"""Add governance queues, research trust zone and graduation storage."""

from alembic import op

revision = "0009_governance_research"
down_revision = "0008_document_operating_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE research_sources (
      source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      stable_key text NOT NULL UNIQUE CHECK (stable_key ~ '^[a-z0-9][a-z0-9._-]{1,127}$'),
      display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 200),
      description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
      origin text NOT NULL CHECK (origin IN ('refinery','manual','partner')),
      owner_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      classification text NOT NULL CHECK (classification IN
        ('public_internal','internal','restricted','highly_restricted')),
      lifecycle text NOT NULL DEFAULT 'active' CHECK (lifecycle IN
        ('active','suspended','retired')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_research_sources_ledger
      ON research_sources(lifecycle, lower(display_name), source_id);

    CREATE TABLE research_packages (
      package_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      source_id uuid NOT NULL REFERENCES research_sources(source_id),
      fingerprint char(64) NOT NULL UNIQUE CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
      payload_sha256 char(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
      snapshot_manifest jsonb NOT NULL,
      captured_at timestamptz NOT NULL,
      snapshot_scope text NOT NULL CHECK (char_length(snapshot_scope) BETWEEN 1 AND 512),
      adapter_version text NOT NULL CHECK (adapter_version ~ '^[a-z0-9._-]{1,64}$'),
      tier_composition jsonb NOT NULL DEFAULT '{}',
      import_state text NOT NULL DEFAULT 'received' CHECK (import_state IN
        ('received','validating','imported','rejected')),
      rejection_code text NULL,
      record_count integer NOT NULL DEFAULT 0 CHECK (record_count >= 0),
      importer_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      received_at timestamptz NOT NULL DEFAULT now(),
      imported_at timestamptz NULL,
      CHECK (jsonb_typeof(snapshot_manifest) = 'object'),
      CHECK (snapshot_manifest->>'adapter_version' = adapter_version),
      CHECK (snapshot_manifest->>'scope' = snapshot_scope),
      CHECK (jsonb_typeof(tier_composition) = 'object'),
      CHECK ((import_state = 'rejected') = (rejection_code IS NOT NULL)),
      CHECK ((import_state = 'imported') = (imported_at IS NOT NULL))
    );
    CREATE INDEX ix_research_packages_source
      ON research_packages(source_id, received_at DESC);
    CREATE INDEX ix_research_packages_state
      ON research_packages(import_state, received_at DESC);

    CREATE TABLE research_records (
      research_record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      package_id uuid NOT NULL REFERENCES research_packages(package_id),
      record_key text NOT NULL CHECK (char_length(record_key) BETWEEN 1 AND 256),
      version_ordinal integer NOT NULL CHECK (version_ordinal > 0),
      tier text NOT NULL CHECK (tier IN ('P','S','H','X')),
      zone_label text NOT NULL DEFAULT 'research' CHECK (zone_label = 'research'),
      content jsonb NOT NULL,
      searchable_text text NOT NULL CHECK (char_length(searchable_text) <= 200000),
      evidence_spans jsonb NOT NULL,
      corroboration_state text NOT NULL DEFAULT 'uncorroborated' CHECK
        (corroboration_state IN ('uncorroborated','corroborated','disputed')),
      content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK (jsonb_typeof(evidence_spans) = 'array'
             AND jsonb_array_length(evidence_spans) > 0),
      UNIQUE(package_id, record_key),
      UNIQUE(record_key, version_ordinal)
    );
    CREATE INDEX ix_research_records_key
      ON research_records(record_key, version_ordinal DESC);
    CREATE INDEX ix_research_records_tier
      ON research_records(tier, created_at DESC);

    ALTER TABLE gaps DROP CONSTRAINT gaps_lifecycle_check;
    ALTER TABLE gaps ADD CONSTRAINT gaps_lifecycle_check CHECK (lifecycle IN
      ('open','triaged','assigned','answered','published','declined',
       'resolved','dismissed'));
    ALTER TABLE gaps DROP CONSTRAINT gaps_reason_category_check;
    ALTER TABLE gaps ADD CONSTRAINT gaps_reason_category_check
      CHECK (reason_category IN
        ('no_evidence','denied_or_unavailable','insufficient_confidence',
         'stale_only','grounding_failed','manual_entry'));
    ALTER TABLE gaps ALTER COLUMN answer_run_id DROP NOT NULL;
    ALTER TABLE gaps
      ADD COLUMN origin text NOT NULL DEFAULT 'honest_null'
        CHECK (origin IN ('honest_null','manual')),
      ADD COLUMN priority text NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low','normal','high','urgent')),
      ADD COLUMN triaged_at timestamptz NULL,
      ADD COLUMN assigned_at timestamptz NULL,
      ADD COLUMN due_at timestamptz NULL,
      ADD COLUMN answered_at timestamptz NULL,
      ADD COLUMN closed_at timestamptz NULL,
      ADD COLUMN resolving_version_id uuid NULL REFERENCES record_versions(version_id),
      ADD COLUMN decline_reason text NULL CHECK (decline_reason IS NULL
        OR char_length(decline_reason) BETWEEN 1 AND 2000);
    ALTER TABLE gaps ADD CONSTRAINT gaps_origin_run_check
      CHECK (origin = 'manual' OR answer_run_id IS NOT NULL);
    ALTER TABLE gaps ADD CONSTRAINT gaps_decline_reason_state_check
      CHECK ((decline_reason IS NOT NULL) = (lifecycle = 'declined'));
    ALTER TABLE gaps ADD CONSTRAINT gaps_resolution_link_check
      CHECK (lifecycle NOT IN ('answered','published')
             OR resolving_version_id IS NOT NULL);
    CREATE INDEX ix_gaps_queue ON gaps(lifecycle, priority, due_at, gap_id);
    CREATE INDEX ix_gaps_owner ON gaps(owner_subject_id, lifecycle)
      WHERE owner_subject_id IS NOT NULL;

    CREATE TABLE gap_transitions (
      sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
      transition_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      gap_id uuid NOT NULL REFERENCES gaps(gap_id),
      from_state text NOT NULL CHECK (from_state IN
        ('open','triaged','assigned','answered','published','declined')),
      to_state text NOT NULL CHECK (to_state IN
        ('triaged','assigned','answered','published','declined')),
      actor_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      reason text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 2000),
      occurred_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_gap_transitions_gap ON gap_transitions(gap_id, sequence);

    CREATE TABLE review_tasks (
      task_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      queue_kind text NOT NULL CHECK (queue_kind IN
        ('freshness','conflict','owner_review')),
      record_version_id uuid NOT NULL REFERENCES record_versions(version_id),
      assignee_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      assigned_by uuid NOT NULL REFERENCES subjects(user_id),
      state text NOT NULL DEFAULT 'assigned' CHECK (state IN
        ('assigned','completed','reopened')),
      due_at timestamptz NULL,
      note text NOT NULL DEFAULT '' CHECK (char_length(note) <= 2000),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      completed_at timestamptz NULL,
      CHECK ((state = 'completed') = (completed_at IS NOT NULL)),
      UNIQUE(queue_kind, record_version_id)
    );
    CREATE INDEX ix_review_tasks_assignee
      ON review_tasks(assignee_subject_id, state, due_at);

    CREATE TABLE graduation_proposals (
      proposal_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      research_record_ids uuid[] NOT NULL CHECK
        (cardinality(research_record_ids) BETWEEN 1 AND 100),
      claim_draft jsonb NOT NULL CHECK (jsonb_typeof(claim_draft) = 'object'),
      target_record_key text NOT NULL CHECK
        (char_length(target_record_key) BETWEEN 1 AND 256),
      proposer_subject_id uuid NOT NULL REFERENCES subjects(user_id),
      rationale text NOT NULL CHECK (char_length(rationale) BETWEEN 1 AND 4000),
      state text NOT NULL DEFAULT 'proposed' CHECK (state IN
        ('proposed','approved','rejected')),
      decided_by uuid NULL REFERENCES subjects(user_id),
      decision_reason text NULL CHECK (decision_reason IS NULL
        OR char_length(decision_reason) BETWEEN 1 AND 2000),
      attestation_hash char(64) NULL CHECK (attestation_hash IS NULL
        OR attestation_hash ~ '^[0-9a-f]{64}$'),
      publish_package_id uuid NULL REFERENCES sot_packages(package_id),
      supersedes_proposal_id uuid NULL REFERENCES graduation_proposals(proposal_id),
      proposed_at timestamptz NOT NULL DEFAULT now(),
      decided_at timestamptz NULL,
      CHECK (decided_by IS NULL OR decided_by <> proposer_subject_id),
      CHECK ((state = 'proposed') = (decided_at IS NULL)),
      CHECK ((state = 'proposed') = (decided_by IS NULL)),
      CHECK ((state = 'proposed') = (decision_reason IS NULL)),
      CHECK ((state = 'proposed') = (attestation_hash IS NULL)),
      CHECK (publish_package_id IS NULL OR state = 'approved')
    );
    CREATE INDEX ix_graduation_proposals_state
      ON graduation_proposals(state, proposed_at DESC);

    CREATE TABLE governance_settings (
      setting_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      setting_key text NOT NULL CHECK (setting_key ~ '^[a-z][a-z0-9._]{1,127}$'),
      version integer NOT NULL CHECK (version > 0),
      value_type text NOT NULL CHECK (value_type IN
        ('integer','decimal','boolean','string','duration_hours')),
      value jsonb NOT NULL,
      updated_by uuid NOT NULL REFERENCES subjects(user_id),
      reason text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 2000),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK (
        (value_type IN ('integer','decimal','duration_hours')
          AND jsonb_typeof(value) = 'number')
        OR (value_type = 'boolean' AND jsonb_typeof(value) = 'boolean')
        OR (value_type = 'string' AND jsonb_typeof(value) = 'string')
      ),
      UNIQUE(setting_key, version)
    );
    CREATE INDEX ix_governance_settings_key
      ON governance_settings(setting_key, version DESC);

    CREATE OR REPLACE FUNCTION prevent_governance_history_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'governance history is immutable';
    END $$;
    CREATE OR REPLACE FUNCTION guard_research_package_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'research package history is immutable';
      END IF;
      IF (to_jsonb(NEW) - ARRAY['import_state','rejection_code','imported_at',
            'record_count','tier_composition'])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['import_state','rejection_code','imported_at',
            'record_count','tier_composition']) THEN
        RAISE EXCEPTION 'research package content is immutable';
      END IF;
      IF NEW.import_state IS DISTINCT FROM OLD.import_state AND NOT (
        (OLD.import_state = 'received'
          AND NEW.import_state IN ('validating','rejected')) OR
        (OLD.import_state = 'validating'
          AND NEW.import_state IN ('imported','rejected'))
      ) THEN
        RAISE EXCEPTION 'invalid research package import transition';
      END IF;
      RETURN NEW;
    END $$;
    CREATE OR REPLACE FUNCTION guard_gap_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'gap history is immutable';
      END IF;
      IF OLD.decline_reason IS NOT NULL
         AND NEW.decline_reason IS DISTINCT FROM OLD.decline_reason THEN
        RAISE EXCEPTION 'gap decline reason is immutable';
      END IF;
      IF OLD.lifecycle IN ('published','declined')
         AND NEW.lifecycle IS DISTINCT FROM OLD.lifecycle THEN
        RAISE EXCEPTION 'closed gap lifecycle is immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE OR REPLACE FUNCTION guard_graduation_proposal_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'graduation history is immutable';
      END IF;
      IF OLD.state <> 'proposed' THEN
        IF NOT (OLD.state = 'approved' AND OLD.publish_package_id IS NULL
                AND NEW.publish_package_id IS NOT NULL
                AND (to_jsonb(NEW) - 'publish_package_id')
                    = (to_jsonb(OLD) - 'publish_package_id')) THEN
          RAISE EXCEPTION 'decided graduation proposal is immutable';
        END IF;
        RETURN NEW;
      END IF;
      IF (to_jsonb(NEW) - ARRAY['state','decided_by','decision_reason',
            'attestation_hash','decided_at'])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['state','decided_by','decision_reason',
            'attestation_hash','decided_at']) THEN
        RAISE EXCEPTION 'graduation proposal content is immutable';
      END IF;
      RETURN NEW;
    END $$;

    CREATE TRIGGER research_records_immutable
      BEFORE UPDATE OR DELETE ON research_records
      FOR EACH ROW EXECUTE FUNCTION prevent_governance_history_mutation();
    CREATE TRIGGER gap_transitions_immutable
      BEFORE UPDATE OR DELETE ON gap_transitions
      FOR EACH ROW EXECUTE FUNCTION prevent_governance_history_mutation();
    CREATE TRIGGER governance_settings_immutable
      BEFORE UPDATE OR DELETE ON governance_settings
      FOR EACH ROW EXECUTE FUNCTION prevent_governance_history_mutation();
    CREATE TRIGGER research_sources_no_delete
      BEFORE DELETE ON research_sources
      FOR EACH ROW EXECUTE FUNCTION prevent_governance_history_mutation();
    CREATE TRIGGER research_packages_guarded
      BEFORE UPDATE OR DELETE ON research_packages
      FOR EACH ROW EXECUTE FUNCTION guard_research_package_mutation();
    CREATE TRIGGER gaps_resolution_guarded
      BEFORE UPDATE OR DELETE ON gaps
      FOR EACH ROW EXECUTE FUNCTION guard_gap_mutation();
    CREATE TRIGGER graduation_proposals_guarded
      BEFORE UPDATE OR DELETE ON graduation_proposals
      FOR EACH ROW EXECUTE FUNCTION guard_graduation_proposal_mutation();

    GRANT SELECT,INSERT,UPDATE ON research_sources,research_packages,
      review_tasks,graduation_proposals TO rtr_app;
    GRANT SELECT,INSERT ON research_records,gap_transitions,
      governance_settings TO rtr_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rtr_app;
    REVOKE UPDATE ON research_records,gap_transitions,governance_settings
      FROM rtr_app;
    REVOKE DELETE ON research_sources,research_packages,research_records,gaps,
      gap_transitions,review_tasks,graduation_proposals,governance_settings
      FROM rtr_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER graduation_proposals_guarded ON graduation_proposals;
    DROP TRIGGER gaps_resolution_guarded ON gaps;
    DROP TRIGGER research_packages_guarded ON research_packages;
    DROP TRIGGER research_sources_no_delete ON research_sources;
    DROP TRIGGER governance_settings_immutable ON governance_settings;
    DROP TRIGGER gap_transitions_immutable ON gap_transitions;
    DROP TRIGGER research_records_immutable ON research_records;
    DROP FUNCTION guard_graduation_proposal_mutation();
    DROP FUNCTION guard_gap_mutation();
    DROP FUNCTION guard_research_package_mutation();
    DROP FUNCTION prevent_governance_history_mutation();
    DROP TABLE governance_settings;
    DROP TABLE graduation_proposals;
    DROP TABLE review_tasks;
    DROP TABLE gap_transitions;
    DROP TABLE research_records;
    DROP TABLE research_packages;
    DROP TABLE research_sources;
    ALTER TABLE gaps
      DROP CONSTRAINT gaps_resolution_link_check,
      DROP CONSTRAINT gaps_decline_reason_state_check,
      DROP CONSTRAINT gaps_origin_run_check;
    DELETE FROM gaps WHERE origin = 'manual';
    UPDATE gaps SET lifecycle = CASE lifecycle
      WHEN 'assigned' THEN 'triaged'
      WHEN 'answered' THEN 'triaged'
      WHEN 'published' THEN 'resolved'
      WHEN 'declined' THEN 'dismissed'
      ELSE lifecycle END
    WHERE lifecycle IN ('assigned','answered','published','declined');
    DROP INDEX ix_gaps_owner;
    DROP INDEX ix_gaps_queue;
    ALTER TABLE gaps
      DROP COLUMN decline_reason,
      DROP COLUMN resolving_version_id,
      DROP COLUMN closed_at,
      DROP COLUMN answered_at,
      DROP COLUMN due_at,
      DROP COLUMN assigned_at,
      DROP COLUMN triaged_at,
      DROP COLUMN priority,
      DROP COLUMN origin;
    ALTER TABLE gaps ALTER COLUMN answer_run_id SET NOT NULL;
    ALTER TABLE gaps DROP CONSTRAINT gaps_reason_category_check;
    ALTER TABLE gaps ADD CONSTRAINT gaps_reason_category_check
      CHECK (reason_category IN
        ('no_evidence','denied_or_unavailable','insufficient_confidence',
         'stale_only','grounding_failed'));
    ALTER TABLE gaps DROP CONSTRAINT gaps_lifecycle_check;
    ALTER TABLE gaps ADD CONSTRAINT gaps_lifecycle_check CHECK (lifecycle IN
      ('open','triaged','resolved','dismissed'));
    GRANT DELETE ON gaps TO rtr_app;
    """)
