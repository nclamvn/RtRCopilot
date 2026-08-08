# TIP-027 — Verify Report

## REQUIREMENT COVERAGE

| Requirement | Result | Evidence |
|---|---|---|
| AC-01 source inventory | PASS | Catalog distinguishes active, approved and backlog sources with gates |
| AC-02 reuse company kernel | PASS | Existing 219-chunk SOT publish/reindex path retained |
| AC-03 deterministic TheSkyWatch adapter | PASS | Canonical fingerprint and package contract verified |
| AC-04 field provenance and honest null | PASS | Values, tier, confidence, URLs and spans retained; null/unverified excluded |
| AC-05 published editorial evidence only | PASS | 68 published articles admitted; sample/unpublished excluded |
| AC-06 deterministic rebuild | PASS | Identical inputs produce identical package members/fingerprint |
| AC-07 parser/tamper/drift rejection | PASS | Adapter and parser regression tests pass |
| AC-08 domain/noisy-language evaluation | CONDITIONAL | Suite exists and hermetic QA passes; final external-LLM campaign awaits provider credit |
| AC-09 explicit curator activation | PASS | Dry-run default; apply requires approval and active curator identity |
| AC-10 honest coverage report | PASS | 4,085 Ask units reported separately from 1,838 Research records and backlog |

**Implementation coverage: 10/10. Final live acceptance: pending.**

## CORPUS AND PROVENANCE CHECKS

- Active SOT: 219 chunks.
- Approved company files: 43 current documents and 3,866 searchable chunks.
  - TIP-024 internal: 22 documents / 2,096 chunks.
  - TIP-024 restricted: 8 documents / 1,156 chunks.
  - TIP-027 internal: 12 documents / 463 chunks.
  - TIP-027 restricted: 1 document / 151 chunks.
- Default company Ask total: 4,085 searchable units.
- TheSkyWatch Research: 1,838 records / 8,162 admitted fields; tier composition
  P 550, S 390, H 91, X 807; fingerprint
  `0c6c201e6b8b3d09f7bee3628696b1d517c231d398107282dd8ed2eed7494f73`.
- TIP-027 company manifest: 13/13 verified; fingerprint
  `7c4afb6ebaa9908917408f367e2c7f7be5680f7232e7e0cd7d3160543c06cfed`.
- Office pipeline v4 reprocessed 22/22 affected documents. Superseded rendition
  chunks remain auditable but are excluded by the active-resource retrieval
  predicate.

## SCENARIO RESULTS

- CRM service-request procedure: PASS — grounded quality-LLM answer preserves
  the complete B1–B9 sequence with nine citations and the canonical CRM subject.
- MRP maturity/operating readiness: PASS — grounded answer cites the maturity
  assessment and operating pipelines without product-domain leakage.
- Hải Phòng UAV-IOC project: PASS — grounded only in the approved Hải Phòng
  project document.
- Quảng Ninh UAV-IOC project: PASS — grounded only in the approved Quảng Ninh
  project document.
- Explicit procedure intent under external planning: PASS — cannot be changed
  into enumeration/catalog.
- Company scope plus specific subject: PASS — company context does not create a
  false requirement that every answer sentence repeat the company name.
- False grounding in focused regression: 0 observed.

### Enterprise E2E campaign state

- Latest complete HTTP campaign: **71/77 passed (92.2%)**, grounded success
  **91.4%**, citation accuracy **92.9%**, honest-null precision **100%**,
  **0 false-grounded**, follow-up pass **100%** and p95 **60.51 s**. It remains
  NO-GO because citation accuracy missed 95% and p95 exceeded 60 s by 0.51 s.
- Domain pass rates: company 80%, conversation 90%, methods 100%, operations
  100%, product 91.3%, safety 100%, systems 87.5%.
- All five live browser scenarios passed in that campaign.
- Selective live passes before the final remediation included HERA battery,
  SkyWatch 360, Sales Brief filename, HERA maintenance classification and the
  two-turn CRM technology-stack conversation.
- Diagnostics on the remaining stochastic failures identified reviewer false
  negatives (`called_quality_review_failed`), a four-word definition-subject
  heuristic (`called_answer_irrelevant`) and citationless structural prose
  (`called_factual_unit_ungrounded`). The final patch addresses those causes at
  reviewer, relevance and ontology-contract layers and passes 148 focused
  regression tests plus the full hermetic suites.
- Blocking external response: HTTP 429,
  `insufficient_quota / credit_balance_exhausted`. This is provider-account
  state, not a retrieval or UI contract failure. The application continues to
  refuse safely when high-quality synthesis is unavailable.

## TECHNICAL HEALTH

- Backend full suite: **555 PASS**, **127 conditional skips**.
- Isolated PostgreSQL integration pytest: **68/68 PASS**.
- Migration, rollback, failing-DDL rollback and non-empty backup/restore drill:
  **PASS** (`DATA INTEGRATION PASS`).
- Web unit: **182/182 PASS**.
- Browser, responsive, accessibility and keyboard matrix: **125/125 PASS**.
- Ruff: **PASS**.
- mypy: **PASS** across 129 source files.
- ESLint: **PASS**.
- TypeScript: **PASS**.
- Next.js production build: **PASS**.
- Runtime readiness: seven containers healthy; API operational health and the
  browser-facing status route pass after a forced API/worker/web rebuild.
- Answer runtime: external provider configured, credential present, approved
  endpoint/classification policy loaded and grounded-answering configuration
  ready. This configuration probe does not imply that the provider account has
  remaining credit. Credential value was not exposed.

## DEFERRED ITEMS

- TIP-027.3 live enterprise connectors are not implemented.
- TIP-027.4 Research federation into default Ask is not implemented.
- Project/CRM/MRP coverage is materially broader but still a curated snapshot,
  not complete coverage of every file or live transaction.
- HRM authoritative source and owner were not discovered.

## OVERALL STATUS

**CONDITIONAL / NOT FINAL READY.** TIP-027.1 and TIP-027.2 pass hermetic local
QA and their corpus breadth is no longer limited to basic product facts. Final
acceptance requires restoring provider credit and passing:

```bash
E2E_APPROVE_FULL=1 E2E_SKIP_BUILD=1 \
  E2E_ENV_FILE=.env.demo ./scripts/run-enterprise-e2e.sh
```

The product is also not yet the complete RtR ecosystem until live connectors,
further owner-approved manifests and Research federation are delivered.
