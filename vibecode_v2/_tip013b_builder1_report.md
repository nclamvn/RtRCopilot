# TIP-013B Part A · Builder-1 Report — curation scaffold + relaxed-ready policy

## STATUS
DONE — **DRY-RUN ONLY**. Added the confidence-tier logic (`strict`/`soft`/
`curate`/`claim`) to the real kernel→V2 adapter, re-ran the migration on the
read-only real kernel under the Homeowner's relaxed ready-policy, and produced the
curation worklist. **Nothing was activated** — no `--apply`, no prod-DB write, no
write-back to `/home/claude/kernel-real/`. All gates green; additive only (adapter
+ CLI + tests + two new docs). Ready jumped **5 → 38** (5 strict + 33 soft); the
finite remainder is **41 curate** + **180 claim**.

## FILES CHANGED (additive; no product/gate/onboarding code touched)
- `v2/eval/migrate/kernel_adapter.py` — confidence-tier logic; `derived_from_verified`
  → `verified_secondary`; deterministic `build_source_note`; soft records carry the
  marker in `record.value["confidence_signal"]`; optional evidence in `write_package`;
  tier-aware `summarize`.
- `v2/eval/migrate/run_migration.py` — `final_tier_totals` + tier printout (still no
  `--apply`; cannot activate anything).
- `v2/apps/backend/tests/test_tip013_migrate_unit.py` — 11 → **19** hermetic tests
  (soft note+flag, curate-not-fabricated, strict unchanged, claim-never-ready,
  source-note determinism/truncation, derived_from_verified, classification intact).
- `vibecode_v2/TIP-013B_MIGRATION_READINESS_RELAXED.md` — new relaxed re-run report.
- `vibecode_v2/TIP-013B_CURATION_WORKLIST.md` — the finite 41-fact worklist.
- `vibecode_v2/TIP-013_PHASE_B_MIGRATION_READINESS.md` — 7-line pointer banner only;
  strict baseline (5/254) preserved unchanged for the record.

## RESULTS

**New split (relaxed re-run, 259 real facts):**

| Tier | Count | Meaning |
|---|---:|---|
| `strict`-ready | 5 | verbatim span + locator (unchanged) |
| `soft`-ready | 33 | verified/derived + source, no formal span → ready + double-check |
| **Ready total** | **38** | strict + soft (was 5 under strict policy) |
| `curate` | 41 | still `needs_curation`, precise gap, nothing fabricated |
| `claim` | 180 | never auto-ready; curator promotion decision |

**By file (confidence tier):**

| File | Facts | strict | soft | curate | claim |
|---|---:|---:|---:|---:|---:|
| specs | 18 | 5 | 1 | 4 | 8 |
| capabilities | 76 | 0 | 9 | 0 | 67 |
| prices | 16 | 0 | 13 | 2 | 1 |
| boms | 25 | 0 | 3 | 0 | 22 |
| l3_facts | 117 | 0 | 6 | 32 | 79 |
| derived_costs | 7 | 0 | 1 | 3 | 3 |
| **Total** | **259** | **5** | **33** | **41** | **180** |

**Per-package gate (DRY-RUN, real validators):** all 6 packages `valid=True,
findings=0`. `rtr.specs` records=6 (5 strict w/ evidence + 1 soft) evidence=5;
`rtr.capabilities` 9; `rtr.prices` 13; `rtr.boms` 3 (**restricted**, first leader
package, evidence=0); `rtr.l3_facts` 6; `rtr.derived_costs` 1. Total ready records
= 38. Output is byte-for-byte deterministic across two independent runs.

**0 activation confirmed:** tool plan = `phase=validate, state=planned_valid` for
every item; `apply=false`, `activated_count=0`; CLI prints "NOTHING WAS ACTIVATED".

**The ~38 verified/derived facts that flipped to soft-ready (33 soft):**
- prices (13): `PRICE.HERA.MSRP.US/.VN`, `PRICE.VEGA.MSRP.US`, `PRICE.HERA.BUNDLE.MSRP/.DIST`,
  `PRICE.VEGA.BUNDLE.MSRP/.DIST`, `DISCOUNT.TIER.STANDARD/PREFERRED/STRATEGIC/MIN`,
  `REG.HOLD_TIME`, `REG.SLA.APPROVAL`.
- capabilities (9): `HC-003/004/011/030/042/043/056`, `OC-001`, `SC-002`.
- l3_facts (6): `L3F.ENT.001`, `L3F.PRD.001` (derived_from_verified), `L3F.RES.001–004`.
- boms (3, restricted): `BOM.HERA.AIRFRAME/GCS/BATTERY`.
- derived_costs (1): `DERIVED.HERA.PREMIUM_VS_IF1200`. specs (1): `SPEC.HERA.SIGNATURE.PAYLOAD_SIMUL`.

**Remaining curate (41), top gap groups:** `provenance_missing` 32 (all
`l3_facts.kernel_refs` — resolve against each `kernel_ref`), `unit_drift` 3
(lb/kg specs), `provenance_unmappable` 3 (flagged/placeholder/legacy),
`missing_source` 3 (derived facts). Full per-fact list in the worklist.

**Gate counts (before → after):**
- ruff: pass → **pass** (backend + eval/migrate).
- mypy: 99 src files → **99** (+ adapter/CLI 2 files, strict-clean).
- pytest unit: **315 passed** / 108 skipped → **323 passed** / 108 skipped (+8 tests).

## ISSUES
- Naive `Path(...).name` mangled non-path source refs with an embedded date
  (`"chat team RtR 14/06"` → `"06"`; `"Lâm confirm 27/07/2026 · DISP.001"`). Fixed
  with an extension-aware `_display_source_name` (basename only for real file
  paths, whole string otherwise) — covered by a test.
- The kernel is still not built for the V2 grounded contract: 180/259 (69%) are
  `claim`-tier and cannot auto-promote to verified. The relaxed policy raises
  *ready* from 2% → 15%, but a verified/grounded SOT is bounded by the 40
  verified_primary + 2 derived facts (minus 4 blocked by drift/no-source).

## DEVIATIONS (every mapping assumption; how soft is attached honestly)
1. **Soft eligibility** = verified/approved provenance + a value + a source pointer
   (`source.file` or l3 `source_path`), minus a formal span/locator. This is the
   5 → 38 driver. Facts missing value/source, or with unit-drift or
   flagged/placeholder/legacy provenance, stay `curate` (nothing fabricated).
   *(Read of the work-order "with a source (file/row/raw_text)" as source-presence,
   not a narrow file+row-only filter — this includes cell-referenced prices and
   evidence_span-only l3 facts, matching the Homeowner's "accept verified_primary
   without a formal span" directive and the "~40 flip" estimate.)*
2. **`derived_from_verified` → `verified_secondary`** (2 l3 facts) — withheld as
   unmappable in the strict rehearsal (readiness deviation #4); the tier table lists
   it under soft. **Confirm.**
3. **Soft marker attached honestly, no fabricated span.** It rides in
   `record.value["confidence_signal"] = {tier:"soft", needs_double_check:true,
   source_note:"…"}` — a single namespaced key in the existing `Any` value field
   (no schema/gate change). It flows verbatim into `ActiveRecord.value` at ingest
   (`service.py` `value_payload`), so Part B reads it with no product change. The
   `source_note` is a deterministic human string built ONLY from real kernel
   metadata (file basename/whole ref · row or sheet!cell · the real `raw_text`/
   `evidence_span` truncated ~120 chars). Where the kernel has no quote, none is
   invented. Soft records carry **no** `evidence.jsonl` entry (evidence is an
   optional package member).
4. **Soft `confidence` = 0.7** vs strict 0.9 (the marker, not this number, is the
   signal). **`claim` never auto-ready** even when fully grounded (routed to the
   claim bucket, keeping `claim_masquerades_as_approved` meaningful). Strict tier,
   classification (leader `boms` = restricted vs staff = internal), synthetic
   principals/timestamps, and placeholder source-blob fingerprints are **unchanged**
   from the strict rehearsal; the real `--apply` must re-run against the real source
   tree for true blob hashes.

## SUGGESTIONS
- **What Part B reads for the caveat flag:** on a cited SOT record, check
  `record.value.get("confidence_signal")`; when present with
  `needs_double_check == true` (tier `soft`), set the answer's `confidence_caveat`
  and render the vi/en caveat line. Strict/claim records have no such key →
  no caveat. The `source_note` string is ready-made supplementary provenance text
  if the Evidence Rail wants to show *why* the caveat fired.
- **Curation worklist headline for the Homeowner:** 41 facts, four moves — (1) 32
  `l3_facts.kernel_refs` resolve against a named kernel record (biggest, most
  mechanical); (2) fix the 3 lb/kg unit-drift specs (they flip straight to strict);
  (3) resolve 3 flags; (4) add 3 derivation sources. Separately, 180 honest
  `claim` facts await a promotion decision (not a gap fix). Clearing the 41 is the
  finite path to a clean curated batch for the eventual reviewed `--apply`.
- **One-line policy widening to consider:** soft currently requires a source
  pointer *and* a value; if the Homeowner wants the 32 `kernel_refs` in the ready
  set sooner, resolving their `kernel_ref` provenance is the single unlock (they
  already carry L3 wording).
