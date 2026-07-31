# TIP-007 · Independent Verify Report

**Date:** 31/07/2026  
**Verifier:** Contractor · Vibecode Kit v6.1  
**Overall status:** READY — policy-filtered Hybrid RAG and grounded-answer
backend verified; company SOT activation and the complete Ask UI remain deferred.

## REQUIREMENT COVERAGE

- TIP-scoped REQ-IDs addressed: **9/9 (100%)**.
- Fully implemented in this TIP: **5/9** — REQ-007, REQ-008, REQ-009,
  REQ-010, REQ-011.
- Foundation advanced for later end-to-end completion: **4/9** — REQ-015,
  REQ-018, REQ-028, REQ-031.
- Missing from the approved TIP-007 scope: **0/9**.

## SCENARIO RESULTS

Acceptance criteria: **17/17 PASS (100%)**.

| AC | Result | Independent evidence |
|---|---|---|
| AC-01 Schema | PASS | Migration `0007` upgrade, downgrade and head checks |
| AC-02 Outbox consumption | PASS | Activated SOT only; deterministic, idempotent generations |
| AC-03 Atomic indexing | PASS | Candidate generation remains hidden until atomic activation |
| AC-04 Hybrid retrieval | PASS | Lexical, vector and reciprocal-rank fusion paths exercised |
| AC-05 Policy before content | PASS | Metadata candidates resolved before authorized content fetch |
| AC-06 Effective ACL | PASS | User, group, role, department and project deny precedence |
| AC-07 Policy/DLP before prompt | PASS | Recheck and redaction precede provider invocation |
| AC-08 Grounding | PASS | Factual units require citations and evidence overlap |
| AC-09 Deep citations | PASS | Source/version/locator/evidence metadata persisted |
| AC-10 Honest null | PASS | Insufficient evidence returns no model-generated answer |
| AC-11 Provider resilience | PASS | Bounded timeout and one repair attempt; no hanging request |
| AC-12 Conversation safety | PASS | Authorized persistence with sanitized question/gap handling |
| AC-13 Citation race | PASS | Advisory locks plus exact generation/version/policy recheck |
| AC-14 Revocation | PASS | Revoked or replaced source cannot be committed as evidence |
| AC-15 Auditability | PASS | Correlated retrieval, answer and denial/gap events |
| AC-16 Regression/leak | PASS | Full gate; denied-content leak count is zero |
| AC-17 Performance | PASS | Recall@5 1.000, MRR 0.900, exact-ID 1.000, p95 6.80 ms |

## INDEPENDENT REFINE FINDINGS

Initial BUILD was not accepted immediately. VERIFY found and corrected:

1. **P0 effective ACL gap:** deny evaluation initially covered only the direct
   user principal, not group, role, department and project assignments.
2. **P0 citation race:** source state could change between citation validation
   and final answer persistence.
3. **P0 input DLP gap:** a secret embedded in the user's question could reach
   persistence or the provider.
4. **P1 grounding weakness:** paragraph-level checking could permit an uncited
   factual sentence.
5. **P1 provider availability:** an unbounded provider call could hang a request.
6. **P1 retrieval starvation:** applying a metadata limit before policy filtering
   could hide authorized records behind denied candidates.
7. **P1 verification isolation:** simultaneous gates initially collided on one
   fixed verification database/bucket.

REFINE added effective-principal deny resolution, final-transaction advisory
locks and source-state checks, input DLP before persistence/provider use,
factual-unit grounding validation, bounded provider timeout, policy-aware
candidate pagination and unique per-run verification resources. Regression
coverage was added for each path.

## TECHNICAL HEALTH

Independent `make verify` result: **PASS**.

- Web lint/typecheck/Vitest/production build: PASS; **1/1** test.
- Ruff: PASS.
- Strict mypy: PASS on **62 source files**.
- Backend unit/API regression: **158 passed, 34 integration/environment skipped**.
- PostgreSQL data integration: **33 passed**.
- Migration revisions/fixtures: **7/7**.
- Policy scenarios retained: **48**.
- Runtime database denials: **18**.
- Supported formats retained: **14**; required rendition outputs: **31**.
- Retrieval benchmark: **Recall@5 1.000, MRR 0.900, exact-ID 1.000,
  p95 6.80 ms**.
- Container vulnerability scan: **0 detected OS/Python vulnerabilities**.
- Git diff check: PASS.
- Local deployment smoke: API, worker and web healthy; API/web readiness **200**;
  PostgreSQL revision `0007_hybrid_rag_grounded_answers`.

Warnings are limited to dependency deprecations and a read-only pytest cache
warning; none is a TIP-007 P0/P1/P2 failure.

## PRODUCT BOUNDARY

The implementation provides the secured retrieval and answer core through API,
including citations, honest-null behavior, DLP and durable conversations. It is
not yet the finished Spotlight-like product experience:

- the current web shell does not yet expose the complete Ask/Evidence Rail UI;
- real company SOT data remains intentionally unactivated pending controlled
  provenance repair, approval and signing;
- the local deterministic 64-dimensional hashing embedding is appropriate for
  functional regression, not a production semantic-quality claim;
- production provider configuration, representative-corpus calibration and
  performance qualification remain later work.

No file under the live kernel, KnowledgeBase registry or GOI/research sources was
modified or indexed by this TIP.

## OVERALL STATUS

**READY.** TIP-007 is accepted and provides the backend contract for TIP-008 and
the later Ask workspace/evidence experience.

Open P0/P1/P2 within TIP-007 implementation: **0**.
