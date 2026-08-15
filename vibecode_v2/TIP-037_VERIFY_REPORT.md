# TIP-037 Verify Report — Multimodal Composer & Attachment-to-Context

**Date:** 15/08/2026
**Verdict:** `PASS_LOCAL`
**Base commit:** `7644563096c91942cb8fe295fa18804099685ccd`

## Verification evidence

### Backend

- Ruff: PASS.
- mypy: PASS — 146 source files.
- pytest: **706 passed, 132 conditional integration skips**.
- Isolated data-integration pytest: **73 passed**.
- Migration revision fixtures and complete up/down chain: PASS.
- Non-empty Document OS backup/restore proof: PASS.
- Runtime-denial probes: **27/27 denied as designed**.
- Multi-file SQL proof: both authorized versions can contribute; one denied
  version returns an empty scope before any file content query.

### Web

- Vitest: **201/201 passed** across 20 files.
- TypeScript: PASS.
- ESLint: PASS.
- Next.js production build: PASS.
- Playwright browser/accessibility/responsive matrix: **127/127 passed**.
- TIP-037 focused browser cases: denied catalog, immutable `version_ids`,
  390 px geometry/touch targets — PASS.

### Live rebuilt UI

- URL: `http://127.0.0.1:3000/ask`.
- Desktop viewport inspected: 1280×720.
- Composer: 820×112; attachment picker: 620×448.
- Picker remained inside the viewport and document horizontal overflow was 0.
- Selecting a catalog entry produced one visible chip and one
  `aria-pressed=true` item without closing the multi-select surface.

### Runtime

Healthy primary services: `api`, `worker`, `web`, `postgres`, `redis`, `minio`,
`clamav` — **7/7 healthy**.

## Trust assertions

1. The UI submits immutable version UUIDs, not filenames as authority.
2. Duplicate or more-than-five version sets are rejected at the API boundary.
3. Authorization of the full set precedes retrieval of any file chunk.
4. Candidate and evidence budgets remain global per Ask request.
5. Uploads reuse Files ingestion; only terminal `accepted` state enters context.
6. No attachment data is stored in URLs or web storage.
7. No external LLM or embedding processing occurred during this TIP.

## Release interpretation

TIP-037 is complete for local development but is not a production release
attestation. TIP-036 and TIP-037 are published together as one local-product
milestone; production configuration and release gates remain separate.
