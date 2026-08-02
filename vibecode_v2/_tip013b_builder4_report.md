# TIP-013B Builder-4 Report — apply the Homeowner's 4 approved curation decisions (DRY-RUN)

## STATUS
DONE — **DRY-RUN ONLY**. Implemented the Homeowner's 4 approved curation decisions
(02/08/2026) as an explicit, auditable **overlay** the migration adapter reads at
convert time, re-ran the dry-run on the read-only real kernel, and confirmed every
emitted package still passes the real publish gate. **Nothing was activated** — no
`--apply`, no prod-DB write, no write-back to `/home/claude/kernel-real/`. The
kernel snapshot is provably unmodified (a test asserts the input registry is
byte-equal before/after). All gates green; additive only. Ready **38 → 131**.

## FILES CHANGED (additive; no product/gate/onboarding code touched)
- **NEW** `v2/eval/migrate/curation_overlay.py` — the auditable decision map:
  `PROMOTE_VERIFIED_PRIMARY` (5 ids), `UNIT_FIX` (3 ids, `lb→kg`), `STRATEGIC_DOC`
  (6 ids), `EXCLUDE` (1 id), plus decision-2 as a RULE (`_promotable_l3_claim`:
  l3 fact + kernel `claim` + non-empty `evidence_span`). `CurationOverlay.decide`
  is pure/deterministic; `OverlayDecision.apply_to_fact` returns a COPY (never
  mutates the kernel-loaded dict).
- **M** `v2/eval/migrate/kernel_adapter.py` — `convert_fact`/`convert_registry`
  take an optional `overlay` (default `None` → baseline behavior identical). Added
  `strategic`/`excluded` tiers, `CONFIDENCE_STRATEGIC=0.6`, `_excluded_outcome`,
  generalized `_signal_value_payload` (tier-aware + `curation` audit sub-key),
  strategic source-note grounding, and strategic/excluded id lists in `summarize`.
- **M** `v2/eval/migrate/run_migration.py` — `--curated` flag applies the overlay;
  `strategic`/`excluded` added to tier order; ready = strict+soft+strategic in the
  printout. Still no `--apply`; cannot activate anything.
- **M** `v2/apps/backend/tests/test_tip013_migrate_unit.py` — 19 → **30** hermetic
  tests (the 11 new all cover the overlay).
- **NEW** `vibecode_v2/TIP-013B_MIGRATION_READINESS_CURATED.md` — post-decision
  readiness report (keeps the prior 38-ready number visible).
- **M** `vibecode_v2/TIP-013B_MIGRATION_READINESS_RELAXED.md` — 7-line pointer
  banner to the curated re-run; the 38-ready baseline preserved for the record.

## RESULTS

**Final split (curated re-run, 259 real facts; baseline in parentheses):**

| Tier | Count | vs 38-ready baseline |
|---|---:|---|
| `strict`-ready | **8** | 5 → 8 (+3 unit-fix) |
| `soft`-ready + caveat | **117** | 33 → 117 (+5 kernel_ref inherit, +79 claim-with-span) |
| `strategic`-ready + caveat | **6** | 0 → 6 (new tier) |
| **READY total** | **131** | **38 → 131** |
| `curate` | 26 | 41 → 26 |
| `claim` (kept as claim + caveat) | 101 | 180 → 101 |
| `excluded` | 1 | 0 → 1 (`L3R.K.005`) |

**By file (curated):**

| File | Facts | strict | soft | strategic | curate | claim | excluded |
|---|---:|---:|---:|---:|---:|---:|---:|
| specs | 18 | 8 | 1 | — | 1 | 8 | — |
| capabilities | 76 | — | 9 | — | — | 67 | — |
| prices | 16 | — | 13 | — | 2 | 1 | — |
| boms | 25 | — | 3 | — | — | 22 | — |
| l3_facts | 117 | — | 90 | 6 | 20 | — | 1 |
| derived_costs | 7 | — | 1 | — | 3 | 3 | — |
| **Total** | **259** | **8** | **117** | **6** | **26** | **101** | **1** |

**FINAL READY COUNT: 131** (8 strict + 117 soft + 6 strategic; 123 of the 131
carry `needs_double_check`, the 8 strict carry none).

**Per-package publish-gate (DRY-RUN, real validators) — all 6 PASS, 0 findings:**

| Package | records | evidence | valid | findings | checksum(12) |
|---|---:|---:|:--:|---:|---|
| rtr.specs | 9 | 8 | ✅ | 0 | `a517b7ba8100` |
| rtr.capabilities | 9 | 0 | ✅ | 0 | `c8c6b6a0683a` |
| rtr.prices | 13 | 0 | ✅ | 0 | `f3cc905b8186` |
| rtr.boms (restricted) | 3 | 0 | ✅ | 0 | `154ec5c7f248` |
| rtr.l3_facts | 96 | 0 | ✅ | 0 | `fc92fd181fa1` |
| rtr.derived_costs | 1 | 0 | ✅ | 0 | `fccafd57c4c6` |

`rtr.specs` evidence=8 = 5 original strict + 3 unit-fixed strict (each a real
`raw_text` span + row locator). Soft/strategic records carry no evidence entry
(optional member); grounding rides in `value.confidence_signal.source_note`.
Checksums are byte-identical across two independent runs (deterministic).

**Named-fact audit (all landed correctly):**
- 1a → soft: `L3R.2.005/013/027`, `L3R.3.030`, `L3R.K.006` — provenance
  `verified_primary`, note cites the inherited kernel record (e.g. `inherits: HC-042`).
- 1b → strict, no caveat: `SPEC.HERA.WEIGHT.EMPTY` (9 kg), `.WEIGHT.TAKEOFF`
  (16 kg), `.MTOW` (31 kg); value unchanged, only the drifted `unit` corrected.
- 2 → soft + caveat: the 79 l3 claims with `evidence_span`; emitted
  `approved_internal`, source note carries the REAL span, audit records
  `origin_provenance = claim`.
- 3 → strategic + caveat: `L3R.2.023/024/025/026/032`, `L3R.K.004`; note cites the
  staged strategic doc (SPEC_CHANGELOG / CEO_STRATEGIC_STANCE / POSITIONING_5CHAN /
  DOCTRINE_1PAGE).
- 4 → excluded: `L3R.K.005` (emitted in no tier/package).

**0 activation confirmed:** every tool-plan item `phase=validate,
state=planned_valid`; no DB/Redis/S3 socket; CLI prints `NOTHING WAS ACTIVATED`.

**Facts that could NOT be promoted:** none among the decision-covered set — all
passed the gate; nothing was force-fit or held back.

**Gate counts (before → after):**
- ruff: pass → **pass** (backend + eval/migrate).
- mypy: 99 src files → **99**; eval/migrate 3→**4** files, strict-clean.
- pytest unit: **324 passed** / 109 skipped → **335 passed** / 109 skipped (+11).
  Migrate unit file `tests/test_tip013_migrate_unit.py`: 19 → **30**.

## ISSUES
- None open. (One self-inflicted test bug — a doubled package path in the
  determinism test — was found and fixed; the adapter output itself was correct.)

## DEVIATIONS (every mapping choice, made honestly)
1. **The 5 verified_primary kernel_refs land in `soft`, not `strict`.** A
   `kernel_ref` carries no `evidence_span` and no structured locator, so the
   existing strict rule (verbatim span + locator) cannot fire; they are emitted
   soft-ready with `needs_double_check` and a note citing the inherited record.
   Decision 1's "→ these become strict" clause attaches to the 3 unit-drift facts
   (which DO have a span + row locator); the 5 are "promote to ready", satisfied
   at the soft tier. **Confirm the soft placement is acceptable.**
2. **Decision 2 promotions map kernel `claim → approved_internal`** (an internal
   curator-approval state), not `verified_*`. This keeps the gate's
   `claim_masquerades_as_approved` guard meaningful and is the honest label for a
   curator-approved-with-caveat fact. The origin `claim` is preserved in
   `value.confidence_signal.curation.origin_provenance`.
3. **The new `strategic` tier reuses `approved_internal`** provenance
   (verification_state `approved`) with `confidence=0.6` and a strategic-doc source
   note — the honest V2 slot for "strategic doctrine, not a verified spec". It is
   ready-with-caveat, distinct from soft only by its tier label + note.
4. **Decision-2 selection is a RULE, not a hand list** (l3 fact + `claim` +
   non-empty `evidence_span`). It selects exactly 79 on the real kernel; if a fact
   later gains/loses a span the set self-corrects, which is more auditable than a
   frozen list. The 5/6/1 named-id decisions ARE explicit id sets.
5. **`strategic`/`excluded` add to the tier vocabulary** only under the overlay;
   with `overlay=None` the adapter is byte-identical to the baseline (all prior
   tests unchanged and green).

## SUGGESTIONS (what's left before a real `--apply`)
- **101 claims remain `claim` + caveat marker** (never auto-ready): capabilities
  67, boms 22 (restricted buy-price), specs 8, prices 1, derived 3. These await an
  explicit curator promotion decision, not a gap fix — the single largest lever
  left after this batch.
- **20 kernel_ref facts stay `curate`** (`provenance_missing`): their resolved
  source record is itself a `claim` (resolution-table group B), NOT covered by the
  4 decisions, so correctly untouched. A follow-up decision would clear them.
- **6 curate remainder:** 3 `missing_source` (derived) + 3 `provenance_unmappable`
  (flagged/placeholder/legacy) — genuine gaps the adapter refuses to fabricate.
- **For the eventual real `--apply`** (Contractor / governance): recompute real
  source-blob SHAs from the source tree (the rehearsal leaves
  `evidence.source_blob_sha256` unset by design), bind the manifest curator to an
  authenticated session + re-sign attestations, and gate on H1/H2/H6. None of that
  is done here — this stays a DRY-RUN measurement.
- **Part B already reads the caveat**: `value.confidence_signal.needs_double_check`
  fires for all 123 soft+strategic records; the optional `curation` sub-key gives
  the Evidence Rail a ready-made "why" (which decision + origin provenance).
