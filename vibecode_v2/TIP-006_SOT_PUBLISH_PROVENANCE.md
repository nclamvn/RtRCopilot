# TIP-006 · SOT Publish & Provenance

## HEADER

- **TIP-ID:** TIP-006
- **Project:** RtR Copilot V2
- **Module:** `v2/apps/backend` + PostgreSQL + SOT adapter/worker contracts
- **Depends on:** TIP-003 VERIFIED; TIP-004 VERIFIED
- **Priority:** P0
- **Status:** VERIFIED · READY

## CONTEXT

- Working directory: `/Users/os/RtR/KnowledgeBase/RtR_Copilot`
- Blueprint: `vibecode_v2/02_BLUEPRINT_RTR_COPILOT_V2.md`
- Task Graph: `vibecode_v2/03_TASK_GRAPH.md`
- Identity/policy contract: `vibecode_v2/TIP-003_IDENTITY_POLICY.md`
- Data/object/audit contract:
  `vibecode_v2/TIP-004_DATA_OBJECT_AUDIT_FOUNDATION.md`
- Ingestion contract: `vibecode_v2/TIP-005_INGESTION_RENDITIONS.md`
- Requirements directly advanced: REQ-008, REQ-011, REQ-015, REQ-016,
  REQ-022, REQ-023, REQ-025, REQ-033.

TIP-006 creates the canonical SOT publish boundary used later by retrieval,
documents and governance. It does not implement RAG, Ask UI, research graduation
or bulk KnowledgeBase migration.

The live kernel is not an acceptable activation fixture at TIP start:

- validation fails because `L3F.ENT.002` lacks `provenance_level`;
- the publish token is stale/blocked;
- source fingerprints cover only part of the canonical source tree;
- existing GOI exporters can run without enforcing validation or the publish token.

These conditions must be represented as fail-closed tests. Builder must not repair
business facts, infer provenance, mint a new real publish token or activate the
current GOI packs.

## TRUST BOUNDARY

1. V2 is a read-only consumer of an explicit adapter package. It never imports an
   arbitrary kernel directory, executes kernel Python, trusts an exporter exit code
   or reads `_dist` output as canonical.
2. Every package declares `trust_zone=sot`, schema version, package ID, immutable
   revision, generated timestamp, manifest checksum and producer identity.
3. SOT, research and private-context records never share a publish run or active
   revision.
4. Copilot/API handlers cannot mutate active SOT facts. Writes happen only through
   a curator-authorized publish service and immutable version tables.
5. Validation, provenance, source fingerprints, classification/ACL and DLP all pass
   before a revision can become active.
6. Any failure leaves the previous active revision fully visible and the candidate
   revision fully invisible.

## TASK

### 1. Canonical database model

Add one additive Alembic migration and typed repository/domain models for:

#### `sot_packages`

- immutable `package_id`, `source_key`, `revision`, `schema_version`;
- `trust_zone` constrained to `sot`;
- manifest and payload SHA-256;
- producer, generated timestamp and ingestion timestamp;
- lifecycle: `staged`, `validating`, `validated`, `publishing`, `active`,
  `rejected`, `superseded`;
- validation summary, rejection code and counts only—no raw secret/content dump;
- uniqueness on `(source_key, revision)` and immutable checksum identity.

#### `records`

- stable UUID and stable external `record_key`;
- source/package identity, owner and security attributes;
- classification, department/project scope;
- lifecycle and current active version pointer;
- timestamps and soft-retention state consistent with TIP-004.

#### `record_versions`

- immutable version UUID, record UUID, package/revision;
- typed value payload plus normalized searchable text;
- provenance level, confidence and verification state;
- valid/effective time interval and freshness state;
- evidence/source references and content checksum;
- supersedes pointer and deterministic version ordinal;
- no in-place mutation of published payload.

#### `evidence_spans`

- immutable span UUID linked to record version;
- source document/version/blob checksum where available;
- locator schema supporting page, sheet/cell, slide/shape, paragraph/table,
  region/bounding box and media timecode;
- quoted/normalized evidence text, evidence checksum and source URI/path label;
- classification/security projection not weaker than its record version.

#### `sot_publish_runs`

- run UUID, package/revision, actor, request ID;
- state machine, validation report, started/finished timestamps;
- candidate and previous active revision;
- deterministic counts/checksums;
- failure code/fingerprint and append-only audit correlation.

Add constraints/indexes needed for stable keys, active revision lookup, provenance,
freshness and evidence linkage. Do not add vector embeddings or RAG chunks in this
TIP.

### 2. Versioned adapter package

Define a deterministic, versioned JSON package contract with:

- `manifest.json`;
- `records.jsonl`;
- optional `evidence.jsonl`;
- `source_hashes.json`;
- `publish_attestation.json`.

The manifest lists every member path, byte size and SHA-256. Package parsing must:

- accept only a configured local staging root;
- reject path traversal, symlink, duplicate member, unknown required-member shape,
  oversized member/package and checksum mismatch;
- parse with bounded line/record/value sizes;
- reject duplicate record/version/evidence keys;
- reject unknown schema major versions;
- never execute package content or follow network/file references.

Provide a small valid synthetic fixture and hostile/invalid fixtures in tests.
Do not copy company facts into fixtures.

### 3. Validation and provenance gate

Validation returns a typed report with stable machine-readable codes and checks:

- manifest/member checksum completeness;
- package/revision identity and monotonicity;
- record schema and deterministic content checksum;
- allowed provenance vocabulary;
- required provenance for every publishable record version;
- evidence resolvability and evidence checksum;
- source fingerprint coverage for every referenced canonical source;
- classification/owner/ACL completeness;
- validity interval consistency and freshness classification;
- no SOT record labelled only as research/private context;
- no `flagged`, `placeholder`, `unspecified` or unresolved-conflict fact activated;
- configurable rule preventing `claim` from masquerading as approved/verified;
- no classification downgrade between record, evidence and referenced source.

The validator must be pure/deterministic for the same package and configuration.
It returns all bounded findings instead of failing on the first item.

### 4. Publish attestation

`publish_attestation.json` binds:

- package ID/revision;
- manifest and payload checksums;
- validator/schema/policy versions;
- validation timestamp;
- curator subject ID;
- decision (`approved`);
- optional expiry;
- detached HMAC signature using a configured secret for the initial private
  deployment.

Production config must fail closed if the signing secret is absent, default,
too short or shared with session/object-store credentials. Tests may use an
explicit test-only secret.

Attestation verification occurs immediately before database activation. Changing
any package member, policy version or attestation field invalidates activation.

### 5. Atomic stage, validate and publish

Implement a service/command flow:

```text
stage package
  → validate package and provenance
  → verify curator authorization
  → verify signed attestation
  → insert immutable candidate records/versions/evidence
  → project resource + ACL attributes
  → atomically swap active revision
  → append audit event and durable reindex outbox request
```

Rules:

- PostgreSQL is source of truth for publish state.
- Use transaction plus row/advisory lock per `source_key`.
- Same package checksum is idempotent and returns the existing result.
- Same revision with different checksum is a permanent conflict.
- Older/equal revision cannot replace a newer active revision.
- Concurrent publishers yield one winner without partial visibility.
- Candidate rows are never returned by active SOT repository queries.
- Failure at every injected step preserves the prior active revision.
- Reindex is an outbox contract only; TIP-007 consumes it.
- Audit contains actor, package/revision, prior/new checksum, counts, decision,
  request/run IDs and sanitized findings.

### 6. Authorization and API/CLI boundary

Expose curator/admin-only typed endpoints or commands for:

- stage package;
- validate candidate;
- publish an already validated candidate with attestation;
- inspect publish-run status and sanitized validation findings;
- list/get active SOT records and evidence through policy-filtered repository/API.

Requirements:

- all mutations require a fresh authenticated corporate subject and policy action
  such as `curate`/`publish`;
- no direct SQL/admin endpoint for editing records or record versions;
- list/get applies TIP-003 policy before returning record metadata or values;
- response never exposes local paths, signing secret, raw attestation signature or
  hidden-record counts;
- OpenAPI schemas include request ID and machine-readable error codes.

### 7. Freshness and conflict representation

Store and calculate, without mutating published values:

- `effective_from`, optional `effective_to`;
- `freshness_policy`, `freshness_due_at`;
- state `current`, `stale`, `expired`, `unknown`;
- supersession chain;
- explicit conflict/rejection findings.

No silent “latest timestamp wins.” Conflicting record keys or overlapping effective
intervals require deterministic rejection or an explicit pre-publish resolution in
the package.

### 8. Real-kernel guard probe

Create a read-only verification probe for the current kernel/GOI boundary. It may
inspect configured paths but must not import them. The probe must demonstrate that
the current live package is non-activatable when validation/token/fingerprint
conditions are not met.

The probe is evidence for VERIFY, not a production adapter and not permission to
alter `/Users/os/RtR/kernel`.

### 9. Tests and operational evidence

Tests must cover at least:

- valid synthetic package stage → validate → publish → read;
- invalid/stale/missing attestation;
- checksum/member/source-fingerprint mismatch;
- missing/unknown provenance and claim-as-approved;
- unresolved/invalid evidence locator;
- missing owner/classification/ACL;
- classification downgrade;
- duplicate keys and revision collision;
- old revision rollback attempt;
- idempotent replay;
- two concurrent publishes;
- injected failure before/during activation;
- candidate invisibility;
- prior revision preservation;
- policy-denied list/get/publish;
- cross-trust-zone package rejection;
- no local-path/signature leakage;
- durable audit and reindex outbox correlation;
- real-kernel guard reports blocked without modifying source.

Update backup/restore and reconciliation verification so all new tables and active
revision invariants are included.

## ACCEPTANCE CRITERIA

1. **AC-01 — Schema:** migration upgrade/downgrade succeeds and constraints prevent
   mutable/ambiguous active SOT state.
2. **AC-02 — Package safety:** valid deterministic fixture parses; traversal,
   symlink, oversize, duplicate and checksum fixtures fail closed.
3. **AC-03 — Provenance:** every active version has allowed provenance and complete
   referenced evidence/source fingerprints.
4. **AC-04 — Trust zone:** research/private packages and unsupported fact states
   cannot activate as SOT.
5. **AC-05 — Attestation:** any package/policy/decision/signature mutation prevents
   publication.
6. **AC-06 — Authorization:** anonymous/staff cannot publish; authorized curator can
   publish only a validated, attested candidate.
7. **AC-07 — Atomicity:** injected failures leave zero candidate visibility and
   preserve the previous active revision.
8. **AC-08 — Concurrency/idempotency:** concurrent/replayed publish yields one
   active revision, no duplicate version/evidence or audit ambiguity.
9. **AC-09 — Version integrity:** rollback/revision collision and overlapping
   unresolved validity intervals are rejected.
10. **AC-10 — Policy-filtered read:** active record/evidence APIs never reveal a
    denied record, value, locator or hidden-result count.
11. **AC-11 — Freshness:** current/stale/expired/unknown is deterministic from
    stored policy and an injected clock.
12. **AC-12 — Outbox:** successful activation durably emits exactly one correlated
    reindex request; failed activation emits none.
13. **AC-13 — Audit:** stage/validate/reject/publish/read-deny events are append-only,
    correlated and sanitized.
14. **AC-14 — Real-kernel guard:** current invalid/stale-token kernel is reported
    blocked and no file under `/Users/os/RtR/kernel` changes.
15. **AC-15 — Recovery:** backup/restore verification includes all SOT tables,
    checksums, active pointers and evidence links.
16. **AC-16 — Health:** Ruff, strict mypy, unit/integration tests, migration check,
    security regression and existing TIP-001..005 gates pass with exact counts.

## CONSTRAINTS

- Do not modify `/Users/os/RtR/kernel`, KnowledgeBase registries or GOI exports.
- Do not mint/refresh a real publish token or infer missing business provenance.
- Do not implement embeddings, vector index, RAG, Ask, research graduation, Files
  UI or Document OS.
- Do not expose a generic record mutation endpoint.
- Do not weaken TIP-003 policy or TIP-004/TIP-005 immutability and audit contracts.
- Reuse existing Unit of Work, repositories, resource projection, ACL, audit,
  outbox and configuration patterns.
- Any schema/contract change outside the approved Blueprint must be reported as L2
  and must not be implemented silently.

## REPORT FORMAT

Create `vibecode_v2/TIP-006_COMPLETION_REPORT.md` containing:

- `STATUS: DONE | PARTIAL | BLOCKED`
- `REQUIREMENT COVERAGE`: implemented/advanced/missing REQ-ID counts
- `FILES CHANGED`
- `MIGRATION`
- `TEST RESULTS`: each AC with pass/fail and exact test counts
- `SECURITY/ATOMICITY EVIDENCE`
- `REAL-KERNEL GUARD RESULT`
- `ISSUES`: severity and owner
- `DEVIATIONS`
- `SUGGESTIONS`
