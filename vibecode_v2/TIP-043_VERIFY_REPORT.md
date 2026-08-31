# TIP-043 Verify Report — Safe Technical-Debt Reduction

**Date:** 31/08/2026
**Verdict:** `PASS_LOCAL`
**Scope:** TIP-043.1 and TIP-043.2
**External network boundary:** no LLM, embedding, connector or crawler call

## Engineering gates

### Backend and telemetry

- Ruff: PASS.
- mypy: PASS — 150 source files.
- Full pytest with production font profile: **722 passed, 132 conditional
  skips**.
- Focused planner/observability suite: **56/56 passed**.
- Warm identical plan: first request recorded one provider call; second request
  recorded zero; two concurrent warm readers each recorded zero.
- Cache telemetry: hit, miss and capacity-eviction deltas asserted; all four
  metric families have zero labels.
- Metrics exposition and unbounded-label audit: PASS.

### Data and migrations

- Isolated data integration: **73/73 passed**.
- Full migration up/down chain and revision fixtures: PASS.
- Alembic legacy path-separator warning: absent.
- Pytest cache warning on the read-only integration mount: absent.
- Transaction rollback, restore, runtime-denial, Document OS and policy probes:
  PASS.

### Web and deterministic browser QA

- ESLint: PASS.
- TypeScript: PASS.
- Vitest: **209/209 passed** across 22 files.
- Next.js 16.2.11 production build: PASS.
- Canonical isolated runner, two consecutive full runs: **131/131 + 131/131
  passed**.
- Final runner smoke after log-hygiene adjustment: **131/131 passed**.
- Every run ended with `teardown=clean`; the disposable QA directory was
  removed and the runner's server PID no longer existed.
- `git diff --check` and shell syntax checks: PASS.

## Acceptance matrix

| Acceptance condition | Result | Evidence |
|---|---|---|
| Production browser runner owns port/start/readiness/output/teardown | PASS | isolated script and clean teardown assertions |
| Two consecutive 131-case production runs | PASS | 262/262 assertions on one rebuilt production artifact |
| Repository-owned Alembic and read-only pytest warnings removed | PASS | data-integration output |
| Third-party warnings not globally suppressed | PASS | Vosk/SWIG and Starlette warnings remain visible for dependency refresh |
| Cache hit/miss/eviction/current entries observable without content labels | PASS | Prometheus definitions plus privacy tests |
| Warm identical plan makes zero new provider calls | PASS | deterministic fake-provider contract |
| Async request usage remains task-local | PASS | concurrent cold and warm tests |
| Configuration changes invalidate shared planner reuse | PASS | runtime fingerprint regression |
| No real provider call or trust-boundary change | PASS | hermetic fakes only; code review and scope audit |

## Environment note

One exploratory full backend run used a bare Python image without the production
font set and produced a Vietnamese PDF extraction false negative. The identical
suite was rerun in the local production backend image and passed 722/722. This
was an environment mismatch, not a product defect, and no assertion was waived.
