# TIP-009 · Contractor Verify Report

**Date:** 2026-07-31  
**Verdict:** **VERIFIED · READY**  
**Baseline commit:** `1d0c906`  
**Scope:** uncommitted TIP-009 worktree under `RtR_Copilot/v2`

## Outcome

TIP-009 implements a governed Document Operating System rather than a thin export
feature:

- immutable, policy-filtered template/version registry;
- strict user, derived and locked-SOT bindings without factual literal fallback;
- deterministic DOCX, XLSX, PPTX and PDF renderers;
- deferred Files ingestion and publication outbox with one observable finalization;
- real TIP-008 preview, immutable generated history and comparison;
- review, separation-of-duties approval, issuance and revocation truth;
- responsive Documents workspace and same-origin API proxy;
- complete backup/restore coverage for database rows, grants and object lineage.

No real kernel, GOI, KnowledgeBase registry or legacy template was modified or
activated. Runtime/template tests use synthetic data.

## Independent verification

### Full gate

Contractor ran `make verify` on the final P1-closure worktree:

- web ESLint, TypeScript and production build: PASS;
- Vitest: `34 passed`;
- Ruff: PASS;
- strict mypy: `68` source files, PASS;
- backend: `175 passed`, `38 skipped`;
- container image builds: PASS;
- vulnerability scan: zero detected high/critical findings;
- final result: `VERIFY PASS`.

### Database, recovery and race gates

Contractor independently reran `./scripts/verify-data-integration.sh`:

- `37 passed`;
- migrations and revision fixtures: `8`;
- document OS runtime probes: `2`;
- failing-DDL rollback: PASS;
- non-empty TIP-009 database/object restore: PASS;
- policy scenarios: `48`;
- runtime denials: `18`;
- result: `DATA INTEGRATION PASS`.

The two Document OS runtime probes prove:

1. policy/fact revocation after staging produces no visible generated file,
   resource or object bytes;
2. production worker flow reaches deferred ingestion, validation, renditions,
   finalized outbox and authorized viewer manifest;
3. concurrent approve/reject/issue/revoke calls produce exactly one immutable
   canonical decision, issuance and revocation with valid audit lineage.

These probes found and caused correction of real defects in audit resource FKs,
audit actor kind, late publication guards, outbox row-count checking and UUID
payload casting before the final PASS.

### Artifact and browser QA

- deterministic double-render and structural checks pass for DOCX, XLSX, PPTX and
  PDF;
- LibreOffice DOCX/PPTX conversion and visual inspection pass;
- LibreOffice XLSX recalculation returns the expected cached result and zero
  formula-error tokens;
- Vietnamese PDF text renders/extracts correctly in the declared DejaVu-equipped
  runtime;
- Documents Playwright: `2 passed`;
- desktop/mobile screenshots were inspected; mobile drawers are mutually
  exclusive and bounded, checksum text is truncated/copyable and draft watermark
  remains legible without hiding the preview.

### Live runtime

- migration head: `0008_document_operating_system`;
- API, web, worker, PostgreSQL, Redis, MinIO and ClamAV: healthy;
- API readiness: PostgreSQL, Redis and object storage ready;
- `http://127.0.0.1:3000/`: HTTP 200;
- `http://127.0.0.1:3000/documents`: HTTP 200;
- final images were rebuilt and the local stack restarted after the last fixes.

## Acceptance decision

All AC-01…AC-19 are accepted. The approved P0/P1 scope has no open failure.

Two bounded product extensions remain outside this acceptance:

- richer declarative coordinate binding for preserving arbitrary PDF
  backgrounds/forms;
- production activation of real company templates and SOT, which requires a
  separately approved data/template onboarding decision.

`git diff --check` is clean. TIP-009 remains intentionally uncommitted because the
user requested a commit before beginning TIP-009, not a commit after its
implementation.
