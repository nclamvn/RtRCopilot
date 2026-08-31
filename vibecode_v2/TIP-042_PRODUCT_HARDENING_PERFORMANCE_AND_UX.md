# TIP-042 — Product Hardening, Performance & UX

## Header

- Date: 31/08/2026
- Base candidate: `0cf2c91`
- Scope: local codebase hardening and QA; no production operation
- External processing: forbidden for this milestone
- Status: `COMPLETE_LOCAL` — see Completion and Verify reports

## Context

The product core is mature, but a whole-codebase X-ray identified two concrete
sources of avoidable friction. Runtime `AnswerService` instances are correctly
request-local, yet each instance also rebuilds the external semantic rewriter,
discarding its bounded query-plan cache between requests. On narrow screens,
the Ask composer keeps full text labels for every context action and can clip
or collide near the send control; the related-information close control is
also smaller than the 44 px touch contract.

This milestone improves reuse and interaction precision without weakening SOT
grounding, authorization, DLP, honest-null behavior or evidence verification.

## Decisions log

| ID | Decision | Rationale |
|---|---|---|
| D-042-01 | Keep `AnswerService` and `RetrievalService` request-local | Their ontology/retrieval state is mutable; sharing them would create concurrency risk |
| D-042-02 | Pool only the external semantic rewriter by a non-secret configuration fingerprint and ontology digest | Preserves its TTL cache across requests while binding plans to the active governed ontology |
| D-042-03 | Do not pool the deterministic offline rewriter | It has no expensive state or cache to preserve |
| D-042-04 | Compact mobile context actions into unambiguous 44 px controls | Prevents clipping without removing scope or attachment capability |
| D-042-05 | Retain the existing monochrome evidence-desk visual direction | This is hardening, not a visual redesign |
| D-042-06 | Run no real LLM, embedding, connector or crawler call | Performance architecture can be certified hermetically |

## Requirements

| ID | Requirement | Priority |
|---|---|---:|
| REQ-042-01 | Every Ask retains current authorization, DLP, grounding and citation behavior | P0 |
| REQ-042-02 | Eligible external semantic rewriters are reused across request-local answer services | P0 |
| REQ-042-03 | Rewriter reuse is invalidated by ontology or relevant configuration changes and never exposes secrets in cache keys | P0 |
| REQ-042-04 | Request usage accounting remains task-local under concurrency | P0 |
| REQ-042-05 | The 375–390 px Ask composer has no clipped/colliding context controls or horizontal document overflow | P0 |
| REQ-042-06 | Visible mobile Ask actions, including closing related information, meet the 44 px touch contract | P0 |
| REQ-042-07 | Backend lint/type/tests, web lint/type/unit/build and browser/accessibility/responsive regression pass | P0 |
| REQ-042-08 | Runtime health and live local UI are inspected without invoking external providers | P0 |
| REQ-042-09 | Remaining large-file and CSS-layering debt is recorded rather than hidden by an unsafe bulk rewrite | P1 |

## Acceptance criteria

- **AC-01:** two independently constructed runtime answer services receive the
  same external rewriter for the same settings and ontology digest.
- **AC-02:** a relevant configuration or ontology digest change receives a
  distinct rewriter.
- **AC-03:** repeat query-plan calls can use the existing TTL cache across
  request-service boundaries; provider usage remains correctly scoped.
- **AC-04:** offline/test mode remains hermetic and does not gain shared mutable
  network state.
- **AC-05:** at 390 px the Ask context controls fit before the send control,
  have no overlap and the document has no horizontal overflow.
- **AC-06:** every visible Ask action covered by the mobile test is at least
  44×44 px where it is an icon-only control.
- **AC-07:** all configured QA gates pass with zero real external calls.

## Out of scope

- Production deployment, production secrets or connector activation.
- External TIP-033/TIP-034 recertification.
- Corpus reindexing or embeddings.
- A wholesale split of the 2.5K-line answering module or replacement of the
  established CSS cascade; these require separate behavior-preserving changes.

## Closure evidence

- [TIP-042 Completion Report](TIP-042_COMPLETION_REPORT.md)
- [TIP-042 Verify Report](TIP-042_VERIFY_REPORT.md)
