# TIP-018 · Verify Report

**Decision:** VERIFIED<br>
**Date:** 04/08/2026<br>
**Verifier role:** Contractor / independent acceptance pass

## Verdict

TIP-018 satisfies all seven acceptance criteria. The implementation preserves
the SOT path, introduces no cross-plane masquerade, and fails closed before any
private content query when the version is absent, denied, above the requested
classification ceiling, quarantined or no longer active.

## High-risk invariants reviewed

1. **Plane integrity:** private renditions cannot enter SOT `chunks`; their
   schema and citations are explicitly labelled `private`.
2. **Authorization before content:** effective lineage policy is evaluated
   before `file_chunks.display_text` is selected.
3. **Version isolation:** metadata and content queries both require the exact
   requested `document_version_id`.
4. **TOCTOU defense:** selected chunks are revalidated inside the grounded
   answer transaction.
5. **Revocation:** conversation replay rechecks version lineage; revoked
   content and citations are withheld.
6. **Append-only evidence:** runtime UPDATE/DELETE against `file_chunks` is
   denied; citation source is constrained to SOT XOR private.
7. **No existence oracle:** denied and nonexistent versions produce the same
   empty retrieval result and honest-null answer behavior.

## Gate record

| Gate | Result |
|---|---|
| Migration upgrade/downgrade/idempotence | PASS — 10 revisions, single head |
| Full backend lint/type/unit | PASS — 411 passed, 112 skipped |
| Live DB integration | PASS — 48 passed |
| TIP-018 isolation/ACL/grounding/replay | PASS — 2 passed |
| Web unit/lint/type/build | PASS — 150/150 |
| Playwright + axe | PASS — 88/88 |
| Runtime mutation denial | PASS — 20/20 |
| Container HIGH/CRITICAL | PASS — 0/0 |

## Scope audit

No provider-policy weakening, no SOT publish bypass, no authentication change,
no external dependency and no destructive source-file migration were introduced.
The only data-destructive rollback behavior is removal of the new private index
and its private citations, as documented in the TIP.

## Next authorized step

Re-run and close TIP-014 against the restored live DB gate, then continue the
TIP-023–025 production-readiness sequence.
