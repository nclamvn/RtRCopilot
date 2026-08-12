# COMPLETION REPORT — TIP-033

**STATUS:** IMPLEMENTED / CONDITIONAL — code, local production runtime and all
non-external quality gates pass. The immutable five-case live latency and quality
recertification is intentionally pending a new explicit export approval.

**Date:** 12/08/2026
**Runtime build:** `5c4049d17cd9+af5df0e43390`

## Delivered

- Added additive typed SSE metadata: monotonic sequence, per-stage duration and
  fixed milestones `intent_ready`, `sources_ready`, `evidence_ready`,
  `draft_ready`, `answer_ready`.
- Preserved the trust boundary: no prompt, snippet, draft answer or chain of
  thought is streamed. Answer text remains buffered until grounding, current
  lineage and persistence authorization succeed.
- Removed resolved-question text from progress events and retained only bounded,
  caller-authorized source metadata.
- Added first-useful-source timing and milestone histograms, including
  `result_ready`, for latency-tail diagnosis.
- Added an intent-aware synthesis lane: routine definition, lookup and
  enumeration use configurable low reasoning; comparison, procedure and
  analysis retain high reasoning. Structured output and deterministic grounding
  are unchanged.
- Right-sized output ceilings for point lookup, definition, catalog and governed
  entity profiles without changing the evidence schema or citation contract.
- Rebuilt the Ask thinking state as a restrained evidence-first stream with
  elapsed time, five-stage spine, source readiness, a 20-second extended-state
  message and an explicit trust disclosure. Reduced-motion mode disables all
  progress animation.
- Added strict client parsing and compatibility defaults for legacy progress
  payloads; forged milestones, negative timing and unbounded source counts fail.
- Added `make tip033-recertify`; its five-case set is immutable and the command
  fails before network access unless `TIP033_APPROVE_EXTERNAL=1` is present.
- Extended runtime drift detection to certify
  `RAG_ANSWER_ROUTINE_REASONING_EFFORT=low` inside the actual API container.
- Removed the retired three-column `.ask-progress` contract from `ask.css`.
  It had survived beneath the final Ask stylesheet and split the new progress
  children across columns. The active component now owns one explicit vertical
  layout, including a complete reduced-motion text reset.

## Verification completed

- Backend: **628 passed**, 128 conditional skips; focused TIP-033: 18 passed.
- Data integration/migration/restore/policy gate: **PASS**; containerized phase
  reported 69 passed and final probe summary reported migrations 12,
  required outputs 31, policy scenarios 48 and runtime denials 27.
- Web unit: **189/189 passed**.
- Browser/accessibility/responsive: **126/126 passed**; Ask-specific: 22/22,
  including coordinate-level regression proof for the vertical progress stack.
- Ruff, mypy (139 source files), ESLint, TypeScript and production build: PASS.
- Runtime verifier: provider external, OpenAI embeddings 1536, routine reasoning
  low, credential and approved policy loaded, build identity exact.
- Containers: **7/7 healthy** (`api`, `worker`, `web`, `postgres`, `redis`,
  `minio`, `clamav`).
- Fail-loud approval probe: `make tip033-recertify` exits 2 without the TIP-033
  acknowledgement and emits only the exact case identifiers.

## Pending release evidence

AC-09 and AC-10 still require one bounded external run for exactly:
`OPS-010`, `SYS-007`, `MTH-004`, `PRD-001`, `PRD-023`. The release target is
5/5, false-grounded 0, citation accuracy 1.0, p95 at most 25,000 ms and no case
at or above 45,000 ms. TIP-032 authorization is not reused implicitly.

## Known boundary

The active-state visual is covered by component/browser behavior tests, but the
real provider-duration screenshot and final latency artifact can only be captured
during the approved bounded run. This is a release evidence gap, not a runtime
configuration gap.

## Rollback

Set `RAG_ANSWER_ROUTINE_REASONING_EFFORT=medium` and recreate `api`/`worker` to
restore the TIP-032 reasoning lane. SSE additions are optional and backwards
compatible, so the transport/UI work can remain in place.
