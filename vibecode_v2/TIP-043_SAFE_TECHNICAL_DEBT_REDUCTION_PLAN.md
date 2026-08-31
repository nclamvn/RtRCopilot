# TIP-043 — Safe Technical-Debt Reduction Plan

## Header

- Date: 31/08/2026
- Depends on: TIP-042 local milestone
- Base candidate: `0cf2c91` plus uncommitted TIP-042 changes
- Scope: TIP-043.1 and TIP-043.2 implemented locally; TIP-043.3 deferred
- Priority: P1 maintainability and performance confidence
- Status: `DEFAULT_STOP_POINT_COMPLETE_LOCAL`

## Objective

Reduce only debt that has a visible operational payoff and can be changed with
small, independently reversible patches. Do not reorganize the architecture,
change API/database contracts, weaken trust boundaries or perform a wholesale
UI/CSS rewrite.

## Selection rules

A debt item enters this plan only when all conditions hold:

1. It addresses measured latency, recurring QA noise, defect recurrence or
   developer/on-call cost.
2. It has characterization coverage before behavior is moved.
3. It can ship and roll back independently.
4. It does not change user-visible answer semantics, authorization, SOT,
   grounding, API schema or database schema.
5. Its full regression cost fits the existing local suite and requires no
   external LLM, embedding, crawler or connector call.

## Ordered work packages

### TIP-043.1 — Deterministic QA runner and owned warning hygiene

**Value:** high for release confidence. **Risk:** very low. **Effort:** 1–2 h.

- Add one canonical command that serves the production Next.js build on an
  isolated port and runs Playwright against it, avoiding Next Dev Tools and
  browser-storage pollution.
- Make the command own server startup, readiness, teardown and port selection.
- Remove warnings owned by the repository, such as Alembic's missing
  `path_separator` and pytest cache writes on a read-only verification mount.
- Do not suppress third-party deprecation warnings globally.

**Acceptance:** two consecutive full runs produce 131/131 pass; no orphaned
server; existing `make verify` remains green; no application source behavior
changes.

### TIP-043.2 — Planner-cache telemetry and local performance contract

**Value:** high for proving latency/cost benefit. **Risk:** low. **Effort:** 2–3 h.

- Add content-free cache hit, miss, eviction and current-entry metrics to the
  shared semantic rewriter.
- Never place a question, entity, ontology content, credential or user ID in a
  metric label.
- Add hermetic concurrency and configuration-invalidation tests.
- Add a local benchmark/probe proving that a warmed identical plan uses zero
  provider calls and that task-local usage accounting remains correct.
- Keep exact answer and retrieval behavior unchanged.

**Acceptance:** metrics expose only bounded counters/gauges; warm-cache test
shows provider-call delta 0; 720+ backend tests and data integration pass; no
real provider invocation.

### TIP-043.3 — One-component Ask-page extraction

**Value:** medium for lowering future UI blast radius. **Risk:** low when done
one component at a time. **Effort:** 3–5 h.

- Extract only `ProcessingInspector` and its local types/helpers from the large
  Ask page into a dedicated component module.
- Preserve markup, class names, accessible names, state ownership and CSS
  exactly; this is a file-boundary change, not a redesign.
- Add/retain a component-level characterization test, then run the 131-case
  browser matrix and visual snapshot comparison.
- Stop after this single extraction. Attachment picker and answer rendering
  require separate future evidence before being scheduled.

**Acceptance:** DOM/accessibility snapshot unchanged; no screenshot geometry
drift; 209 web unit and 131 browser tests pass; Ask page line count decreases
without adding a new styling layer.

## Deferred intentionally

| Debt | Decision | Reason |
|---|---|---|
| Split the whole 2.5K-line `answering.py` | Defer | High semantic and concurrency blast radius; no current defect requires it |
| Rewrite retrieval or ontology lifecycle | Defer | Changes quality/freshness architecture and needs a separate benchmark/design review |
| Merge all CSS layers | Defer | High visual-regression surface across every workspace |
| Upgrade FastAPI/Starlette/httpx/Vosk solely to silence warnings | Defer | Dependency churn is larger than the current operational benefit |
| Add database indexes without a measured slow query | Reject for now | Optimization without query-plan evidence creates write and migration cost |
| Rename/reformat across the repository | Reject | Large diff, near-zero product or operational value |

## Delivery discipline

- Complete and verify TIP-042 before starting this sequence.
- One work package per commit; no mixed refactor and behavior change.
- Maximum recommended patch size: 250 changed application lines per package.
- Mandatory gates after each package: `git diff --check`, Ruff, mypy, backend
  tests, data integration where applicable, ESLint, TypeScript, web unit,
  production build and the relevant browser matrix.
- If a package needs an API/schema change, a second CSS layer, or more than one
  large module extraction, stop and re-plan instead of widening scope.

## Recommended order and stop point

1. TIP-042 local milestone completed; commit remains an explicit later action.
2. TIP-043.1 implemented and certified.
3. TIP-043.2 implemented and certified.
4. Measured benefit and code health recorded in the Completion/Verify reports.
5. TIP-043.3 remains deferred unless continued Ask UI development justifies it.

The default stopping point is after TIP-043.2. At that point QA is repeatable
and the performance optimization is observable. TIP-043.3 is useful but not a
release prerequisite.

## Implementation note — 31/08/2026

The approved default scope was implemented without widening into TIP-043.3.
The production-browser gate now owns an ephemeral loopback port, disposable
standalone tree, readiness, Playwright output and teardown. The semantic
planner cache now emits label-free hit/miss/eviction/current-entry telemetry
and has a local warm-cache/task-isolation contract. No external provider was
called and no answer, retrieval, authorization, SOT or database contract was
changed.
