# TIP-026 Completion Report

**Date:** 2026-08-05
**Status:** DONE — campaign infrastructure complete; product quality gate failed

## Files changed

### Created

- `vibecode_v2/TIP-026_REAL_WORLD_ENTERPRISE_ACCEPTANCE_CAMPAIGN.md` — requirements,
  taxonomy, gates and isolation design.
- `v2/eval/real_world/cases.json` — 63 single-turn cases and five two-turn
  conversations, totalling 73 measured turns.
- `v2/eval/lib/operational_acceptance.py` — pure fixture validation, semantic
  scoring, stratification and release-gate evaluation.
- `v2/eval/run_real_world_acceptance.py` — full AnswerService runner.
- `v2/eval/real_world/baseline_summary.json` — sanitized machine-readable baseline;
  no answer plaintext or credentials.
- `v2/apps/backend/tests/test_operational_acceptance_unit.py` — five teeth tests.
- `vibecode_v2/TIP-026_VERIFY_REPORT.md` — Contractor verification and backlog.

### Modified

- None. This TIP deliberately measures the approved product architecture without
  tuning runtime behavior to the test fixture.

## Acceptance criteria

| AC | Result | Evidence |
|---|---:|---|
| Versioned multi-domain fixture | PASS | 73 turns, seven domains, 57 shapes |
| Fixture rejects missing oracle/duplicate/invalid cases | PASS | hermetic unit tests |
| Wrong grounded citation counts as false-grounded | PASS | scorer teeth test |
| Full AnswerService runs on isolated active-corpus clone | PASS after guard | 219/219 records cloned; verified run changed clone by 73 runs and source by 0 |
| Machine-readable report excludes answer plaintext | PASS | baseline summary contract |
| Non-zero quality gates are enforced | PASS | campaign result `passed=false`; seven of eight gates failed |
| Completion and Verify reports created | PASS | this report and TIP-026 Verify Report |

**Acceptance criteria tested:** 7/7 passed for campaign delivery.

## Test results

- Campaign scorer unit tests: **6 passed**.
- Campaign new files Ruff: **PASS**.
- Backend: **455 passed, 119 skipped**.
- mypy strict: **120 source files, zero issues**.
- Web: **176 passed**; ESLint, TypeScript and production build **PASS**.
- Browser/accessibility/responsive: **106/106 passed**.
- Data integration: **61 passed**; 12 migration fixtures, 48 policy scenarios,
  27 runtime denials and non-empty restore proof **PASS**.
- Full repository Ruff: **FAIL** on six pre-existing E501 lines in migration
  `0012_enterprise_governance.py`; no campaign file fails Ruff.

## Issues discovered

1. **P0 — False grounding:** 29/73 turns returned a grounded answer that did not
   satisfy the citation/semantic oracle.
2. **P0 — Safety abstention:** honest-null precision is 37.5%; out-of-scope,
   fabricated, gibberish and enterprise-abbreviation prompts can retrieve unrelated
   approved records.
3. **P0 — Conversation continuity:** follow-up pass rate is 20%; the persisted
   conversation identifier is not used to resolve pronouns or ellipsis.
4. **P0 — Enterprise identity collisions:** the bootstrap ontology is 13/13 product
   entities. `HR` resolves to HERA through the alias `hr`; “The Sky Watch” competes
   with the product SkyWatch 360.
5. **P0 — Answerability gate too weak:** one overlapping meaningful token can pass
   question→evidence and question→answer relevance even when the record does not
   answer the question.
6. **P1 — Retrieval quality:** runtime still uses `OfflineHashEmbedding`; broad,
   typo and paraphrase ranking is not calibrated on enterprise language.
7. **P1 — No governed enterprise release:** the local database has no approved
   enterprise domains, active ontology revision or release attestation; runtime is
   using the packaged bootstrap registry.
8. **P1 — Lint debt:** six long SQL lines make the full backend Ruff command fail.

## Deviations

- Bulk semantic cases ran through AnswerService directly rather than the HTTP rate
  limiter. This was intentional: the API limiter was tested separately and correctly
  returned HTTP 429 after its window, while bulk semantic scoring required a stable
  measurement path. Auth, API, persistence and browser contracts remain covered by
  integration and Playwright suites.
- **Isolation incident:** the first baseline invocation used `DATABASE_DSN`, while
  backend configuration reads `POSTGRES_DSN`. It therefore wrote 73 tagged answer
  runs, 68 conversations, 146 messages, 69 citations and four gaps into the local
  development database. No SOT, ontology, ACL or source record changed. The runner
  now requires `--expected-database`, enforces the `rtr_tip026_` prefix and compares
  the connected database before loading a subject. The verified rerun proved source
  campaign-run count remained 73 while the clone increased by exactly 73. Existing
  audit/history was not silently deleted; cleanup requires an explicit Homeowner
  decision.

## Suggestions for Contractor

- Do not begin a broad employee pilot on the current answer path.
- Implement TIP-026.1 Query Safety & Semantic Reranking before increasing corpus or
  enabling more users.
- Follow with enterprise ontology expansion, conversation context and an approved
  quality-LLM synthesis/reviewer route; rerun this exact immutable fixture after each
  change.
