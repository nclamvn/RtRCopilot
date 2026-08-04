# TIP-024: Pilot Corpus & Provenance Campaign

## HEADER

- **TIP-ID:** TIP-024
- **Project:** RtR Copilot V2
- **Module:** Pilot rollout · Files · Document OS · Research · SOT provenance
- **Depends on:** TIP-006, TIP-008, TIP-009, TIP-010, TIP-013B, TIP-018, TIP-023
- **Priority:** P0 rollout
- **Issued:** 04/08/2026
- **Status:** COMPLETE · READY-with-deferred

## CONTEXT

- Working directory: `RtR_Copilot/v2`
- Approved plan: `vibecode_v2/04_CONTINUATION_PLAN_2026-08-04.md` §7
- Live local baseline at issue time:
  - 219 active SOT records and 219 search chunks;
  - 8 strict records and 211 records carrying `needs_double_check`;
  - all 219 records are assigned to the TIP-013B migration placeholder, not a
    named human domain owner;
  - 0 templates, 0 research sources/packages/records;
  - 6 tiny TIP-018 PDF fixtures, not a representative file corpus.
- Available real inputs:
  - four company templates plus `templates/registry.yaml`;
  - more than 1,200 viewable PDF/DOCX/XLSX/PPTX/image artifacts in the local
    KnowledgeBase; no audio/video artifact was found;
  - `Dataset_CongNgheChienLuoc`: 124 claims, span gate 124/124 PASS, 110 current
    sourced claims which deterministically reconcile to 70 research records.

## REQUIREMENTS MATRIX

| REQ-ID | Requirement | Priority | Source |
|---|---|---:|---|
| REQ-024-01 | Expose a live, read-only pilot corpus/provenance readiness view to authorized administrators | P0 | TIP-024 objective |
| REQ-024-02 | Distinguish strict, caveated, placeholder-owned and high-risk SOT records without changing provenance | P0 | H-024-01 + A3 |
| REQ-024-03 | Convert the CNCL refinery dataset into a deterministic, checksum-bound research package | P0 | pilot Research target |
| REQ-024-04 | Preserve exact corroborated/disputed/honest states during research import | P0 | Refinery v1.2 |
| REQ-024-05 | Adapt the four real company templates to V2 without freezing stale fact values | P0 | template pilot target |
| REQ-024-06 | Block caveated facts from official/legal output; make any allowed internal caveat and owner visible | P0 | H-024-01 |
| REQ-024-07 | Onboard a manifest-bound representative local file batch through the existing ingestion path | P0 | file pilot target |
| REQ-024-08 | Provide 25–40 role-labelled pilot questions and a deterministic evaluation ledger | P1 | evaluation target |
| REQ-024-09 | Keep all activation local/dev and reversible until real OIDC owners and production authority exist | P0 | TIP-025 boundary |

## DECISIONS LOG

| ID | Decision | Rationale |
|---|---|---|
| D-024-01 | Treat this as a governed campaign, not a bulk seed | Counts without owner, provenance and checksums are not pilot evidence |
| D-024-02 | Keep the eight strict facts unchanged and never bulk-remove 211 caveats | A3 integrity is more important than a higher readiness percentage |
| D-024-03 | A TIP-013B migration placeholder does not count as a named domain owner | Prevent false 100% ownership coverage |
| D-024-04 | Reconcile current CNCL claims by `(entity, field)` | Produces 70 stable records and retains every source claim |
| D-024-05 | Different source wording remains `disputed`, even when tier A appears stronger | Refinery v1.2 forbids automatic conflict resolution by tier |
| D-024-06 | Map authoritative/secondary research to P/S; keep corroboration as an independent field | Tier and corroboration answer different questions |
| D-024-07 | Real files remain `private_context`; research remains `research`; neither may masquerade as SOT | Zero cross-zone masquerade |
| D-024-08 | Adapt template binaries in staging; never overwrite the canonical template files | Canonical-source ownership invariant |
| D-024-09 | Official/legal rendering fails closed on `needs_double_check` | Caveated facts are approved only for visibly caveated internal pilot use |
| D-024-10 | Audio/video target is an honest-null for this batch | No local source exists; no synthetic media will be invented |

Checkpoint note: the Homeowner already approved the continuation plan and
explicitly requested TIP-024. This TIP refines that approved scope without a
new architecture or production activation, so no additional Blueprint pause is
required.

## TASK

Implement a reproducible pilot campaign that populates and measures the real
Files, Templates and Research surfaces in local/dev, while making provenance
and ownership debt visible and enforcing stronger document-output gates.

## SPECIFICATIONS

### 1. Pilot readiness contract

Add an admin-only read endpoint and UI panel derived from live database state.
It must report at least:

- active SOT total, strict total, caveated total, current/stale totals;
- named-owner versus placeholder-owner totals;
- high-risk price/spec/legal/external subset totals;
- real file/version/rendition/index counts and checksum/parity findings;
- template totals, approved totals and locked-binding totals;
- research source/package/record, tier and corroboration totals;
- target, actual and state (`met`, `partial`, `blocked`) for every pilot family.

No endpoint in this TIP may mutate SOT/research/document truth.

### 2. Research adapter

- Input is the existing flat `claims.jsonl` plus immutable snapshots.
- Every `evidence_span` must be found verbatim in its named snapshot.
- Include only current `state=sourced` claims in the pilot package.
- Group by `(entity, field)` and keep every claim in `content.claims`.
- One value from one source → `uncorroborated`.
- One exact value from at least two independent A/B publishers →
  `corroborated`.
- More than one exact value → `value: null`, `disputed`; never select a winner.
- The output must be byte-deterministic and accepted by the existing rooted
  Research package parser.
- Extend the package contract so declared corroboration is persisted rather
  than reset to `uncorroborated` during import.

Expected current result: 70 records = 16 corroborated + 24 disputed + 30
uncorroborated.

### 3. Template adapter and document guard

- Convert all four entries in `templates/registry.yaml` to V2 schema.
- Support deterministic day/month/year derivation from one ISO date field.
- Locked values may use only a bounded scalar format over current fact JSON or
  a curator-declared literal that must still occur in current fact content.
- Remap the two retired `CAND.*` references to strict HERA spec records.
- Adapt the XLSX cells into placeholders in staging only.
- Import/approve pilot templates as internal; this does not approve them as
  official/legal company stationery.
- For `needs_double_check` locked facts:
  - official/legal → `fact_caveated`, fail closed;
  - internal → the rendered value visibly includes caveat code and owner.
- Freshness, version checksum and publication recheck remain unchanged.

### 4. File campaign

- Use an explicit YAML manifest rooted under a user-supplied KnowledgeBase
  path; no arbitrary path traversal or symlink escape.
- Require file path, classification, source zone, owner and SHA-256 at plan
  time; apply refuses drift.
- Select 30 representative, modest-size real artifacts across PDF, DOCX, XLSX,
  PPTX and image when available.
- Drive the existing ingestion/rendition/index path; do not insert final
  document rows directly.
- Re-running is idempotent by source manifest key + checksum.
- Report original/object/rendition checksum or declared-lineage parity.

### 5. Pilot questions

- Commit 25–40 questions with persona (`staff`, `leader`, `curator`, `admin`),
  scope (`sot`, `file`, `research`, `document`) and expected outcome
  (`grounded`, `honest_null`, `denied`, `blocked_caveat`).
- Evaluation output must state measured/untestable counts; no external-provider
  result may be claimed without provider credentials.

## ACCEPTANCE CRITERIA

- **AC-024.1 — Readiness truth:** Given the live local database, when an admin
  opens Pilot Corpus, then every displayed count matches a direct database
  reconciliation and a non-admin receives the existing 403 discipline.
- **AC-024.2 — Provenance honesty:** Given 8 strict and 211 caveated records,
  when the readiness report is computed, then it reports exactly those classes,
  does not upgrade any provenance and reports placeholder ownership separately.
- **AC-024.3 — Research evidence:** Given the CNCL dataset, when the adapter
  runs, then 124/124 input spans pass, the current package has 70 records and
  every emitted quote/checksum is revalidated by the package parser.
- **AC-024.4 — Conflict preservation:** Given exact-equal and unequal duplicate
  values, when records are built/imported, then the totals are 16 corroborated,
  24 disputed and 30 uncorroborated; disputed values remain null with all claims.
- **AC-024.5 — Research zone:** Given an imported pilot package, when searched
  or viewed, then every item remains labelled `research`, and no active SOT
  generation includes a research record.
- **AC-024.6 — Real templates:** Given the four canonical company templates,
  when the adapter/import runs, then all four have deterministic fingerprints,
  approve through the existing lifecycle and at least one locked strict fact
  renders from the exact active version.
- **AC-024.7 — Caveat gate:** Given a caveated locked fact, when an
  official/legal template binds, then it is blocked; when an internal template
  binds, then the caveat and owner are visible in the rendered artifact.
- **AC-024.8 — Real files:** Given the approved local manifest, when activation
  completes, then at least 30 real versions are ready across at least four
  viewer families, checksum/lineage parity has zero unexplained mismatch and
  cross-file/private retrieval leakage remains zero.
- **AC-024.9 — Questions:** Given the committed pilot set, when the offline
  evaluator runs, then all cases receive a measured result or an explicit
  untestable reason; unsupported cases retain 100% honest-null expectation.
- **AC-024.10 — Regression:** Backend, Web, browser, live-data, axe and
  repository verification gates pass with zero new P0/P1 finding.
- **AC-024.11 — Production boundary:** No production secret, OIDC binding,
  official owner attestation or company-wide activation is fabricated or
  claimed complete.

## CONSTRAINTS

- Never write back to the canonical kernel, template files, CNCL claims or
  source snapshots.
- Never map a caveated/claim record to strict merely to meet a target.
- Never count test fixtures as representative pilot corpus.
- Never copy Research content into SOT without the graduation gate.
- Never bypass the existing ingestion, template lifecycle, policy, audit or
  publish gates.
- Production owner assignment and TIP-025 launch authority remain Homeowner
  checkpoints.

## REPORT FORMAT

Create `TIP-024_COMPLETION_REPORT.md` and `TIP-024_VERIFY_REPORT.md` with:

- REQ coverage and AC pass/fail counts;
- live corpus totals by zone/type/provenance/owner;
- exact research reconciliation and bite/gate evidence;
- file/template checksum evidence;
- technical-health counts;
- remaining human-owner/production blockers;
- overall status `READY`, `READY-with-deferred`, or `NOT READY`.
