# TIP-006 Completion Report

STATUS: DONE

## REQUIREMENT COVERAGE

- Implemented: 2 — REQ-011, REQ-015.
- Advanced: 6 — REQ-008, REQ-016, REQ-022, REQ-023, REQ-025, REQ-033.
- Missing within TIP-006 scope: 0.
- Retrieval/RAG, template rendering, research graduation and Files UI remain in
  their later TIPs by design.

## FILES CHANGED

- Schema: `v2/apps/backend/migrations/versions/0006_sot_publish_provenance.py`.
- SOT domain/service/API: `v2/apps/backend/src/rtr_copilot/sot/`.
- Kernel guard: `v2/apps/backend/src/rtr_copilot/commands/sot_kernel_guard.py`.
- Wiring/config: `api/main.py`, `config.py`, `repositories/resources.py`,
  `.env.example`, `compose.yaml`.
- Tests/fixtures: `sot_fixtures.py`, `test_sot_unit.py`, `test_sot_api.py`,
  `test_sot_integration.py`, and the schema-revision assertions in
  `test_data_integration.py`.
- Operations: `backup-data.sh`, `restore-data.sh`,
  `verify-data-integration.sh`.
- Documentation: `v2/README.md` and this report.

## MIGRATION

- Head: `0006_sot_publish_provenance`.
- Upgrade and downgrade both executed successfully against PostgreSQL 16.
- Added `sot_packages`, `records`, `record_versions`, `evidence_spans`,
  `sot_publish_runs`, `sot_active_revisions`, and `sot_reindex_outbox`.
- Added stable-key/current-pointer constraints, active/provenance/freshness
  indexes, immutable-content triggers, runtime grants and DELETE denials.
- Active revision is one row per `source_key`; publish uses a transaction plus a
  per-source advisory lock.

## TEST RESULTS

- Backend regression: 153 passed; 21 integration/environment tests skipped in
  the local unit run.
- TIP-006 focused unit/API: 20 passed.
- TIP-006 PostgreSQL integration: 4 passed.
- Full data integration: 20 passed, including six migration revisions, six
  revision fixtures, rollback DDL, existing TIP-003/004/005 tests and TIP-006.
- Web: ESLint pass, TypeScript pass, Vitest 1/1 pass, Next production build pass.
- Ruff: pass. Strict mypy: pass. Compose validation and shell syntax: pass.
- Trivy: zero detected OS or Python vulnerabilities.
- Deployment smoke: API, worker and web rebuilt/restarted healthy; API and web
  readiness both returned `ok=true,status=ready`. API/worker runtime environments
  both resolved revision `0006_sot_publish_provenance` and all SOT settings.

| AC | Result | Evidence |
|---|---|---|
| AC-01 Schema | PASS | upgrade/downgrade/head and DB constraints |
| AC-02 Package safety | PASS | deterministic and hostile-member unit tests |
| AC-03 Provenance | PASS | bounded validation findings and publish integration |
| AC-04 Trust zone | PASS | strict `trust_zone=sot` and typed fact/verification states |
| AC-05 Attestation | PASS | HMAC, identity, policy, expiry and future-time verification |
| AC-06 Authorization | PASS | anonymous/staff API denial; curator policy boundary |
| AC-07 Atomicity | PASS | injected failures after candidate insert and pointer swap |
| AC-08 Concurrency/idempotency | PASS | two publishers, one activation/outbox/audit |
| AC-09 Version integrity | PASS | collision, overlap, rollback and direct-tamper rejection |
| AC-10 Policy-filtered read | PASS | active-only query plus classification-escalation regression |
| AC-11 Freshness | PASS | injected-clock current/stale/expired/unknown tests |
| AC-12 Outbox | PASS | exactly one correlated durable request |
| AC-13 Audit | PASS | stage/validate/publish/read-deny append path |
| AC-14 Kernel guard | PASS | live kernel blocked; before/after fingerprints equal |
| AC-15 Recovery | PASS | seven table counts plus pointer/evidence/checksum invariants |
| AC-16 Health | PASS | all gates above |

## SECURITY/ATOMICITY EVIDENCE

- Parser is rooted, single-level, non-symlink, bounded and checksum-complete; it
  never executes package content or resolves package references.
- Production rejects absent/default/short/shared SOT signing secrets.
- Compose keeps API and worker schema/SOT configuration in parity; the local
  development stack also points at migration head `0006`.
- Attestation is verified immediately before activation.
- Candidate rows require `staged` lifecycle and are excluded from active reads.
- Every revision snapshots owner/classification/scope/fact state/ACL in the
  immutable version row; the canonical checksum also binds those fields,
  confidence, freshness and the complete evidence source/security projection.
- A revision security escalation updates both `records` and `resources` before
  activation in the same transaction. Regression coverage proves a staff subject
  cannot read a newly restricted value through stale public/internal attributes,
  and the new ACL replaces the old ACL atomically.
- Failure rolls back resources, ACLs, versions, evidence, pointer, audit and
  outbox together; the prior revision remains visible.
- Database triggers reject direct changes to any record-version/evidence field
  except the explicit lifecycle state machine. Runtime has no DELETE privilege on
  any of the seven canonical SOT tables; the recovery drill re-applies and checks
  those denials.
- Recovery validates active pointers, evidence linkage, checksum shapes and
  equality of the active version security snapshot with `records`/`resources`.
- Error envelopes expose stable codes/request IDs, not local paths, signatures,
  secrets or hidden-result counts.

## REAL-KERNEL GUARD RESULT

- Decision: `blocked`.
- Reasons observed: `record_not_found`, `publish_token_stale`,
  `source_fingerprint_coverage_missing`.
- Read-only proof: before and after fingerprints were identical.
- No file under `/Users/os/RtR/kernel`, any KnowledgeBase registry, or GOI export
  was written or repaired.

## ISSUES

- P3 / dependency owners: existing Starlette/httpx and SWIG deprecation warnings
  remain; they do not affect gate results.
- No P0, P1 or P2 issue remains in TIP-006 scope.

## DEVIATIONS

- Detached-attestation circularity is resolved by defining
  `manifest_sha256` as the canonical manifest identity with only the
  attestation member SHA replaced by 64 zeroes. The actual attestation member
  byte size/SHA is still present in `manifest.json` and verified first; the HMAC
  then binds the normalized manifest identity and payload identity. This is
  deterministic and covered by mutation tests.
- No Blueprint-level schema or policy-contract deviation was introduced.

## SUGGESTIONS

- TIP-007 should consume only `sot_reindex_outbox`, never scan candidate tables.
- Add an operator-only package builder/signing command before production rollout;
  keep the current live kernel blocked until business provenance, token and
  fingerprint coverage are independently repaired and approved.
