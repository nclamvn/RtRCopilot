# TIP-034 — Enterprise Pilot Operations & Usefulness Campaign

**Status:** Implemented locally · campaign not started
**Date:** 12/08/2026
**Owner:** RtR Copilot
**Method:** Vibecode Kit v6.1 — Contractor / Builder / Homeowner

## 1. Problem statement

TIP-032 introduced a truthful usefulness/trust/latency/cost scorecard, but its
observation sample remains zero. The enterprise E2E suite is already broad — 77
turns across company, products, operations, systems, methods, safety and
conversation — yet a tester could still manufacture a pilot GO by copying easy
results, evaluating a stale build or entering observations unrelated to a real
run.

The missing product capability is therefore an operational contract that binds
human usefulness judgement to the exact question, exact runtime build, exact E2E
run and immutable enterprise strata without storing question or answer plaintext
in the scorecard report.

## 2. Decision

Create a provenance-bound 27-case campaign selected from the existing governed
77-turn oracle:

- Product 4; company 4; operations 4; systems 3; methods 3; safety 3;
  conversation 6.
- Three complete two-turn conversations; no follow-up may be tested without its
  anchor.
- Three ambiguity/clarification probes and three honest-null cases.
- At least 12 messy-query observations; explicit minimums for broad,
  colloquial, exhaustive and follow-up shapes.
- Every manifest case is mandatory; a completed campaign cannot omit a hard
  case while retaining a GO verdict.

Reuse the TIP-032 scorecard rather than create another metric system. Add a
campaign evaluator that derives citation, honest-null, false-grounded and
latency facts from a build-bound acceptance report. Human input is limited to
usefulness, clarification recovery, authorization leakage attestation and
provider-cost attestation.

## 3. Trust and disclosure boundary

- The committed campaign contains case IDs, strata and digests; the generated
  scorecard contains no question or answer plaintext.
- An observation is invalid unless question digest, run ID, runtime build and
  report timestamp all match.
- Authorization and cost require trace digests. Missing attestations fail schema
  validation; they are not silently treated as zero.
- The live capture script is fail-closed and locks the exact 27-case set.
- Running local validators does not authorize sending internal questions or
  evidence to an external LLM. Live capture requires a new, purpose-bound human
  approval through `TIP034_APPROVE_EXTERNAL=1`.

## 4. Work packages

### Contractor

- Freeze campaign scope against the SHA-256 of the existing enterprise suite.
- Define domain, shape, messy-query, clarification, honest-null, trust, latency
  and cost gates.
- Keep TIP-033 recertification and TIP-034 pilot capture as separate approval
  purposes.

### Builder

- Add strict campaign, observation and ledger contracts.
- Add source-suite, question-digest, report, timestamp and runtime-build binding.
- Add a content-free evaluator that feeds the existing scorecard.
- Add operator commands for definition check, live capture and final evaluation.
- Record runtime build identity in all future HTTP acceptance reports.

### Homeowner

- Recruit internal testers who have real company context, not only developers.
- Judge usefulness from the employee task outcome, not lexical similarity.
- Review failures by domain and query shape; never repair only the named example.
- Authorize external processing only for the immutable campaign and approved
  endpoint.

## 5. Acceptance criteria

| ID | Gate |
|---|---|
| AC-01 | Campaign source digest matches the governed 77-turn suite. |
| AC-02 | Manifest contains exactly 27 unique cases and all seven required domains. |
| AC-03 | All three follow-ups include their preceding conversation anchors. |
| AC-04 | At least three clarification probes, three honest-null cases and 12 messy queries are present. |
| AC-05 | Completed campaign requires all 27 cases; no duplicate case or observation can be counted. |
| AC-06 | Each observation binds to exact question digest, run ID, report timestamp and one runtime build. |
| AC-07 | Citation, honest-null, false-grounded and latency values are derived from the E2E report, not manually entered. |
| AC-08 | Authorization and provider cost carry trace digests; false-grounded and authorization leakage remain zero. |
| AC-09 | Shared TIP-032 gates hold: usefulness ≥ 0.80, clarification recovery ≥ 0.80, citation accuracy ≥ 0.95, p95 ≤ 25 s and average cost ≤ USD 0.10. |
| AC-10 | Scorecard/report remain content-free. |
| AC-11 | Live script refuses to run without explicit external-processing approval and refuses any changed case set. |
| AC-12 | Ruff, mypy, backend unit tests and production manifest check pass. |

## 6. Operator workflow

```bash
make pilot-campaign-check

# Only after purpose-bound approval of the exact manifest:
TIP034_APPROVE_EXTERNAL=1 make tip034-pilot-capture

# After human usefulness/authz/cost attestations are entered:
make pilot-campaign-evaluate
```

`pilot-campaign-check` is safe and local. `tip034-pilot-capture` can invoke the
configured external LLM and therefore stays blocked until explicitly approved.

## 7. Rollback

- Remove TIP-034 targets and evaluator without changing the TIP-032 scorecard or
  production answer pipeline.
- Restore the observation ledger to `not_started` only when no real observations
  exist; never discard a real pilot ledger to improve the verdict.
- Any source-suite change invalidates the manifest digest and requires a new
  campaign version, not an in-place edit.

## 8. Current gate status

- AC-01–AC-08, AC-10–AC-12: **PASS locally**.
- AC-09: **NOT STARTED** — no live 27-case report or human observations exist.
- Current result is intentionally `not_started`, sample 0, not a pilot GO.
- TIP-033 live latency recertification remains a separate pending approval.
