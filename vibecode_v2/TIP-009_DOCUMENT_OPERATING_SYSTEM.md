# TIP-009 · Document Operating System

## HEADER

- **TIP-ID:** TIP-009
- **Project:** RtR Copilot V2
- **Module:** Template registry, structured binding, deterministic rendering,
  preview, review, approval and issuance
- **Depends on:** TIP-003, TIP-004, TIP-005, TIP-006, TIP-008 VERIFIED
- **Priority:** P0
- **Status:** VERIFIED · READY
- **Working directory:** `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2`
- **Requirements directly implemented/advanced:** REQ-004, REQ-006, REQ-008,
  REQ-011, REQ-013, REQ-015, REQ-016, REQ-021, REQ-022, REQ-023, REQ-024,
  REQ-025, REQ-028, REQ-029, REQ-032

## CONTEXT

TIP-006 supplies versioned SOT facts, evidence, provenance, freshness and atomic
activation. TIP-008 supplies the authorized Files catalog, immutable document
versions, safe rendition manifests, in-app viewers and original download
authorization.

The pilot contains four useful template assets and demonstrates the intended
separation between user fields, locked facts and derived fields. It is an oracle,
not production code:

- locked fields include duplicated literal `value` data and regex checks against
  record text, so the output is not actually bound to an immutable fact value;
- template metadata is mutable YAML without owner, lifecycle approval or immutable
  template-version checksum;
- output names contain clock time and randomness; Office ZIP metadata is not
  normalized, so repeated renders are not byte-deterministic;
- there is no persistent render job, parameter/fact manifest, generated-file
  version, review, approval, issuance or revocation trail;
- output bypasses V2 resource/object authorization and safe viewer pipeline;
- XLSX patching preserves cached formula values but does not prove recalculation or
  absence of formula errors;
- only DOCX/XLSX exist; PDF/PPTX generation and real in-app preview are absent.

TIP-009 creates a governed **Document Operating System**. It does not implement
collaborative Office editing, arbitrary template code, electronic signatures,
public sharing, production template activation from the real company kernel or
the final cross-module UX consolidation.

## DECISIONS LOG

| ID | Decision | Rationale |
|---|---|---|
| D-009-01 | Reuse the already-approved Blueprint; no new Homeowner checkpoint | The request explicitly advances the approved M3 Document OS |
| D-009-02 | A template and each template version are immutable governed resources | Prevent silent format/schema drift and enable exact rerender/audit |
| D-009-03 | Locked fields resolve only from an activated SOT record version; literal factual defaults are forbidden | Eliminate the pilot's hard-code drift |
| D-009-04 | A render freezes canonical parameters, template checksum, renderer version and exact fact/evidence snapshot | Make every generated statement explainable and reproducible |
| D-009-05 | Preview/rerender produces new immutable generated versions and uses TIP-008 Files/viewers | Avoid a second storage/viewer/security plane |
| D-009-06 | Official/legal output is a draft until separate review, approval and issuance complete | Meet REQ-025 and prevent accidental official use |
| D-009-07 | Renderer accepts declarative bindings only; macros, scripts, external relationships and executable content are rejected | Template authors cannot cross the execution boundary |
| D-009-08 | Legacy assets remain read-only and may enter V2 only through a validated, fingerprinted import | Preserve evidence and prevent uncontrolled activation |
| D-009-09 | Tests use synthetic activated SOT facts and synthetic templates only | The real company kernel is currently read-only/not publishable |

## DESIGN DIRECTION

**Subject:** a governed document assembly desk for RtR employees who need a
traceable file, not a generic form builder.

**Single job:** choose an approved template, supply only the missing inputs,
inspect every locked fact and its evidence, render a real file, then route an
official document through review and issuance.

### Token and layout continuity

Inherit TIP-008 graphite, steel, RtR signal orange and locator cyan tokens, type
stacks and responsive breakpoints. Add no remote font and no independent design
system.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ RT ROBOTICS / DOCUMENTS       template search       identity / activity │
├──────────────────┬───────────────────────────────┬───────────────────────┤
│ Template ledger  │ Structured assembly desk      │ Fact & approval rail  │
│ status / version │ user fields + real preview    │ SOT evidence / history│
│ format / owner   │ render state / file viewer    │ checksum / issuance   │
└──────────────────┴───────────────────────────────┴───────────────────────┘
```

At mobile width, the template ledger becomes a drawer and the fact/approval rail
becomes a bottom sheet. Preview remains the dominant surface.

### Signature element

Use a **provenance stitch**: each locked field has a restrained cyan line joining
the form value to its exact SOT record/evidence entry in the rail. It communicates
the product's core promise rather than decorating the interface. Respect reduced
motion and provide the same relationship in accessible text.

Avoid generic dashboard card grids, glass effects, decorative gradients and
marketing copy. Use plain Vietnamese verbs: “Xem trước”, “Tạo bản mới”, “Gửi
duyệt”, “Phê duyệt”, “Từ chối”, “Phát hành”.

## DATA MODEL AND INVARIANTS

Add migration `0008_document_operating_system` with tenant-safe UUID/FK/check
constraints, indexes, grants and backup/restore coverage for:

- `templates`: stable key, display metadata, category, owner, classification,
  document class (`internal|official|legal`), lifecycle state;
- `template_versions`: immutable ordinal/version, format
  (`docx|xlsx|pptx|pdf`), source object/checksum, strict field schema, renderer
  kind/version, status (`draft|in_review|approved|retired`), creator and
  approval timestamps;
- `template_bindings`: immutable field path/type/source
  (`user|locked_fact|derived`), required rule, formatting rule, SOT record key
  and accepted provenance/verification/freshness contract;
- `render_jobs`: requester, idempotency key, canonical input hash, template
  version, active SOT generation/revision, state, safe error code and timestamps;
- `render_job_bindings`: canonical user input or exact record-version/value
  snapshot, evidence/source checksums and locator; factual user input remains
  visibly distinct from locked facts;
- `generated_files`: render job, immutable Files document/version/object IDs,
  output format, ordinal, checksum, deterministic render manifest and lifecycle;
- `approvals`: generated-file version, stage, immutable reviewer subject,
  decision, attestation hash, reason and timestamp;
- `document_issuances`: generated-file version, unique issue number, issuer,
  issued checksum, issued/revoked timestamps and immutable reason.

Required invariants:

- updates/deletes cannot mutate approved template versions, completed render
  bindings, generated checksums, approval decisions or issuance history;
- one idempotency key per requester and operation resolves to one semantic result;
- official/legal requester cannot approve their own output;
- issuance is unique and possible only for the exact approved checksum;
- a rejected/revoked decision cannot be bypassed by a stale UI;
- generated resources inherit a bounded owner/classification/ACL policy; no public
  object URL or object key appears in API/UI/logs;
- append-only audit covers import, approve/retire template, preview/render,
  submit/review/approve/reject, download and issue/revoke.

## TASK

### 1. Governed template registry

Implement typed APIs:

- `GET /api/v1/templates` with policy-filtered, stable cursor pagination;
- `GET /api/v1/templates/{template_id}/versions/{version_id}`;
- curator/admin import and lifecycle endpoints for draft, submit, approve, retire.

Import copies an asset through quarantine/object storage, verifies extension,
detected MIME, size, archive ratios, paths, relationships and package structure,
then fingerprints it. Reject macros, embedded OLE/packages, executable content,
external/remote relationships, traversal, unsupported compression and malformed
OOXML/PDF. Never render an uploaded template before validation.

Schema is strict and bounded: unknown properties forbidden; supported primitives
are string, multiline string, integer/decimal, boolean, date, enum, bounded list
and bounded table. Required/max lengths/row limits/formats are server-enforced.
No template expression language, eval, arbitrary formula injection or network
lookup is allowed.

Legacy files under `/templates` are read-only oracle assets. If fixtures import
them, copy through the same validator; never modify their bytes or registry.

### 2. Parameter extraction and binding preview

Provide:

- `POST /api/v1/templates/{version_id}/bind` to validate explicit parameters,
  compute derived fields and resolve locked facts without creating a file;
- optional natural-language extraction into user fields only.

Extraction must return field confidence/source spans, leave absent fields empty and
never guess required values, issue numbers, dates, recipients or company facts.
Unknown/ambiguous input is a typed validation result, not silent coercion.

Binding preview returns display-safe user/derived values plus each locked field's
record key, immutable record-version ID, provenance, verification/freshness,
evidence locator and checksums. It never exposes a fact before `view` policy and
DLP checks. Policy runs before content lookup and again before render publication.

### 3. Locked SOT fact gate

Locked fields resolve from the currently activated SOT generation. For official or
legal documents, require an approved/verified, non-conflicted, non-placeholder,
effective and fresh record with accepted provenance. A schema cannot contain a
literal fallback factual value.

The render manifest freezes the exact record version, normalized value,
content/evidence/source checksums and activation revision. Revalidate immediately
before committing output. If a fact becomes stale, revoked, conflicted or
unauthorized while the job runs, fail closed and publish no generated artifact.

### 4. Deterministic renderer

Implement background render jobs for DOCX, XLSX, PPTX and PDF:

- the same approved template bytes, renderer version, canonical parameters and
  fact snapshot produce a byte-identical output checksum;
- normalize ZIP member order/timestamps, Office core properties, PDF metadata,
  locale/timezone, relation ordering and generated identifiers;
- render into a private temporary object; validate fully; publish the object,
  generated-file row and Files document/version atomically;
- retry is idempotent; concurrency cannot create duplicate semantic versions;
- cancellation/failure removes temporary bytes and exposes no partial object.

Format requirements:

- **DOCX:** preserve template styles/sections/header/footer; replace placeholders
  safely across runs; multiline/tables retain controlled styles; no unresolved
  placeholder; valid OOXML and successful PDF preview;
- **XLSX:** preserve styles and intended formulas; neutralize leading formula
  injection from user text; recalculate with LibreOffice in QA; zero
  `#REF!/#DIV/0!/#VALUE!/#NAME?/#N/A`; deterministic workbook metadata;
- **PPTX:** preserve masters/layouts/relationships; replace only declared shapes;
  reject overflow; valid package and PDF/slide previews;
- **PDF:** generate from an approved PDF template or deterministic controlled
  conversion; embedded fonts/metadata are stable; text is extractable when
  expected and page bounds are respected.

Renderer workers have no internet, no shell/template code execution, bounded CPU,
memory, pages/slides/sheets/rows and wall time. Errors are typed and sanitized.

### 5. Generated versions and real preview

Register each valid output through TIP-004/005 Files primitives. Trigger the
existing rendition pipeline and open it in the TIP-008 viewer. Do not create a
parallel download/view endpoint.

Editing parameters after a preview creates a new render job and immutable
generated version; never overwrite. Show version comparison for parameters,
locked fact snapshots, template version, state and checksum. A draft watermark or
equivalent visible state is mandatory for official/legal previews before issue.

### 6. Review, approval and issuance

Implement:

- submit a generated version for review;
- authorized reviewer approve/reject with reason;
- authorized issuer issue the exact approved checksum;
- revoke an issuance with immutable reason.

Internal templates may finish at generated state according to policy. Official and
legal documents require separation of duties and exact-checksum approval before
issuance. Changing parameters, facts, template version or output bytes invalidates
prior approval. Issue numbers are server-generated/validated under a deterministic
collision-safe policy and cannot be supplied through natural-language extraction.

Downloads and previews always show current draft/approved/issued/revoked truth.
Previously downloaded bytes remain traceable by checksum and issuance history.

### 7. Documents workspace

Add a “Tài liệu” workspace alongside Files:

- approved template ledger with format/category/owner/version/status filters;
- schema-driven form with clear user, derived and locked fact treatment;
- fact/evidence rail with accessible provenance stitch;
- binding validation, missing/blocked states and actionable recovery;
- background render progress, retry/cancel where safe;
- real TIP-008 preview, parameter edit and generated-version history;
- review/approval/issuance timeline and role-appropriate actions;
- empty, loading, offline, denied, expired and partial-rendition states;
- URL-restorable template/generated version without storing restricted metadata in
  browser storage.

The primary keyboard flow must work from template selection through issue/download.
Use semantic landmarks, one H1, visible focus, status announcements, WCAG 2.2 AA
contrast and no accidental page overflow at 360×800, 768×1024, 1440×900 and
1920×1080.

### 8. Tests, artifact QA, recovery and documentation

Add backend unit/integration tests for schema/import attacks, policy filtering,
fact gates, activation races, deterministic bytes, idempotency/concurrency,
rollback cleanup, approval separation, stale decision/issue races, audit and
restore.

Add frontend tests and Playwright flows for binding, evidence inspection, all four
formats, edit/rerender, failed render, review/reject/approve/issue, keyboard and
responsive behavior. Include explicit anonymous/cross-owner/denied
template/fact/generated-file leak probes.

Artifact QA is mandatory:

- render representative synthetic DOCX/XLSX/PPTX/PDF outputs twice and compare
  checksums;
- validate OOXML/PDF structure;
- use LibreOffice to recalculate XLSX and scan all formula cells for errors;
- render DOCX/PPTX/PDF pages/slides to images and visually inspect every page;
- verify no clipping, overlap, unresolved placeholders, broken relationships,
  corrupted diacritics or false “issued” state;
- retain only bounded synthetic QA artifacts/evidence outside production object
  namespaces.

Update README/API/operator documentation and backup/restore manifest. Keep
`make verify` as the concurrency-safe full gate and preserve all TIP-001…008 tests.

## ACCEPTANCE CRITERIA

### AC-01 · Registry is immutable and policy-filtered

Only authorized template metadata is listed; approved versions cannot be mutated
or replaced and denied existence does not leak through count, cursor or timing
contracts.

### AC-02 · Template import is fail-closed

Valid synthetic templates enter quarantine and validation; macro, OLE, remote
relationship, traversal, malformed or oversized packages are rejected and audited
without reaching the renderer.

### AC-03 · Schema is strict

Supported fields validate deterministically while unknown properties, unbounded
values, ambiguous dates, formula injection and executable expressions fail with
typed errors.

### AC-04 · Extraction does not guess

Natural-language extraction fills only explicitly evidenced user fields, provides
source spans and leaves missing/ambiguous required or locked fields empty.

### AC-05 · Locked facts have no hard-code drift

Every locked output value comes from an exact active SOT record version with
evidence/checksums; literal factual fallback and placeholder/conflicted/stale
official facts are blocked.

### AC-06 · Authorization survives races

Template, fact and output policy/DLP are checked before disclosure and rechecked
before publication; revocation during a render yields no published bytes or
metadata.

### AC-07 · Render jobs are atomic and idempotent

Concurrent/retried identical requests resolve to one semantic result; failed or
cancelled jobs leave no visible partial row/object and safe error details only.

### AC-08 · DOCX is deterministic and valid

Two identical renders are byte-identical, retain intended template layout/styles,
contain no unresolved placeholders and pass structural plus visual QA.

### AC-09 · XLSX is deterministic and valid

Two identical renders are byte-identical, retain intended styles/formulas, contain
no formula injection, recalculate successfully and contain zero formula errors.

### AC-10 · PPTX is deterministic and valid

Two identical renders are byte-identical, preserve master/layout relationships,
have no text overflow or unresolved placeholders and pass structural/visual QA.

### AC-11 · PDF is deterministic and valid

Two identical renders are byte-identical, have stable metadata, valid structure,
expected extractable text and no clipped/overflowing content.

### AC-12 · Manifest proves every value

Generated files persist canonical inputs, template/renderer checksums, active SOT
revision and exact fact/evidence/source fingerprints sufficient to explain and
reproduce the output.

### AC-13 · Preview reuses Files safely

Every completed render creates an authorized immutable Files version and safe
renditions; the UI previews it without original OOXML execution or public/object
URLs.

### AC-14 · Edit/rerender preserves history

Changing a parameter creates a distinct generated version and comparison record;
prior output, manifest, checksum, citations and decisions are unchanged.

### AC-15 · Official approval enforces separation

The requester cannot approve their own official/legal version; unauthorized,
duplicate, rejected, stale-checksum and concurrent approval actions fail closed
and are audited.

### AC-16 · Issuance is exact and traceable

Only the currently approved checksum can be issued once under a collision-safe
number; revocation is append-only and every downloaded byte can be matched to its
issuance state.

### AC-17 · Documents UX is operable

An authorized user can select a template, complete fields, inspect locked evidence,
render, preview, edit/rerender and complete permitted review/issue actions using
keyboard alone across required responsive sizes.

### AC-18 · Leak and recovery gates pass

Anonymous/cross-owner/denied policy probes leak zero restricted metadata/content;
backup/restore retains templates, manifests, bindings, generated checksums,
approvals, issuances, grants and object lineage.

### AC-19 · Full verification and artifact QA pass

`make verify`, backend/frontend/integration/Playwright suites, deterministic
rerender probes, Office/PDF structural validators, XLSX recalculation and visual
inspection all pass with zero P0/P1 failure.

## OUT OF SCOPE

- Electronic/digital signature providers and certificate authority integration.
- Multi-user real-time Office editing or arbitrary Office Online embedding.
- Arbitrary user-authored code, macros, formulas, remote images or web templates.
- Public links, external recipient delivery and email workflow.
- Activating or mutating `/Users/os/RtR/kernel`, KnowledgeBase registry, GOI or
  research corpora.
- Production-ready legal/official template content; TIP-009 proves the governed
  mechanism with synthetic fixtures.
- Final application-wide navigation/i18n/accessibility consolidation (TIP-011).

## BUILDER HANDOFF

Builder must:

1. implement only inside `v2` plus TIP completion evidence;
2. preserve real kernel/GOI/KnowledgeBase and legacy templates read-only;
3. create `vibecode_v2/TIP-009_COMPLETION_REPORT.md` mapping every AC to code,
   tests, commands, counts, screenshots/artifacts and deviations;
4. run `make verify` and format-specific QA before declaring complete;
5. leave the working tree uncommitted for Contractor verification.

Contractor will independently inspect code/data boundaries, rerun gates, execute
runtime/browser and artifact probes, visually inspect outputs, then write
`TIP-009_VERIFY_REPORT.md`. P0/P1 failure returns the TIP to BUILD.
