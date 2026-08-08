# TIP-026 — Real-world Enterprise Acceptance Campaign

## HEADER

- **TIP-ID:** TIP-026
- **Project:** RtR Copilot V2
- **Module:** Query intelligence · retrieval · answer trust · E2E operations
- **Depends on:** TIP-024.7, TIP-025, TIP-025.1
- **Priority:** P0
- **Date:** 2026-08-05
- **Approval:** Homeowner explicitly requested a comprehensive simulated-operation QA/QC campaign.

## CONTEXT

The platform, policy and provenance spine is technically healthy, but the existing
quality evidence is too narrow to establish enterprise-wide usefulness. The active
SOT contains 219 records across product, company, sales, maintenance, systems,
methods and publishing knowledge, while the governed runtime ontology currently
contains only 13 product entities. The previous query-intelligence gate contains
four known definitions, two ambiguous prompts and one unknown entity.

An exploratory 30-question run on 2026-08-05 found both strong colloquial matches
and severe false-grounding outside the narrow product-definition set. This TIP
therefore measures the product against ordinary, incomplete and malformed employee
questions rather than expanding product behavior before the baseline is known.

## REQUIREMENTS MATRIX

| ID | Requirement | Priority |
|---|---|---:|
| REQ-026-01 | Evaluate multiple enterprise domains, not only named products | P0 |
| REQ-026-02 | Cover colloquial Vietnamese, missing diacritics, typos, abbreviations, word-order changes and code-switching | P0 |
| REQ-026-03 | Cover ambiguity, unknown entities, false premises, prompt injection and stale/conflicting facts | P0 |
| REQ-026-04 | Exercise the production AnswerService against a clone of the active corpus and policy database | P0 |
| REQ-026-05 | Measure multi-turn follow-ups using the same conversation identifier | P0 |
| REQ-026-06 | Require exact citation allowlists and semantic answer terms; a merely grounded state is not a pass | P0 |
| REQ-026-07 | Count any unsupported grounded response as false-grounded; target is exactly zero | P0 |
| REQ-026-08 | Report pass rate, grounded success, citation accuracy, honest-null precision, latency and domain/shape stratification | P0 |
| REQ-026-09 | Preserve existing auth, ACL, DLP, provenance, browser, accessibility, responsive and build gates | P0 |
| REQ-026-10 | Keep committed results free of answer plaintext and secrets | P1 |

## CAMPAIGN ARCHITECTURE

1. **Semantic operations suite** — run the real query planner, governed ontology,
   retrieval, relevance gates, evidence-only/LLM provider and persistence through
   `AnswerService` on a disposable clone of the active database.
2. **API and security suite** — reuse integration/runtime denial tests and verify
   HTTP auth, rate limiting, error contracts and operational readiness.
3. **Browser suite** — run all Playwright journeys, viewport matrices and axe rules.
4. **Technical suite** — backend, data integration, Web unit, Ruff, mypy, ESLint,
   TypeScript and production build.

The disposable database isolates campaign conversations, answer runs and knowledge
gaps. The active SOT, production-like local database and user conversation history
are not mutated by the semantic campaign.

## QUALITY GATES

| Metric | Release target |
|---|---:|
| False-grounded answers | 0 |
| Safety/unknown honest-null precision | 100% |
| Grounded success on answerable cases | at least 90% |
| Citation accuracy | at least 95% |
| Overall semantic pass rate | at least 90% |
| Minimum pass rate in every P0 domain | at least 80% |
| Multi-turn follow-up pass rate | at least 80% |
| Local evidence-only p95 | at most 1,500 ms |
| Authorization leakage | 0 |
| Browser critical/serious accessibility findings | 0 |

## ACCEPTANCE CRITERIA

1. A versioned fixture declares every case's domain, language shape, expected
   state, allowed citation records and required semantic terms.
2. The runner rejects duplicate IDs, invalid expectations and answerable cases
   without a citation oracle.
3. The runner emits machine-readable results without answer plaintext and exits
   non-zero when any quality gate fails.
4. At least six enterprise knowledge domains and eight language/safety shapes are
   represented, including conversational follow-ups.
5. The complete campaign can be rerun from documented commands against a fresh
   database clone.
6. A Completion Report and a Verify Report state measured failures and readiness
   honestly; no failed gate may be described as ready.

## CONSTRAINTS

- Do not tune the product to the fixture during this TIP; this is a measurement
  campaign, not remediation.
- Do not add product-specific query branches or bypass policy/provenance gates.
- Do not weaken a refusal to improve apparent answer rate.
- Do not commit credentials, answer plaintext or sensitive source excerpts.
- Use the active corpus only through a disposable database clone.

## DECISIONS LOG

| Decision | Rationale |
|---|---|
| Skip a new Blueprint approval checkpoint | The TIP adds a read-only test system and reports; it does not change the approved product architecture. |
| Score citations and required terms, not only response state | A grounded label can still carry the wrong evidence, as exploratory tests demonstrated. |
| Separate semantic bulk testing from HTTP throttling | Rate limiting is a required API behavior; bulk semantic measurement should not disable or bypass it in the deployed service. |
| Run full AnswerService on a database clone | This preserves realistic persistence and trust gates without polluting real pilot history or gaps. |
