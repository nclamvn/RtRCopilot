# TIP-042 Completion Report — Product Hardening, Performance & UX

**Date:** 31/08/2026
**Status:** `COMPLETE_LOCAL`
**Base commit:** `0cf2c91`
**Delivery:** approved for atomic commit/push with TIP-043 after local verification
**External processing:** 0 LLM calls; 0 embedding calls; 0 connector calls

## Outcome

The whole-product X-ray found no reason to rebuild the core architecture. The
high-value remediation was narrower: preserve the semantic planner's existing
bounded TTL cache across request-local answer services, and remove concrete
mobile Ask interaction defects. Grounding, authorization, DLP, evidence
verification, honest-null behavior and request-local retrieval state are
unchanged.

## Delivered

- Added a bounded process-local runtime rewriter pool with a maximum of eight
  entries.
- Bound every shared planner to a SHA-256 fingerprint covering active ontology
  digest, export allowlist, credential digests, provider models, timeouts,
  prompt-cache settings, candidate/cache limits, breaker policy and Redis
  route. No raw credential is retained in the pool key.
- Kept `AnswerService`, `RetrievalService`, conversation state and retrieval
  trace request-local; only the `ContextVar`-scoped external planner is reused.
- Kept offline/test planning fresh and stateless, so hermetic execution gains
  no shared mutable network state.
- Added unit coverage for reuse, configuration invalidation and offline
  isolation.
- Reworked the 760 px composer controls so scope, attachment, options and send
  fit without overlap; attachment/options remain 44 px controls with their
  accessible names intact.
- Enlarged the related-information close action from 30 px to 44 px.
- Added geometry, overlap, document-overflow and touch-target browser
  assertions at 390 px.

## Product X-ray

| Surface | Finding | Disposition |
|---|---|---|
| Query intelligence | `AnswerService` is correctly request-local, but rebuilding its external rewriter discarded the 3,600 s / 2,048-entry plan cache after every request | Resolved by configuration- and ontology-bound reuse |
| Concurrency | Retrieval traces and answer-service ontology state are mutable | Preserved request-local; no unsafe singleton introduced |
| Mobile Ask | Full context labels competed with the send column at 375–390 px | Resolved with compact 44 px icon actions and fit assertions |
| Mobile rail | Inspector close action measured 30×30 px | Resolved at 44×44 px |
| Security | Runtime image scan found no HIGH/CRITICAL finding in the configured gate | Clean |
| General hygiene | No actionable TODO/FIXME/HACK markers, web `console` calls, `any` escapes or TypeScript-ignore debt found | Clean |

## Remaining debt register

These items are real maintainability debt but are not hidden as release bugs:

1. **P2 — module size:** `rag/answering.py` (~2.5K lines),
   `documents/service.py` (~1.7K) and `rag/retrieval.py` (~1.3K) should be split
   only behind characterization tests; a bulk extraction now would increase
   release risk without reducing current user latency.
2. **P2 — UI composition:** Ask page (~1.7K lines) and the layered CSS cascade
   contain repeated selectors. Consolidation should proceed component by
   component after visual snapshots, not through a wholesale stylesheet
   rewrite.
3. **P3 — dependency warnings:** Vosk/SWIG and Starlette test-client warnings
   come from pinned third-party packages. Track during the next dependency
   refresh; there is no current functional or vulnerability finding.
4. **P3 — QA ergonomics:** a development Next.js server injects Dev Tools and
   storage state, so strict browser certification must continue against the
   production build or rebuilt runtime.

## Runtime boundary

The primary seven-service local runtime remains healthy, but was deliberately
not recreated from an uncommitted working tree. The verified production build
was served temporarily on a separate localhost port for browser certification
and then stopped. Commit/build binding and runtime rebuild belong to the next
explicit milestone.
