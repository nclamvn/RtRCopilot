# TIP-018 · Completion Report — Real Per-File Retrieval

**Status:** BUILT · VERIFIED<br>
**Date:** 04/08/2026<br>
**Branch:** `agent/tip-018-per-file-retrieval`<br>
**Baseline:** `064d5db6f77f19624e43e9cd0f25f547a79643b4`

## Outcome

The Ask workspace now retrieves and grounds answers inside an immutable,
ACL-viewable file version. File evidence is no longer approximated through a
SOT `source_key`. Private content stays in a dedicated evidence plane and every
persisted citation deep-links to the exact document version and locator.

## Built

- Added migration `0010_file_retrieval` with immutable `file_chunks`, hybrid
  lexical/vector indexes and XOR SOT/private citation references.
- Added deterministic indexing for verified PDF, DOCX, XLSX, PPTX, OCR and
  transcript JSON renditions during ingest.
- Added an idempotent backfill command for verified pre-existing renditions;
  local demo invokes it automatically.
- Added `SearchFilters.version_id`; it is mutually exclusive with `source_key`.
- Implemented security-first file retrieval through the same effective
  resource lineage and `view` policy used by Files.
- Enforced exact `document_version_id` equality in both metadata and content
  SQL; content is loaded only after authorization.
- Added private citation persistence, exact source/rendition checksums, deep
  locators and conversation-time authorization rechecks.
- Changed Ask UI scope requests to immutable `version_id`; the Evidence Rail
  accepts only server-labelled `sot` or `private` grounded citations.
- Runtime role can SELECT/INSERT file chunks but cannot UPDATE/DELETE them.

## Acceptance evidence

| AC | Result | Evidence |
|---|---|---|
| AC-01 | PASS | Allowed version returns private grounded citation with exact version, checksum and page locator; persistence/replay DB probe passes. |
| AC-02 | PASS | Two-file byte probe never exposes B while scoped to A; SQL repeats version equality in both phases. |
| AC-03 | PASS | Classification ceiling, explicit deny and denied≡nonexistent all return empty/honest-null behavior. |
| AC-04 | PASS | Cross-file/miss probe cannot fall through to company SOT or another file. |
| AC-05 | PASS | Existing SOT retrieval/answer suites remain green in the 48-test DB gate and 411-test backend gate. |
| AC-06 | PASS | Existing sentence-level grounding verifier is unchanged; grounded file answer and revoked replay probes pass. |
| AC-07 | PASS | Exact target at ordinal 206 (beyond candidate limit) is present in top-5 after whole-version SQL ranking (Recall@5 = 1.0). |

## Verification summary

- Backend: Ruff clean; Mypy clean across 104 source files; Pytest **411 passed,
  112 skipped**, zero failures.
- Web: Vitest **150/150**; ESLint, TypeScript and production build pass.
- Live data gate: **48/48**, migrations 10/10, 20 runtime mutation denials.
- TIP-018 live leak/ACL/grounding matrix: **2/2**.
- Browser/accessibility: Playwright + axe **88/88**.
- Container scan: **0 HIGH / 0 CRITICAL**.
- Migration gate: one head, `0010_file_retrieval`, matching runtime pin.

## Rollback

Disable file scope in the client, then downgrade to `0009_governance_research`.
The downgrade removes private citations and file chunks but does not modify
source files, renditions or SOT data. SOT-only retrieval remains independently
available throughout.

## Residual limits

- OCR/transcript content is searchable only when its optional local engine
  produced a verified rendition; otherwise the result is honest-null.
- This TIP does not make private file evidence canonical SOT. Graduation still
  requires the existing curator/publish gate.
