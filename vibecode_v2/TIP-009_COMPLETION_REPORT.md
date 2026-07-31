# TIP-009 · Document Operating System — Completion Report

**Date:** 2026-07-31  
**Builder scope:** `RtR_Copilot/v2` only  
**Overall result:** **IMPLEMENTED · CONTRACTOR GATE PASSED · P1 CLOSURE VERIFIED**

## 1. Outcome

TIP-009 now has a coherent vertical slice:

- governed template and immutable template-version registry;
- strict typed binding contracts for user, locked SOT and declared derived fields;
- deterministic DOCX, XLSX, PPTX and PDF renderers;
- durable/idempotent render jobs and worker dispatch;
- output registration through the existing Files ingestion/rendition/viewer plane;
- generated-file review, approval, issue and revoke lifecycle;
- signed template cursor, template-version history and generated approval truth;
- responsive `/documents` workspace with the TIP-008 safe viewer;
- database migration, backup/restore inventory and operator documentation.

No live kernel, GOI, KnowledgeBase dataset or legacy template asset was modified or
used as a production fixture. Tests use bounded synthetic artifacts.

## 2. Principal implementation

### Persistence and invariants

Migration `0008_document_operating_system` adds:

- `templates`, `template_versions`, `template_bindings`;
- `render_jobs`, `document_publication_outbox`, `render_job_bindings`,
  `generated_files`;
- `approvals`, `document_issuances`;
- resource types `template` and `template_version`;
- immutable approved/retired versions, bindings, output checksum/manifest,
  approval and issuance history;
- least-privilege runtime grants and delete revocation.

Approved replacement versions retire the previous approved version without
mutating its canonical bytes/schema/checksum. Importing the same `stable_key`
creates the next ordinal rather than replacing history.

### Template boundary

The import contract is strict and rejects:

- unknown schema properties and unsupported/undeclared derivation;
- text, numeric, list and table fields without deterministic bounds;
- malformed or oversized OOXML/PDF;
- ZIP traversal/compression abuse;
- VBA, OLE, embeddings, ActiveX and custom UI payloads;
- external relationships and missing required package parts.

Rejected import attempts are fail-closed and emit a safe audit reason when the
audit dependency is available.

### Binding, SOT and rendering

- Natural extraction accepts only explicit `field_path: value` evidence and stores
  source spans; it does not guess missing or locked values.
- Locked values resolve only from the current active record version with accepted
  provenance, verification, freshness, evidence locator and exact checksums.
- Render publication rechecks template policy, DLP and exact active fact checksum.
- Canonical render manifests freeze template checksum/version, renderer version,
  input hash, SOT revision and record/evidence fingerprints.
- Retry reuses the same semantic job; pending cancellation is typed and atomic.
- Renderers normalize ZIP member order/timestamps and document metadata.
- XLSX formula-like user strings are neutralized and formula-error tokens blocked.
- Output enters the existing Files validation and safe rendition pipeline in a
  deferred-publication state. Document/version/object/rendition resources remain
  quarantined/staged until the generated row, completed job and finalized
  publication outbox commit together. Failure marks resources deleted and removes
  staged objects; retry/cancel transitions the outbox explicitly.

### Review and issuance

- Requester submits an immutable generated checksum.
- Leader policy is checked against the generated Files version.
- Official/legal requester self-approval is denied.
- Approval attests the exact checksum and is append-only.
- Issuance is once-only with a server-derived collision-resistant number.
- Revocation records actor, timestamp and immutable reason.
- Generated detail returns current lifecycle, decisions and issuance truth.
- Generated history is policy-filtered per Files version and compares user
  parameters separately from locked SOT snapshots, template version, checksum and
  lifecycle.

### Documents UX

`/documents` implements the three-part operating desk:

- approved template ledger;
- typed assembly form and real Files preview;
- locked-fact / approval rail.

Official/legal previews show a visible `DRAFT · CHƯA PHÁT HÀNH` overlay before
issuance. The overlay was visually tuned to preserve preview readability. Mobile
drawers are mutually exclusive, bounded to `min(88vw, 360px)`, close with Escape
and retain a backdrop. Checksums are visually truncated with a copy affordance.

## 3. Verification evidence

### Passed

- Backend Ruff: pass.
- Backend strict mypy: pass (`68` source files).
- Final full backend suite: `175 passed, 38 skipped` (database integration tests
  run separately against isolated services).
- TIP-009 document unit suite with runtime DejaVu font: `15 passed`;
  deterministic/structural DOCX, XLSX, PPTX and PDF pass, including Vietnamese
  PDF extraction.
- Web TypeScript, ESLint and Vitest: pass (`6` files, `34` tests).
- Documents Playwright mock flow after visual fixes: `2 passed`.
- Final full `make verify`: pass (`175` backend passed / `38` skipped,
  `37` integration, `34` web), including image builds and vulnerability scan.
- P1-targeted Ruff and strict mypy: pass (`68` source files); generated-history
  comparison test: pass.
- Bounded DB/runtime Document OS probes: `2 passed` on a fresh revision-0008
  database and isolated object bucket:
  - policy revocation after output staging but before finalization produces a
    failed outbox, zero generated rows, zero active Files resources and no
    remaining staged bytes;
  - the production worker dispatch path completes render → deferred Files
    validation/renditions → finalized publication → authorized viewer manifest;
  - concurrent duplicate approve, reject, issue and revoke attempts produce one
    canonical decision/issuance/revocation, one success audit per transition and
    immutable approval history.
- Browser screenshots inspected:
  - `tip009-documents-desktop.png`;
  - `tip009-documents-mobile-ledger.png`;
  - `tip009-documents-mobile-rail.png`;
  - `tip009-documents-mobile.png`.
- Isolated mounted migration exercise:
  - upgrade to `0008_document_operating_system`: pass;
  - all nine new TIP-009 tables present, including the publication outbox;
  - downgrade to 0007 removes TIP-009 tables;
  - re-upgrade to 0008: pass;
  - runtime `DELETE FROM approvals`: denied.
- LibreOffice artifact QA:
  - synthetic DOCX and PPTX converted to PDF;
  - rendered pages visually inspected with intact Vietnamese diacritics and no
    clipping in the bounded fixture;
  - synthetic XLSX recalculated by LibreOffice;
  - cached formula result verified as `2`, with formula/style checks also covered
    by unit tests.
- Non-empty TIP-009 recovery proof:
  - seeded template/version/binding, render/outbox/binding, generated file,
    approval and issuance rows plus two object payloads;
  - custom-format database dump restored into an isolated database and objects
    copied into an isolated bucket;
  - exact row counts, generated→job→version→object lineage, checksum equality,
    finalized outbox state and runtime DELETE revocations verified.

### Important test-environment note

The PDF Vietnamese test fails in an unprovisioned bare `python:slim` container
because ReportLab's fallback Vera font lacks Vietnamese glyphs. This is not the
declared runtime: the backend Dockerfile and fallback verification path now install
the pinned `fonts-dejavu-core=2.37-6` package. The same test passes with that runtime
dependency present.

## 4. Acceptance-criteria disposition

| AC | Disposition | Evidence / limitation |
|---|---|---|
| AC-01 | Implemented | policy-filtered ledger, signed stable cursor, immutable version trigger |
| AC-02 | Implemented with deviation | hostile packages rejected/audited; import validates before durable storage rather than using a separate quarantine table |
| AC-03 | Implemented | strict Pydantic schema, deterministic bounds, injection handling |
| AC-04 | Implemented | explicit line evidence and source spans; no guessing |
| AC-05 | Implemented | exact active record/evidence/freshness gate and publication recheck |
| AC-06 | Implemented and verified | policy/template/exact-fact guards run both before rendering and again after artifact staging immediately before publication; revocation probe proves no visible row/resource/object escapes |
| AC-07 | Implemented | formal publication outbox; Files resources stay quarantined/staged until one final DB transaction activates resources, completes the job, inserts generated truth and finalizes the outbox; failures close visibility and clean staged objects |
| AC-08 | Implemented | byte determinism, split-run/table replacement, style and structural tests; LibreOffice visual fixture |
| AC-09 | Implemented | byte determinism, formula/style preservation, injection defense; LibreOffice recalculation result `2` |
| AC-10 | Implemented | byte determinism, relationship preservation, overflow/unresolved-placeholder rejection; LibreOffice visual fixture |
| AC-11 | Implemented | byte determinism, stable metadata, valid structure and Vietnamese extractable text with runtime font |
| AC-12 | Implemented | persisted canonical render manifest and exact fact/evidence fingerprints |
| AC-13 | Implemented and verified | synthetic production-worker E2E traverses deferred Files ingestion, validation, rendition generation, finalized outbox and authorized viewer manifest |
| AC-14 | Implemented | policy-filtered generated-history API and UI diff separate changed user parameters, locked SOT snapshots, template version, checksum and lifecycle |
| AC-15 | Implemented and verified | role/policy/SoD/exact-state checks plus concurrent approve/reject probes yield exactly one immutable canonical decision |
| AC-16 | Implemented and verified | exact checksum and deterministic issue number; concurrent issue/revoke probes yield one issuance, one revocation and one success audit each |
| AC-17 | Implemented | keyboard actions, mocked end-to-end render/preview, responsive drawer tests/screenshots |
| AC-18 | Implemented | backup/restore manifests and grants include every TIP-009 table; non-empty isolated database/object restore proves counts, lineage, checksums, finalized outbox and delete revocations |
| AC-19 | Implemented with environment note | Contractor full `make verify` passed; P1-targeted static/unit/integration/recovery gates rerun, with bare-python PDF font behavior documented above |

## 5. Known deviations and required follow-up

1. **PDF template semantics:** the controlled PDF renderer produces a deterministic
   governed layout from bound values rather than executing or editing arbitrary
   supplied PDF content. If approved PDF backgrounds/forms must be preserved,
   define a declarative coordinate schema and add visual golden tests before
   enabling that behavior.

## 6. Handoff status

The feature is suitable for integration and product review. All P1 verification
gaps identified after the Contractor pass—observable publication, generated
comparison, non-empty recovery, revocation closure, production-worker E2E and
concurrent lifecycle canonicality—are closed. Richer PDF-template semantics remain
a non-blocking product extension.
