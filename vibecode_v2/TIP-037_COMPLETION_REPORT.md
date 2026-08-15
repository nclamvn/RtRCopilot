# TIP-037 Completion Report — Multimodal Composer & Attachment-to-Context

**Date:** 15/08/2026
**Status:** `COMPLETE`
**Base commit:** `7644563096c91942cb8fe295fa18804099685ccd`
**Runtime:** rebuilt primary local stack; 7/7 containers healthy
**External processing:** 0 LLM calls; 0 embedding calls

## Outcome

The Ask composer now accepts up to five governed file contexts. An employee can
select authorized versions from the Files catalog or upload a supported file
through the existing TIP-008 ingestion pipeline. Ask receives exact immutable
`version_ids`; raw browser bytes, local paths and client-extracted text never
become answer authority.

The backend authorizes the complete set before loading any chunk. A denied,
missing or over-ceiling version makes the whole file scope return no evidence.
Authorized files share one vectorization, one content query, one candidate
limit and one evidence-byte budget, so adding files does not multiply the
latency or memory ceiling.

## Delivered

- Backward-compatible `version_id` plus bounded, unique `version_ids` contract.
- Mutual exclusion between company source, one-file and multi-file boundaries.
- All-or-nothing authorization before the first content query.
- Union retrieval with precise per-version citation provenance.
- Compact monochrome attachment picker, search, removable media chips and
  explicit five-file counter.
- Upload handoff to the governed Files API with progress and terminal
  acceptance before attachment activation.
- Access-loss/new-conversation cleanup of private attachment state.
- Vietnamese/English copy, keyboard semantics, reduced-width layout and 44 px
  mobile touch targets.
- Hermetic browser mocks for the TIP-036 planner and TIP-037 upload capability;
  test requests can no longer fall through to the live API and invalidate the
  mock identity.

## Acceptance result

| AC | Result | Evidence |
|---|---|---|
| 01 legacy one-file compatibility | PASS | model compatibility and integration suite |
| 02 two authorized files | PASS | real PostgreSQL integration retrieval |
| 03 denied member fails whole set | PASS | integration assertion before content load |
| 04 invalid/mixed/duplicate/oversized input | PASS | backend unit contract tests |
| 05 select/remove/max-five/exact payload | PASS | web unit and Playwright Ask suite |
| 06 upload activates only after acceptance | PASS | web unit upload state-machine test |
| 07 private state cleared on access loss | PASS | component state and revocation regression |
| 08 keyboard/a11y/mobile | PASS | 127/127 browser matrix |
| 09 engineering gates | PASS | backend, web, integration and build gates |

## Scope boundary

This closes local TIP-037 only. Connector activation, native chat/Slack,
production OIDC/TLS/secrets and production deployment remain deliberately out
of scope. TIP-036 changes already present in the worktree were preserved and
verified together; `../_to_delete/` was not touched or staged.
