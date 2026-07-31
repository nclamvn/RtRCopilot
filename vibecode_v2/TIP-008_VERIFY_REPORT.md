# TIP-008 · Independent Verify Report

**Date:** 31/07/2026  
**Verifier:** Contractor · Vibecode Kit v6.1  
**Overall status:** READY — end-to-end Files workspace and seven viewer families
verified; full-fidelity Office editing and unified Ask remain explicitly deferred.

## REQUIREMENT COVERAGE

- TIP-scoped REQ-IDs addressed: **11/11 (100%)**.
- Completed through this TIP: **5/11** — REQ-013, REQ-017, REQ-018, REQ-019,
  REQ-021.
- Existing foundations advanced: **6/11** — REQ-004, REQ-006, REQ-014,
  REQ-026, REQ-027, REQ-029.
- Missing from the approved TIP-008 scope: **0/11**.

REQ-026 remains a product-level unified-workspace requirement and REQ-027 still
requires complete Việt/Anh plus automated accessibility qualification in TIP-011.
REQ-029 still requires the production CI/security/load program in TIP-012.

## SCENARIO RESULTS

Acceptance criteria: **18/18 PASS (100%)**.

| AC | Result | Independent evidence |
|---|---|---|
| AC-01 Catalog policy | PASS | Effective-principal filtering, signed cursor and denied-target leak probes |
| AC-02 Upload targets | PASS | Keyset scan crosses denied batches and returns authorized sources only |
| AC-03 Separate download | PASS | Version plus original-object authorization; view-only original is opaque 404 |
| AC-04 Byte ranges | PASS | Full/bounded/open/suffix/invalid/unsatisfiable `200/206/416` cases |
| AC-05 Narrow proxy | PASS | Literal/encoded/double-encoded traversal returns 400; header allowlists and `nosniff` |
| AC-06 Authentication gate | PASS | Anonymous UI issues zero file requests |
| AC-07 Catalog interaction | PASS | Search/filter/cursor/select/history and session-revoke clearing |
| AC-08 Upload lifecycle | PASS | Streaming upload, terminal polling and failed/retry/accepted browser flow |
| AC-09 Image/PDF | PASS | Safe renditions, OCR/page search and locator navigation |
| AC-10 DOCX/PPTX | PASS | Semantic PDF/text viewers with explicit fidelity warning |
| AC-11 XLSX | PASS | Sheet/grid/formula/merged-range and cross-sheet cell locator |
| AC-12 Media | PASS | Audio/video controls, range seek and transcript timecodes |
| AC-13 Safe failure | PASS | Strict hostile-manifest validation and access-loss removal |
| AC-14 Evidence Rail | PASS | Version/hash/quality/locator and server-authoritative download truth |
| AC-15 Deep links | PASS | Bounded locator parsing, history restoration and copyable link |
| AC-16 Accessibility/responsive | PASS | Keyboard/Escape/3 px focus; 360/768/1440 no page overflow |
| AC-17 Leak regression | PASS | Anonymous/cross-owner/classification/effective-deny/rendition/original; leak 0 |
| AC-18 Full health | PASS | Independent full gate, browser suite and healthy runtime |

## INDEPENDENT REFINE FINDINGS

The initial BUILD was returned to REFINE. Contractor review found:

1. **P0 proxy boundary:** `.` and `..` matched the route segment regex, while
   Next could normalize encoded dot paths before the file route.
2. **P1 capability truth:** catalog `can_download` checked the version but not the
   original object, unlike manifest/original enforcement.
3. **P1 locator state:** the XLSX active sheet did not follow later history/search
   locator changes.
4. **P1 revocation state:** rendition denial or session revocation could leave
   stale selected metadata visible.
5. **P2 response hardening:** the same-origin proxy stripped the backend
   `X-Content-Type-Options: nosniff`.
6. **P1 upload-target starvation:** a fixed pre-policy limit could exclude an
   authorized target behind denied candidates.
7. **P1 runtime validation:** manifest capability/rendition fields were not all
   validated before the TypeScript cast.
8. **P1 session loss:** catalog `401/403` initially left prior files and workspace
   state in memory.
9. **P2 upload memory:** client checksum generation used a full-file
   `arrayBuffer`, contradicting the streaming contract.

REFINE added a dependency-free raw HTTP guard plus Next middleware/route
defenses, exact version+object capability evaluation, locator-derived XLSX sheet
state, centralized access-loss clearing and foreground revalidation, `nosniff`
forwarding, keyset upload-target scanning, complete manifest schema checks and a
true streaming upload whose authoritative checksum is computed by the backend.
Regression tests cover every finding.

## TECHNICAL HEALTH

Independent `make verify` result: **PASS**.

- Web unit tests: **28/28**, four files.
- ESLint, strict TypeScript and Next production build: PASS.
- Production Playwright: **15/15**.
- Ruff: PASS.
- Strict mypy: PASS on **62 source files**.
- Backend: **159 passed, 35 integration/environment skipped**.
- Isolated PostgreSQL/data integration: **34 passed**.
- Migration revisions/fixtures: **7/7**; schema remains
  `0007_hybrid_rag_grounded_answers`.
- Supported formats: **14**; required rendition outputs: **31**.
- Policy scenarios retained: **48**; runtime database denials: **18**.
- Container build: PASS; Trivy: **0 detected OS/Python vulnerabilities**.
- Git diff check: PASS.

Warnings are limited to existing dependency deprecations and the read-only pytest
cache warning; none is a TIP-008 P0/P1/P2 failure.

## VISUAL AND RUNTIME VERIFICATION

Desktop and mobile screenshots were visually inspected. The workspace preserves
the RtR graphite/industrial identity, keeps the viewer dominant, and uses the
locator spine as the single signature element rather than a generic dashboard
card treatment. Mobile correctly collapses Catalog and Evidence Rail into
explicit controls without page-level overflow.

Runtime evidence:

- API, web, worker, PostgreSQL, Redis, MinIO and ClamAV are healthy.
- API/web readiness return `ready`.
- literal and double-encoded traversal probes return **400**.
- valid application routes remain available.
- PostgreSQL revision is `0007_hybrid_rag_grounded_answers`.

Screenshots:

- `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/web/test-results/tip008-desktop.png`
- `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/apps/web/test-results/tip008-mobile.png`

## DEFERRED BOUNDARY

- DOCX/PPTX are safe semantic/PDF previews, not layout-faithful Office editing.
- Browser-native PDF/media controls are used over authorized safe renditions.
- File-scoped Ask composition and final shared Evidence Rail belong to TIP-011.
- Full Việt/Anh, axe automation and production cross-browser qualification remain
  TIP-011/TIP-012.
- Production ingress/TLS defense, observability and load calibration remain
  TIP-012.
- Real company source data remains outside this TIP; only synthetic fixtures were
  used.

## OVERALL STATUS

**READY.** TIP-008 is accepted and provides the Files/viewer contract required by
TIP-009 Document OS and TIP-011 Unified UX.

Open P0/P1/P2 within TIP-008 implementation: **0**.
