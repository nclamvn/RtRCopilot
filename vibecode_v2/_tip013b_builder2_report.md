# TIP-013B Part B · Builder-2 Report — answer-time confidence caveat

## STATUS
DONE. The honesty feature is wired end-to-end: an answer grounded on any
soft-tier fact now carries an additive `confidence_caveat` flag, and `/ask`
renders a small, legible, a11y-reachable double-check caveat beneath the answer
ONLY on those answers. Additive only — no retrieval/grounding/DLP change, no
schema migration, tokens frozen, honest-null untouched. All gates green;
AC-3/AC-4 proven (backend integration run against a real head-migrated DB, plus
hermetic unit + web render/parse tests).

## FILES CHANGED (additive; no retrieval/grounding/DLP/schema change)
Backend:
- `apps/backend/src/rtr_copilot/rag/models.py` — additive fields:
  `AskResponse.confidence_caveat: bool = False` and per-citation
  `Citation.needs_double_check: bool = False` (defaults keep every existing
  path unchanged; never persisted).
- `apps/backend/src/rtr_copilot/rag/answering.py` — pure/total predicate
  `needs_double_check(value)` (reads Part A's `value["confidence_signal"]`);
  read-only `AnswerService._soft_cited_version_ids(selected)` that looks up
  `record_versions.value_payload` for the ALREADY-selected citations only; the
  grounded return sets `confidence_caveat=bool(soft)` and marks the soft
  citations. Retrieval/ranking/DLP/grounding logic untouched.
- `apps/backend/tests/sot_fixtures.py` — `build_package(..., confidence_signal=)`
  merges the marker into the primary record's `value` (flows verbatim into
  `value_payload` at publish).
- `apps/backend/tests/test_rag_unit.py` — `test_needs_double_check_fires_only_for_the_soft_marker`
  (hermetic; soft→True, strict/missing/malformed/hostile→False, never raises).
- `apps/backend/tests/test_rag_integration.py` — `publish_and_index(...)` threads
  provenance + `confidence_signal`; new `test_confidence_caveat_set_only_when_a_soft_fact_is_cited`.
Web:
- `apps/web/src/ask/contracts.ts` — `AskAnswer.confidenceCaveat: boolean`;
  `parseAskAnswer` validates `confidence_caveat` is boolean-or-absent and sets
  the flag only when the answer is `grounded` (never inferred client-side).
- `apps/web/src/app/(shell)/ask/page.tsx` — renders `<p role="note"
  className="confidence-caveat">{t("ask.confidenceCaveat")}</p>` inside the
  grounded-answer region, gated on `current.confidenceCaveat`.
- `apps/web/src/i18n/messages.ts` — `ask.confidenceCaveat` vi + en twin (parity
  enforced by `MessageKey` typecheck + runtime i18n guard).
- `apps/web/src/app/styles.css` — one appended rule `.confidence-caveat` (no
  existing rule modified).
- `apps/web/src/app/(shell)/ask/page.test.tsx` — jsdom render test (flagged →
  caveat note renders; the existing grounded test now asserts unflagged → none).
- `apps/web/src/ask/contracts.test.ts` — parse test (flag rides only a grounded
  answer; non-boolean rejects).
- `apps/web/tests/browser/ask.spec.ts` — flagged fixture + a Playwright test for
  the caveat note; the default grounded test asserts the unflagged case.

## HOW THE FLAG IS DERIVED (rides ALONG the existing grounding)
The `confidence_signal` marker lives in `record_versions.value_payload`, not on
the chunk/citation. At answer time, AFTER the citations are already selected and
persisted, `_soft_cited_version_ids` does a read-only lookup of those citations'
`record_version_id`s and applies the pure `needs_double_check` predicate. It
returns version-ids only (no content leaves; these records already passed policy
+ DLP during retrieval). Nothing about what is retrieved, ranked, filtered or
grounded changes; the flag is a response field, never stored.

## TEST RESULTS (before → after)
Backend:
- ruff: pass → **pass**
- mypy: 99 src files → **99** (change is inside existing rag modules)
- pytest **unit**: 323 passed / 108 skipped → **324 passed / 109 skipped**
  (+1 unit `test_needs_double_check…`; +1 integration correctly skipped without a DB)
- RAG **integration** (one-DB): 13 → **14 passed** — proven locally against a
  fresh, head-migrated DB in the running compose stack (pgvector), then dropped.

Web:
- lint (eslint): pass → **pass**
- typecheck (tsc): pass → **pass** (i18n parity incl. the new key)
- vitest: **146 → 148 passed** (19 files) — +1 `ask/contracts.test.ts`, +1
  `(shell)/ask/page.test.tsx`
- build (next build): pass → **PASS**
- Playwright ask spec: 12 → **13 tests** — compiles + `--list` clean, new test
  discovered at `ask.spec.ts:244`. See ISSUES: the browser RUN could not be
  executed in this sandbox.

### Flagged-vs-unflagged proof
- Backend integration (real DB): soft fact cited → `confidence_caveat is True`
  AND every returned `citation.needs_double_check is True`; strict-only → both
  `False`; honest-null (no permitted evidence) → `confidence_caveat is False`,
  `citations == []`.
- Web jsdom render: flagged grounded answer renders the caveat as `role="note"`
  with the vi text incl. "vui lòng kiểm chứng lại"; the strict-grounded test
  asserts the caveat text is absent.
- Web contract parse: `confidenceCaveat` true only when `confidence_caveat===true`
  AND `state==="grounded"`; a non-boolean caveat throws `invalid_ask_response`.
- Playwright: flagged answer surfaces the caveat note; default grounded answer
  asserts `getByText(/vui lòng kiểm chứng lại/)` count 0.

## ISSUES
- **Playwright browser RUN blocked by the sandbox.** Any long-lived `next start`
  server reproducibly terminates the tool call with exit 144 (empty logs, server
  never binds), and this persisted even with the sandbox disabled — an
  environment/harness constraint on long-lived listeners, not a code fault. The
  spec is syntactically valid and lists 13 tests; the caveat RENDER is proven by
  the jsdom component test (real DOM render via testing-library). Per the work
  order the Contractor runs the browser stage — recommend it re-run the ask spec
  there (ci-local `browser` stage, `next start` + `PLAYWRIGHT_BASE_URL`).

## DEVIATIONS
1. Field shape: chose `confidence_caveat: bool` (matches AC-3 wording) over the
   `confidence: "standard"|"needs_review"` enum alternative. Per-citation
   `needs_double_check: bool` added too (clean, additive, tested).
2. Caveat is **answer-time only**. Reopened conversation history
   (`GET /conversations/{id}`) does not re-derive the caveat — that would need
   the same value_payload lookup for persisted citations (cleanly addable later
   with no migration), but it is outside the AC. Documented, not fabricated.
3. Contrast (documented): `.confidence-caveat` uses `--ink` (#e8e6e3) on `--bg`
   (#0d0f11) ≈ **15.4:1** (far above WCAG AA 4.5:1) — the same foreground token
   the answer body uses, never a faint grey; a `--signal` (#e56b46) 3px left
   rule is a ~6:1 non-text accent. Fully static → reduced-motion safe.
   `role="note"`, real text in the answer region, keyboard/screenreader reachable.
4. Marker detection is a pure, total predicate (any non-marker value → False,
   never raises/coerces) so the flag logic is provable hermetically; the DB
   lookup is a thin read-only wrapper proven by the integration test.

## SUGGESTIONS (for the Contractor to probe)
- **Per-citation rail chip: NOT added on the web** (deliberate — avoids threading
  `needsDoubleCheck` through `EvidenceEntry` + rail render + broad test churn; the
  answer-level caveat is the AC). The backend already exposes
  `citation.needs_double_check` and the rail parser tolerates it (unknown key
  ignored), so a subtle "cần kiểm chứng" zone-style chip is a clean follow-up.
- Re-run the ask Playwright spec in the browser stage (couldn't run here; exit
  144). Expect 13 tests incl. the new caveat-note test.
- Decide whether conversation-history replay should also surface the caveat
  (same read-only `value_payload` lookup, no migration) — currently answer-time
  only, by design.
- Honest-null and strict-only paths keep `confidence_caveat=false` by default —
  verified, but worth a spot-check in the Contractor's full-suite rerun.
