# TIP-042 Verify Report — Product Hardening, Performance & UX

**Date:** 31/08/2026
**Verdict:** `PASS_LOCAL`
**Base commit:** `0cf2c91`
**External network boundary:** no LLM, embedding, connector or crawler call

## Engineering gates

### Backend

- Ruff: PASS.
- mypy: PASS — 150 source files.
- pytest: **720 passed, 132 conditional integration skips**.
- New planner-pool coverage: same-contract reuse, relevant-setting
  invalidation and offline isolation all PASS.
- Isolated data-integration: **73/73 passed**.
- Migration up/down chain, revision fixtures, rollback, non-empty restore,
  runtime-denial and Document OS probes: PASS.

### Web

- ESLint: PASS.
- TypeScript: PASS.
- Vitest: **209/209 passed** across 22 files.
- Next.js 16.2.11 production build: PASS.
- Full Playwright browser/accessibility/responsive/keyboard regression on the
  production build: **131/131 passed**.
- Focused 390 px composer/touch regression: PASS.
- Visual inspection of the generated 390 px screenshot: scope, attachment,
  options and send controls remain separated and bottom-anchored.

### Security and operations

- Trivy image scan: **0 detected vulnerabilities** in the configured gate.
- Docker Compose build of API, worker and web: PASS.
- Primary local services inspected: API, worker, web, Postgres, Redis, MinIO
  and ClamAV — **7/7 healthy**.
- `git diff --check`: PASS.

## Acceptance matrix

| AC | Result | Evidence |
|---|---|---|
| AC-01 request services reuse the same eligible external planner | PASS | runtime getter integration in both constructor and ontology refresh path; unit identity assertion |
| AC-02 ontology/config changes invalidate reuse | PASS | SHA-256 contract key and changed-model unit test |
| AC-03 TTL plan cache survives service boundaries with task-local usage | PASS | shared `ExternalLLMRewriter`; existing concurrent `ContextVar` test plus reuse test |
| AC-04 offline mode remains hermetic | PASS | distinct offline-adapter unit test; zero external calls |
| AC-05 mobile composer does not overlap or overflow | PASS | Playwright geometry and document-width assertions at 390 px |
| AC-06 mobile Ask actions meet the touch contract | PASS | attachment, options, send and inspector-close measurements |
| AC-07 configured QA gates pass | PASS | engineering, security and operations evidence above |

## QA environment note

An initial full browser run on a Next.js development server produced four
environment-only failures because Dev Tools injected an extra button and one
session-storage entry. The same source was then certified using its production
build, where all 131 cases passed. No product assertion was waived.
