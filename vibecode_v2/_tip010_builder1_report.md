# TIP-010 Builder 1 Completion Report — schema layer (migration 0009, models, repository)

STATUS: DONE

## FILES CHANGED

Created:
- `v2/apps/backend/migrations/versions/0009_governance_research.py` — all 8 DATA MODEL tables (research_sources, research_packages, research_records, gaps extension, gap_transitions, review_tasks, graduation_proposals, governance_settings), CHECKs, indexes, immutability triggers, least-privilege grants, full downgrade.
- `v2/apps/backend/src/rtr_copilot/governance/__init__.py` — new governance domain package.
- `v2/apps/backend/src/rtr_copilot/governance/models.py` — typed domain models for the governance schema (house convention: Pydantic StrictModel; see DEVIATIONS D1).
- `v2/apps/backend/src/rtr_copilot/repositories/governance.py` — `GovernanceRepository` storage layer with typed `GovernanceError` codes; no business logic beyond storage invariants.
- `v2/apps/backend/tests/test_governance_unit.py` — 7 unit tests (single alembic head, model round-trips, closed zone/tier vocabularies, gap transition matrix, cursor codec, setting type validation); run without Postgres.
- `v2/apps/backend/tests/test_governance_integration.py` — 8 integration tests (skip without `INTEGRATION_DATABASE_DSN`, house pattern): migration head + table presence + disjoint index namespace, fingerprint idempotency, research record/package immutability + zone CHECK, gap dedupe/lifecycle/append-only history, immutable decline reason, review-task upsert/reopen, graduation separation-of-duties + immutable decisions + one-shot publish-submission link, settings versioning.

Modified (wiring the codebase's own mechanisms to the new head — no TIP-001…009 behavior change):
- `v2/apps/backend/src/rtr_copilot/config.py` — `expected_schema_revision` → `0009_governance_research` (same mechanism every prior migration used; TIP-009 precedent commit c90e4cf).
- `v2/.env.example` — `EXPECTED_SCHEMA_REVISION` → 0009.
- `v2/apps/backend/tests/test_data_integration.py` — the two hard-coded head-revision strings → 0009 (exact TIP-009 precedent).
- `v2/scripts/backup-data.sh` — 7 new tables added to the row-count manifest (backup/restore coverage is in the TIP DATA MODEL section).
- `v2/scripts/restore-data.sh` — restored-revision check → 0009; new tables added to restored row-count comparison; post-restore grant re-application extended (REVOKE DELETE on all 8 governance tables incl. `gaps`, REVOKE UPDATE on the 3 insert-only tables).
- `v2/scripts/verify-data-integration.sh` — 0009 revision-fixture step (upgrade → table probe → downgrade 0008 → probe absent → re-upgrade), `test_governance_integration.py` added to the containerized pytest list, summary counts bumped (migrations=9, revision_fixtures=9, tests=45). `bash -n` clean on all three scripts.

Migrations 0001–0008, all existing models/repositories/services: untouched.

## TEST RESULTS

Official gates (before → after), run in `v2/apps/backend`:
- `uv run ruff check .` — PASS → PASS ("All checks passed!")
- `uv run mypy` — 68 files, 0 issues → **71 files, 0 issues** (strict; zero new ignores)
- `uv run pytest` — 175 passed / 38 skipped → **182 passed / 46 skipped** (+7 unit, +8 integration-skipped; unit phase stays green without infra)
- `uv run alembic heads` — single head `0009_governance_research (head)` (also pinned by a unit test)

Live-database verification (this container has PostgreSQL 16 + pgvector; I created an owner role, a `rtr_app` LOGIN runtime role and a database, mirroring compose `init-runtime.sh`):
- `alembic upgrade head`, `downgrade 0008 → upgrade head` over a **populated** DB, and `upgrade head → downgrade base → upgrade head` on a fresh DB: all PASS; all 7 new tables present.
- `pytest tests/test_governance_unit.py tests/test_governance_integration.py` with `INTEGRATION_DATABASE_DSN`: **15 passed**.
- Regression proof on the 0009 schema: `pytest tests/test_data_integration.py tests/test_sot_integration.py tests/test_rag_integration.py tests/test_governance_integration.py` → **30 passed, 1 failed**; the single failure is `test_real_minio_object_persists_with_database_metadata`, which needs a live MinIO absent in this container (fails identically on 0008 — infra-missing, not a regression). All TIP-007 RAG tests pass, proving honest-null gap inserts still work against the extended `gaps` table.

## ISSUES

- LOW: `make verify` / `verify-data-integration.sh` (docker compose + MinIO) could not be executed in this container; my script edits are mechanical mirrors of the 0008 step and are `bash -n` clean, but the Contractor should run the containerized gate.
- LOW: one MinIO-dependent pre-existing test fails locally for lack of MinIO only (see above).

## DEVIATIONS (L1)

- D1 — "SQLAlchemy models": this codebase has **no** SQLAlchemy declarative/metadata layer anywhere; every domain module (sot, documents, resources) uses Pydantic models + textual SQL repositories over `AsyncSession`. I followed the house convention exactly (`governance/models.py` = Pydantic StrictModel; repository = `text()` SQL) instead of introducing a first-ever declarative metadata registry, which would have been an architecture change. There is consequently no "metadata registration" step — none exists for documents/sot either.
- D2 — `gaps` already exists (migration 0007). 0009 **extends** it (new columns origin/priority/SLA timestamps/resolution linkage, widened lifecycle + reason_category CHECKs, `answer_run_id` made nullable for manual gaps, DELETE revoked) rather than creating a duplicate table. TIP-007 vocabulary (`resolved`/`dismissed`, its upsert path) is preserved; downgrade maps new states back and restores the original constraints/grants.
- D3 — revision-pin wiring (config.py, .env.example, test_data_integration.py) and backup/restore/verify script coverage were updated because the codebase's own mechanisms hard-pin the head revision and table manifests; leaving them at 0008 would fail loudly against a 0009 database. Matches the TIP-009 precedent commit and the DATA MODEL section's "backup/restore coverage" requirement.
- D4 — `gap_transitions` carries a `sequence bigint GENERATED ALWAYS AS IDENTITY` (audit_events precedent): `now()` is transaction-fixed, so multiple transitions in one transaction would otherwise have no stable order.
- D5 — graduation lineage column is `publish_package_id` FK → `sot_packages(package_id)` set once via `attach_publish_submission` (trigger permits exactly that single change on an approved proposal); "policy-denied research record" screening at proposal time is a service-layer concern (policy engine), not schema — repository enforces exists+imported.

## SUGGESTIONS (for Contractor / Builders 2–3)

- Repository API surface (`rtr_copilot.repositories.governance`): all methods take an `AsyncSession` (compose them inside one `UnitOfWork.transaction()`); typed failures raise `GovernanceError(code)` with codes: `package_fingerprint_conflict`, `package_transition_invalid`, `package_state_conflict`, `rejection_code_required`, `invalid_question_digest`, `answer_run_required`, `invalid_cursor`, `gap_not_found`, `gap_state_unsupported`, `gap_transition_invalid`, `gap_owner_required`, `gap_resolution_record_required`, `record_version_not_found`, `record_version_not_active`, `gap_decline_reason_required`, `gap_transition_conflict`, `review_task_state_conflict`, `research_records_required`, `research_record_not_graduatable`, `superseded_proposal_not_found`, `proposal_not_found`, `proposal_already_decided`, `proposer_cannot_decide`, `invalid_attestation_hash`, `proposal_submission_conflict`, `setting_value_type_mismatch`.
- Key methods Builder 2/3 will use: `register_package` (fingerprint-idempotent, returns `PackageIntake(package, created)`), `set_package_state` (received→validating→imported|rejected only), `insert_record` (immutable; no update/delete exists), `create_or_increment_gap` (dedupe on (digest, requester, classification); occurrence counter), `transition_gap` (legal matrix in `ALLOWED_GAP_TRANSITIONS`; `answered` requires an **active** `record_versions` row; appends the immutable transition row itself), `list_gaps` (state/owner/priority filters + keyset cursor via `encode_gap_cursor`; wrap the cursor in the HMAC-signed API cursor pattern like ingestion/documents before exposing it), `upsert_review_task` (UNIQUE(queue_kind, record_version_id); completed→reopened on reassign), `create_proposal`/`decide_proposal`/`attach_publish_submission`, `get_setting`/`set_setting`/`list_setting_versions` (append-only versions; `validate_setting_value` enforces types incl. non-negative `duration_hours`).
- Research records deliberately do NOT join `resources` (zone separation, D-010-02); policy scoping for research reads should bind at `research_sources` level or via a research-specific check in the service layer — Contractor may want to confirm that choice before Builder 2 builds retrieval.
- Setting-value bounds beyond typing (min/max per key, e.g. SLA windows) are left to the admin service layer; add a bounds table or per-key registry there if REQ needs hard DB bounds.
- Audit events for import/reject, transitions, assignments, proposal decisions and settings changes are Builder 2's service-layer duty via `AuditRepository().append` in the same transaction — the repository intentionally does not auto-audit (matches ResourceRepository/ObjectRepository split).
- TIP-007's `rag/answering.py` gap upsert still works unchanged; Builder 2 may later route it through `create_or_increment_gap` for one code path, but that is a TIP-010 service decision, not required.

## ADDENDUM — Contractor VERIFY finding: AC18 restore proof (refine completed)

**Finding (pre-existing harness bug, not a TIP-010 regression):** the containerized
gate's AC18 restore proof failed with `restore_proof=f`. Root cause: the pytest
phase intentionally leaves deterministic document-OS residue (templates with
`integration.<uuid>` keys, 3 render_jobs incl. one failed, generated_files,
approvals, one issuance) in the same `$verify_database` that AC18 then seeds with
exactly one row per table; the proof's `count(*)=1` assertions therefore see 2-4
rows. Contractor's controlled reproduction confirms the identical failure on MAIN
(pre-TIP-010) at both revisions 0008 and 0009 on fresh databases
(templates|2, render_jobs|3, generated_files|2, issuances|1 in every
combination) — a pre-existing AC18 ordering assumption made newly visible;
`test_governance_integration.py` is not the cause.

**Fix (surgical, `v2/scripts/verify-data-integration.sh` only):** AC18 is now
hermetic. A dedicated database `${verify_database}_ac18` is created and migrated
to head via a new parameterized `run_migration_for <database> <args...>` helper
(the existing `run_migration` and the migration ladder are untouched); the AC18
seed runs through a new `ac18_sql` helper against that database; `pg_dump` reads
from `$ac18_database`; the restore side still uses `$restore_database` and the
proof SQL (counts=1, checksum lineage, DELETE-privilege checks), pytest phase,
runtime-denial loop and final echo are byte-for-byte unchanged; `cleanup()` now
also terminates connections to and drops `$ac18_database`. `bash -n` clean.

**Verification:** full `./scripts/verify-data-integration.sh` rerun end-to-end
against the warm compose stack (postgres/minio/redis healthy): containerized
pytest phase `45 passed`, AC18 restore proof passed, cleanup dropped all
`rtr_verify*` databases (0 remain). Final line:

```
DATA INTEGRATION PASS · migrations=9 · revision_fixtures=9 · failing_ddl_rollback=1 · tests=45 · document_os_runtime_probes=2 · formats=14 · required_outputs=31 · private_engine_proofs=4 · policy_scenarios=48 · tip009_nonempty_restore=1 · runtime_denials=18
```

## ADDENDUM 2 — Contractor VERIFY finding #2: SOT integrity residue from governance test fixtures (refine completed)

**Finding:** the production restore drill (`scripts/restore-data.sh`) failed exit 11
at the SOT broken-links check against a DB populated by the integration suites:
4 `records` rows (all `GOV.` keys from `tests/test_governance_integration.py`)
were left `lifecycle='active'` with `current_version_id` NULL — my
`insert_sot_version` fixture never set the current-version pointer and marked
even the staged-version probe's record as active, violating the TIP-006
invariant "active record ⇒ existing active current version". Audit of the other
governance suites found one mirrored hole in Builder 2's
`tests/test_governance_service_integration.py` (`lifecycle="staged",
set_current=False` creates a brand-new record that stays active with a NULL
pointer); Builder 3/4a's admin fixture already repoints correctly and needed no
change.

**Fix (test files only; no production code, migrations or scripts):**
- `tests/test_governance_integration.py` — `insert_sot_version` now derives
  `records.lifecycle`/`resources.lifecycle_state` from the version lifecycle
  (`active`/`active` vs `staged`/`draft`) and, for active versions, repoints
  `records.current_version_id` (+`updated_at`) at the inserted version.
- `tests/test_governance_service_integration.py` — the fixture's new-record
  branch now inserts `records`/`resources` as `staged`/`draft` unless the call
  both sets the current pointer and inserts an active version
  (`record_state = "active" if (set_current and lifecycle == "active") else
  "staged"`). No assertion weakened; all tests prove the same behaviors
  (the staged probes only ever read `record_versions.lifecycle`).

**Verification (this container, native infra: PG :5432, repro-minio :9002,
repro-redis :6380):**
- Unit gates: `ruff` PASS, `mypy` 83 files 0 issues, `pytest` 210 passed /
  71 skipped (previous slice baseline 182/46; growth is Builders 2-4 suites).
- Fresh-DB proof: created `rtr_v2_hygiene`, migrated to head, ran
  documents + sot + rag + all three governance integration suites in sequence
  (43 passed, 0 skipped), then ran both restore-drill broken-link queries
  (restore-data.sh lines 245-256) verbatim: documents broken links = **0**,
  SOT broken links = **0**, with 17 governance-fixture records present
  (12 active, all with current pointers; 2 staged probes with NULL pointer,
  correctly exempt). The `rtr_v2_hygiene` database is left in place for
  Contractor inspection.
