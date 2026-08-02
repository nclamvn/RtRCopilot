# TIP-013B · Phase B Work Order — Curation, Confidence Caveat, Activation Prep

## HEADER

- **TIP-ID:** TIP-013B (Phase B work package under TIP-013)
- **Depends on:** TIP-013 Phase A VERIFIED; migration dress rehearsal
- **Status:** ISSUED
- **Working dir:** `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2`
- **Homeowner directives (02/08/2026):**
  1. Maximize autonomous support on the curation.
  2. **Accept `verified_primary` facts without a formal evidence span** — but
     each MUST carry a short source note, and facts whose grounding is not
     strict enough MUST be flagged so answers built on them surface a small,
     necessary caveat (like the "AI can make mistakes, please double-check"
     line under a composer) — shown ONLY on those answers, not blanket.
  3. Proceed toward real activation (`--apply`) — Homeowner will supply the
     real OIDC / cert / secret values at the activation moment.

## CONTEXT

The migration dress rehearsal found 5/259 kernel facts package-ready under a
strict "evidence-span-required" policy; 254 needed curation. The Homeowner has
now (a) relaxed that policy for `verified_primary` facts and (b) asked for an
answer-time confidence caveat on softly-grounded answers. This work order turns
the dress rehearsal into a much larger ready set AND builds the honesty feature
that makes the relaxed policy safe.

## CONFIDENCE TIERS (the spine of this work)

| Tier | Definition | Migration | Answer behavior |
|---|---|---|---|
| `strict` | Verified provenance + verbatim evidence span with locator | ready, no caveat | normal grounded answer |
| `soft` | `verified_primary` (or `derived_from_verified`) WITH a source (file/row/raw_text) but no formal span/locator | **ready WITH source note + `needs_double_check` flag** | grounded answer + small caveat line |
| `curate` | Missing source entirely, ambiguous/placeholder/flagged/legacy provenance, or unit-drift | still `needs_curation` (not auto-ready) | n/a until curated |
| `claim` | provenance `claim` | never auto-ready as fact | n/a |

## TASK

### Part A — Curation scaffold + relaxed-ready migration policy (Builder 1)
- Extend `v2/eval/migrate/kernel_adapter.py`: add the tier logic above. A
  `verified_primary`/`derived_from_verified` fact WITH `source.file` +
  (`row`/`raw_text`) becomes **ready as `soft`**, attaching a deterministic
  short **source note** (e.g. `"<file> · row <n> · \"<raw_text truncated>\""`)
  AND a `needs_double_check: true` marker on the emitted record.
- Facts still missing source, or with ambiguous/placeholder/flagged/legacy
  provenance, or unit-drift → remain `needs_curation` with the precise gap
  (do NOT fabricate).
- Re-run the DRY-RUN migration on the real staged kernel
  (`/home/claude/kernel-real/registry`) and report the NEW split
  (strict-ready / soft-ready / still-curate / claim) by file and overall.
  NOTHING activated.
- Produce a `curation-worklist` artifact: the finite remaining `curate` facts,
  grouped by gap, with the one-line action each needs — the concrete list the
  Homeowner/curators finish by hand or in a follow-up.
- Keep the `strict` vs `soft` distinction in the emitted package/record so
  Part B can read it. Deterministic; hermetic tests; DRY-RUN ONLY.

### Part B — Answer-time confidence caveat (Builder 2)
- Backend: when an answer is grounded on any fact/record carrying the
  `needs_double_check`/`soft` marker (propagate it from the SOT record →
  retrieval → answer citation metadata; ADDITIVE field on the answer/citation
  models, no retrieval-logic change), the answer response carries a
  `confidence_caveat: true` (or an enum) flag. Answers grounded only on
  `strict` facts do not. Honest-null unaffected.
- Web (`/ask` + the shared Evidence Rail): when the answer flag is set, render
  a small, unobtrusive-but-legible caveat line beneath the answer — Vietnamese
  default (e.g. "Một số căn cứ chưa có trích dẫn nguyên văn — vui lòng kiểm
  chứng lại.") + English via i18n. It appears ONLY on flagged answers. Must
  meet the existing WCAG contrast (not a faint unreadable grey); reduced-motion
  safe; keyboard/screenreader reachable (aria).
- Tests: backend unit/integration proving the flag is set iff a soft fact is
  cited and unset for strict-only answers and honest-null; web unit proving the
  caveat renders iff flagged; a Playwright assertion for a flagged vs unflagged
  answer. Keep all gates green + hermetic.

### Part C — Real-activation runbook (Contractor)
- Produce `vibecode_v2/TIP-013B_ACTIVATION_RUNBOOK.md`: the exact turnkey
  sequence for the Homeowner to activate the curated batch for real — set the
  real `SOT_SIGNING_SECRET` + production secrets (H6), stage the curated
  packages, dry-run until clean, then `onboard-batch.sh --manifest … --apply
  --approve --report …` under an authenticated curator; plus the precise list
  of values the Homeowner must hand over (OIDC H1, certs H2, secrets H6) with
  where each goes. The agent does NOT run `--apply` (no real credentials); it
  makes activation a single reviewed step.

## ACCEPTANCE CRITERIA
- **AC-1** Relaxed-ready adapter: `verified_primary`-with-source facts emit as
  `soft`-ready with a source note + `needs_double_check`; genuinely broken
  facts stay `needs_curation`; DRY-RUN re-run reports the new split; 0
  activation; deterministic.
- **AC-2** Curation worklist artifact lists every remaining `curate` fact with
  its gap + action.
- **AC-3** Answer flag: `confidence_caveat` set iff a soft fact is cited; unset
  for strict-only and honest-null; proven by test.
- **AC-4** Web caveat renders only on flagged answers, legible (WCAG), i18n
  vi/en, a11y-reachable; proven by unit + Playwright.
- **AC-5** No regression: backend full suite, web, Playwright, probes, gates
  green (Contractor rerun).
- **AC-6** Activation runbook complete; the Homeowner-supplied values are
  enumerated; agent runs no `--apply`.

## CONSTRAINTS
- DRY-RUN ONLY on real data; no activation without real Homeowner credentials.
- Additive backend fields only; NO retrieval/grounding-logic change (a caveat
  flag rides ALONG the existing grounding, it does not alter what is retrieved
  or grounded). No schema migration (soft marker rides in existing record/
  package fields or a bounded additive column ONLY if unavoidable — prefer
  package/record metadata). Tokens frozen; no localStorage; hermetic tests.
  Kernel copies read-only.

## BUILDER HANDOFF
Builders 1→2 sequential on branch `tip-013b`; reports
`_tip013b_builder{1,2}_report.md`; keep gates green; leave tree uncommitted for
Contractor checkpoint. Contractor reruns gates, re-runs the dry-run migration
independently, verifies the caveat renders only when it should, writes the
activation runbook, and reports Phase-B status.
