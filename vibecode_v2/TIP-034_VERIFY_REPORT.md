# VERIFY REPORT — TIP-034

## Live technical-capture addendum — 13/08/2026

**Candidate:** `9b019832e08a`
**Run ID:** `fef13ede-4b61-450c-b1f4-84e64b00fadc`
**Status:** `TECHNICAL_CAPTURE_PASS / HUMAN_EVALUATION_PENDING`

| Gate | Result | Verdict |
|---|---:|---|
| Immutable cases | 27 selected, 27 unique | PASS |
| Overall | 27 passed, 0 failed | PASS |
| Grounded success | 1.0 | PASS |
| Citation accuracy | 1.0 | PASS |
| Honest-null precision | 1.0 | PASS |
| False grounded | 0 | PASS |
| Follow-up recovery | 1.0 | PASS |
| P95 latency | 19,148.973 ms ≤ 25,000 ms | PASS |
| Domain strata | 7/7 at pass rate 1.0 | PASS |
| Human observations | 0/27 | PENDING |

The technical capture ran exactly once with concurrency one, browser-off,
without rebuild, embeddings, reindex, connectors or production operations.
Temporary E2E containers and cloned database were cleaned up; the seven pilot
services remained healthy. No retry was performed.

The historical report below remains useful as implementation evidence, but its
“external capture not started” statement is superseded by this addendum.

### Provenance debt closure — TIP-035.5

The historical raw report remains byte-for-byte immutable and therefore still
shows the two fields as null. TIP-035.5 closes the open P1 without rewriting
history:

- every future HTTP campaign collects database and ontology digests from the
  exact API container connected to its disposable clone before question one;
- missing, malformed or build-mismatched provenance fails before any question
  is posted;
- the database digest covers active records, generations, chunks, vector
  hashes, locators and ACL-relevant fields;
- a separate post-capture attestation binds this historical report hash to the
  unchanged pilot snapshot: database
  `911fef5626fede0bb2b2f1002f6acc8cbcae3004f808769f184b4245ed6d526e`
  and ontology
  `15e76e881503ea35f9e9d6c061426e7b17d271442ee9d17a7aad831bcffd5f37`.

P1 status: **CLOSED**. The raw capture is retained as historical evidence; its
content is not silently backfilled.

**Date:** 12/08/2026
**Environment:** Local Docker production image + isolated Python 3.12 verifier
**Runtime build:** `5c4049d17cd9+90cb5f148fbe`
**Campaign:** `tip034.enterprise-pilot-usefulness`
**Campaign digest:** `6a745f0cd8d75ad5c8a9c22b6ff1a3d764129040db5bd970d6a3366fdf2ddb34`

## Summary

| Layer | Result | Status |
|---|---:|---|
| Manifest/source binding | 27 unique cases, exact suite SHA-256 | PASS |
| Domain coverage | 7/7 required domains | PASS |
| Conversation coverage | 3 complete two-turn scenarios | PASS |
| Clarification/honest-null | 3 / 3 | PASS |
| Messy-query minimum | ≥ 12 encoded in manifest gate | PASS |
| Focused regressions | 27 passed | PASS |
| Full backend | 635 passed, 128 conditional skipped | PASS |
| Ruff / mypy strict | clean / 141 files | PASS |
| Production manifest command | verdict `not_started`, sample 0 | PASS TRUTHFULLY |
| Runtime verifier | external provider; grounded answering ready | PASS |
| External capture | blocked without approval | PASS SAFE |
| Real pilot observations | 0 / 27 | NOT STARTED |

## Requirement traceability

| Requirement | Evidence | Verdict |
|---|---|---|
| AC-01–AC-04 | Source digest, manifest validator and committed strata | PASS |
| AC-05 | Duplicate and incomplete-completion regressions | PASS |
| AC-06 | Question/run/build/timestamp binding regressions | PASS |
| AC-07 | Technical facts derived inside `evaluate_pilot_campaign` | PASS |
| AC-08 | Required authz/cost trace digests; zero-tolerance shared gates | PASS |
| AC-09 | Empty observation ledger | NOT STARTED |
| AC-10 | Generated result contains only digests, counts and metrics | PASS |
| AC-11 | No-approval shell probe exits 2 before E2E startup | PASS |
| AC-12 | Static analysis, unit suite and production manifest command | PASS |

## Anti-gaming proof

- Removing one case from a completed ledger returns `insufficient_sample` and
  fails `all_manifest_cases_observed`.
- Reusing a case under another observation ID fails schema validation.
- Changing the source-suite digest, question digest or runtime build fails loud.
- An observation timestamp earlier than its source report is rejected.
- Citation counts and latency cannot be overridden by the human ledger.
- One-domain-heavy sampling cannot satisfy domain minimum and maximum-share
  gates.

## Security and disclosure

- No credential, prompt, answer or evidence snippet is written to the pilot
  result.
- The only live wrapper is exact-scope and fail-closed.
- No network-bound campaign was run during local verification.
- `../_to_delete/` is user-owned and untouched.

## Verdict

**TIP-034 IMPLEMENTATION READY; ENTERPRISE PILOT NOT YET CERTIFIED.** The campaign
can now produce an auditable GO/NO-GO, but the truthful current state remains
`not_started` until a separately approved live capture and real tester
observations exist.
