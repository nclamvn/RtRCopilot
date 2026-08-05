# TIP-026 Verify Report

**Date:** 2026-08-05
**Environment:** Local production-like Docker stack + disposable database clone
**Campaign verdict:** PASS
**Product verdict:** NOT READY for broad enterprise pilot

## Requirement coverage

| Requirement | Status |
|---|---:|
| REQ-026-01 multi-domain evaluation | Implemented |
| REQ-026-02 dirty and ordinary language | Implemented |
| REQ-026-03 ambiguity/safety/conflict cases | Implemented |
| REQ-026-04 production AnswerService on database clone | Implemented |
| REQ-026-05 multi-turn conversations | Implemented |
| REQ-026-06 citation and semantic-term oracle | Implemented |
| REQ-026-07 zero-tolerance false-grounding metric | Implemented |
| REQ-026-08 metrics and stratification | Implemented |
| REQ-026-09 existing technical/security gates retained | Implemented |
| REQ-026-10 no committed answer plaintext/secrets | Implemented |

**Coverage:** 10/10 = 100%.

## Scenario results

| Metric | Target | Actual | Result |
|---|---:|---:|---:|
| Overall semantic pass | at least 90% | 43/73 = 58.9% | FAIL P0 |
| Grounded success | at least 90% | 40/65 = 61.5% | FAIL P0 |
| Citation accuracy | at least 95% | 69.2% | FAIL P0 |
| Honest-null precision | 100% | 3/8 = 37.5% | FAIL P0 |
| False-grounded | 0 | 29 | FAIL P0 |
| Minimum domain pass | at least 80% | safety 37.5% | FAIL P0 |
| Follow-up pass | at least 80% | 1/5 = 20% | FAIL P0 |
| Local evidence-only p95 | at most 1,500 ms | 288.9 ms | PASS |

### Domain stratification

| Domain | Passed | Total | Rate |
|---|---:|---:|---:|
| Methods | 5 | 6 | 83.3% |
| Operations | 8 | 12 | 66.7% |
| Systems | 5 | 8 | 62.5% |
| Company | 6 | 10 | 60.0% |
| Product | 11 | 19 | 57.9% |
| Conversation | 5 | 10 | 50.0% |
| Safety | 3 | 8 | 37.5% |

## Technical health

| Gate | Result |
|---|---:|
| Seven runtime containers | HEALTHY |
| API operational capability | `evidence_only` |
| Backend | 455 passed, 119 skipped |
| mypy strict | PASS, 120 files |
| Campaign scorer teeth | 6 passed |
| Campaign Ruff | PASS |
| Data integration | 61 passed |
| Migration fixtures | 12/12 PASS |
| Runtime denial probes | 27/27 PASS |
| Web unit/contracts | 176 passed |
| ESLint / TypeScript / production build | PASS |
| Browser / axe / responsive | 106/106 PASS |
| Full repository Ruff | FAIL: six pre-existing migration E501 findings |

## Root-cause assessment

1. **Question→evidence relevance is lexical, not answerability-aware.** For an
   unresolved entity, any meaningful-token overlap can pass the gate. Approved but
   irrelevant evidence can therefore become a confidently displayed answer.
2. **Evidence-only selects the first eligible chunk verbatim.** It intentionally
   cannot synthesize, compare, convert units, resolve conflicts or determine that a
   top-ranked snippet does not answer the requested attribute.
3. **The active query registry is not enterprise-wide.** The packaged bootstrap
   ontology has 13 products and no people, company, policy, system, method, project,
   customer or HR entities. Unsafe aliases and cross-domain name collisions are not
   governed by an active enterprise release.
4. **Conversation storage is not conversation understanding.** Prior messages are
   persisted and displayed, but `AnswerService.ask` plans each question without
   loading a bounded policy-safe history or resolved entity state.
5. **Semantic infrastructure is incomplete.** `OfflineHashEmbedding` and absent
   approved LLM credentials/policy leave deterministic lexical retrieval carrying a
   workload it cannot reliably solve.

## Required remediation sequence

### TIP-026.1 — Query Safety & Semantic Reranking (P0)

- Introduce a typed answerability decision before generation: `supported`,
  `clarification_required`, `unsupported`.
- Replace one-token overlap with attribute/intent support and a bounded semantic
  reranker or approved LLM evidence judge.
- Add an independent final question→claim entailment reviewer.
- Treat unknown, gibberish, injection and out-of-domain prompts as abstention unless
  explicit evidence support crosses calibrated thresholds.
- Exit gate: false-grounded 0 and safety 100% on TIP-026.

### TIP-026.2 — Governed Enterprise Ontology Expansion (P0)

- Onboard domains for company, people, systems, policies, methods, projects,
  customers and organization units.
- Remove or scope unsafe short aliases such as `hr`; add collision tests for product
  versus business terms and The Sky Watch versus SkyWatch 360.
- Bind records to stable entity/concept/attribute IDs and activate only through the
  TIP-025 evaluation/release ledger.

### TIP-026.3 — Conversational Query State (P0)

- Load a bounded, authorized and DLP-inspected conversation window.
- Persist resolved entity/intent state separately from prose history.
- Resolve pronouns and ellipsis through the same governed ontology; ambiguity still
  requires clarification.
- Exit gate: follow-up pass at least 80%, leak 0.

### TIP-026.4 — Quality LLM Synthesis and Independent Review (P0)

- Approve external-processing policy and credentials for the selected provider(s).
- Use LLM planning for messy language and multi-hop/comparison requests, bounded by
  ontology candidates and authorized evidence.
- Require claim-level citations plus an independent reviewer; fall back to strict
  extraction or honest-null on any failure.
- Calibrate cost, p95 latency and provider fallback with real measurements.

### TIP-026.5 — Human Pilot and Release Re-evaluation (P1)

- Add anonymized real employee prompts to the immutable suite after curator review.
- Run at least two weeks with domain-stratified metrics and false-grounding incident
  review.
- Activate enterprise release only after every P0 gate passes and named owners sign.

## Decision required from Homeowner

Authorize the remediation sequence above before a broad pilot. The Contractor
recommendation is to start with TIP-026.1 immediately; expanding corpus or UI first
would increase the surface area of wrong answers without fixing the trust boundary.

The first campaign invocation also left clearly tagged local test telemetry: 73
answer runs across 68 conversations and four gaps with request IDs beginning
`tip026-d07ab5ea-`. Preserve it as audit evidence, archive the conversations, or
perform an explicit scoped cleanup after backup; no deletion was performed during
VERIFY.

## Overall status

**NOT READY.** The software engineering, security, persistence and UI foundations are
strong, but generalized answer trust is below the minimum threshold for real company-
wide use. A limited supervised demo remains possible for explicitly curated direct
questions; it must not be represented as an enterprise-ready assistant.
