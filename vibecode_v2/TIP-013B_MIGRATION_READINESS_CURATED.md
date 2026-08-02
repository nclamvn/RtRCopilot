# TIP-013B Phase B — Curated Migration Readiness (DRY-RUN re-run, 02/08/2026)

**Status:** DRY-RUN ONLY — nothing was activated. No `--apply`, no production DB
write, no real-data activation, no write-back to the read-only kernel snapshot.
This re-run applies the Homeowner's **4 approved curation decisions**
(02/08/2026) as an explicit, auditable **overlay** the adapter reads at convert
time. The kernel snapshot is **never modified**: the unit fix, the promotions,
the strategic tier and the exclusion are transforms on the *emitted V2 packages*
only. Every promoted/soft/strategic record still references a REAL source (real
`evidence_span`, real source record / kernel_ref, or real staged strategic doc)
and carries the `needs_double_check` marker where the tier is soft/strategic.
**No fabrication.**

- **Date:** 2026-08-02
- **Prior number kept for the record:** the relaxed re-run (pre-decision) yielded
  **38 ready** (5 strict + 33 soft) / 41 curate / 180 claim — see
  `TIP-013B_MIGRATION_READINESS_RELAXED.md`. The strict baseline (5 ready / 254)
  is in `TIP-013_PHASE_B_MIGRATION_READINESS.md`.
- **Inputs (READ-ONLY snapshot):** `/home/claude/kernel-real/registry/*.yaml`
  (never written back) + the 4 staged strategic docs under
  `/home/claude/kernel-real/_dist/` (SPEC_CHANGELOG.md,
  legal/CEO_STRATEGIC_STANCE_2026-07-01.md,
  positioning/POSITIONING_5CHAN_2026-07-03.md, DOCTRINE_1PAGE.md).
- **Overlay:** `v2/eval/migrate/curation_overlay.py` (the auditable decision map).
- **Adapter / CLI:** `v2/eval/migrate/kernel_adapter.py` +
  `run_migration.py --curated`.
- **Gate exercised:** the SAME pure, no-DB validators the onboarding tool uses in
  dry-run — `rtr_copilot.sot.package.PackageParser` + `validate_package`, driven
  through `commands.onboard_batch.OnboardBatch.validate_all`. No DB/Redis/S3 touched.

Reproduce:

```
uv run python v2/eval/migrate/run_migration.py            # baseline: 38 ready
uv run python v2/eval/migrate/run_migration.py --curated  # curated: 131 ready
```

---

## 1. The 4 approved decisions, as applied

| # | Decision | Overlay transform | Result tier |
|---|---|---|---|
| 1a | Promote the 5 Group-1 `kernel_ref` facts that resolve to `verified_primary` (inherit the source record's verified provenance) | inject `provenance_level = verified_primary`; source note cites the inherited kernel record | **soft** (no formal span/locator on a kernel_ref) + caveat |
| 1b | Fix the 3 HERA unit-drift facts `lb → kg` (evidence = each fact's own `raw_text` + `notes`) | rewrite `unit` only when it is exactly `lb`; drift clears | **strict** (verbatim span + row locator), **no** caveat |
| 2 | Promote the 79 l3-claim facts that already carry an `evidence_span` | RULE (not a hand list): l3 fact, kernel `claim`, non-empty `evidence_span` → inject `approved_internal`; grounded on the real span | **soft** + `needs_double_check` |
| 3 | The 6 strategic-doc `kernel_ref` facts | inject `approved_internal`, relabel tier `strategic`; note cites the staged strategic doc named in `kernel_ref` | **strategic** (ready-with-caveat) |
| 4 | Exclude `L3R.K.005` (kernel_ref = toolkit `rtr-van-phong-nha-nuoc`, a process reference) | emitted in no tier / no package | **excluded** |

Honesty guarantees:

- Decision 2 maps kernel `claim → approved_internal` (an internal curator-approval
  state), **never** a verified state without evidence — so the publish gate's
  `claim_masquerades_as_approved` guard stays meaningful. The origin `claim` is
  recorded in the record's `value.confidence_signal.curation`.
- Every soft/strategic record carries `needs_double_check: true` in
  `value.confidence_signal`, which Part B reads to surface the answer-time caveat.
- Every promotion's source note is built ONLY from real kernel metadata: the real
  `evidence_span` text (decision 2), the real `kernel_ref` naming the inherited
  record (1a) or the staged strategic doc (3). Nothing is invented.

---

## 2. Headline result (curated re-run) — 259 facts

| Tier | Count | % of 259 | vs prior relaxed (38-ready) |
|---|---:|---:|---|
| **strict**-ready | **8** | 3.1% | 5 → 8 (+3 unit-fix) |
| **soft**-ready + caveat | **117** | 45.2% | 33 → 117 (+5 kernel_ref inherit, +79 claim-with-span) |
| **strategic**-ready + caveat | **6** | 2.3% | 0 → 6 (new tier) |
| **READY total** (strict+soft+strategic) | **131** | **50.6%** | **38 → 131** |
| `curate` | 26 | 10.0% | 41 → 26 (−3 unit, −5 inherit, −6 strategic, −1 excluded) |
| `claim` (kept as claim + caveat marker) | 101 | 39.0% | 180 → 101 (−79 promoted) |
| `excluded` | 1 | 0.4% | 0 → 1 (`L3R.K.005`) |

Ready-with-caveat (soft + strategic) = **123** of the 131 carry
`needs_double_check`; the 8 strict carry none.

---

## 3. Final split by file

| File | Facts | strict | soft | strategic | curate | claim | excluded |
|---|---:|---:|---:|---:|---:|---:|---:|
| specs | 18 | 8 | 1 | — | 1 | 8 | — |
| capabilities | 76 | — | 9 | — | — | 67 | — |
| prices | 16 | — | 13 | — | 2 | 1 | — |
| boms | 25 | — | 3 | — | — | 22 | — |
| l3_facts | 117 | — | 90 | 6 | 20 | — | 1 |
| derived_costs | 7 | — | 1 | — | 3 | 3 | — |
| **Total** | **259** | **8** | **117** | **6** | **26** | **101** | **1** |

`l3_facts` (117 = 85 facts + 32 kernel_refs) carries every decision: the 79
claim-with-span promotions and the 6 pre-existing verified/derived softs and the
5 inherited kernel_refs → 90 soft; the 6 strategic; the 20 remaining kernel_refs
(their source record is itself a `claim`, NOT covered by the 4 decisions) stay
curate; `L3R.K.005` excluded.

---

## 4. Per-package publish-gate result (DRY-RUN, real validators)

All 6 emitted packages **PASS** — `valid=True, findings=0`. Checksums are
deterministic (byte-identical across two independent runs).

| Package (source_key) | records | evidence | valid | findings | deterministic_checksum (12) |
|---|---:|---:|:---:|---:|---|
| rtr.specs | 9 | 8 | ✅ | 0 | `a517b7ba8100` |
| rtr.capabilities | 9 | 0 | ✅ | 0 | `c8c6b6a0683a` |
| rtr.prices | 13 | 0 | ✅ | 0 | `f3cc905b8186` |
| rtr.boms (restricted/leader) | 3 | 0 | ✅ | 0 | `154ec5c7f248` |
| rtr.l3_facts | 96 | 0 | ✅ | 0 | `fc92fd181fa1` |
| rtr.derived_costs | 1 | 0 | ✅ | 0 | `fccafd57c4c6` |
| **Total ready records** | **131** | **8** | | **0** | |

- `rtr.specs` evidence = 8 = 5 original strict + 3 unit-fixed strict (each with a
  real `raw_text` span + row locator). Soft/strategic records carry **no**
  `evidence.jsonl` entry (evidence is an optional package member); their grounding
  rides in `value.confidence_signal.source_note`.
- The strategic and promoted-claim records are `approved_internal` with no
  evidence entry — a valid record for the gate; none masquerade as verified.

**0 activation confirmed:** every tool-plan item is `phase=validate,
state=planned_valid`; no `--apply`, no DB/Redis/S3 socket. CLI prints
`NOTHING WAS ACTIVATED. No --apply, no DB writes.`

---

## 5. The named facts (audit)

- **Decision 1a → soft (verified_primary inherit):** `L3R.2.005` (HC-056·057·058),
  `L3R.2.013` (HC-042), `L3R.2.027` (OC-001·CEO_STANCE), `L3R.3.030` (OC-001),
  `L3R.K.006` (HC-042 + DISP.005).
- **Decision 1b → strict (unit lb→kg):** `SPEC.HERA.WEIGHT.EMPTY` (9 kg),
  `SPEC.HERA.WEIGHT.TAKEOFF` (16 kg), `SPEC.HERA.MTOW` (31 kg). Values unchanged;
  only the drifted `unit` label corrected, per each fact's own `raw_text`/`notes`.
- **Decision 2 → soft + caveat:** the 79 l3 claims with `evidence_span` (rule-
  selected; the remaining 101 claims across capabilities/boms/specs/prices/derived
  stay `claim`).
- **Decision 3 → strategic + caveat:** `L3R.2.023`, `L3R.2.024`, `L3R.2.025`,
  `L3R.2.026`, `L3R.2.032`, `L3R.K.004` (grounded on SPEC_CHANGELOG /
  CEO_STRATEGIC_STANCE / POSITIONING_5CHAN / DOCTRINE_1PAGE).
- **Decision 4 → excluded:** `L3R.K.005`.

Nothing could NOT be promoted: every fact the 4 decisions named passed the
publish gate; no decision-covered fact was held back in `curate`.

---

## 6. What is left before a real `--apply`

- **20 kernel_ref facts remain `curate`** (`provenance_missing`): their resolved
  source record is itself a `claim` (resolution table group B) — NOT covered by
  the 4 approved decisions, so they were correctly left untouched. A future
  decision would be needed to promote them.
- **101 facts remain `claim`** (kept as claim + caveat marker, never auto-ready):
  capabilities 67, boms 22 (restricted buy-price), specs 8, prices 1, derived 3.
  These await an explicit curator promotion decision, not a gap fix.
- **6 curate remainder:** 3 `missing_source` (derived) + 3 `provenance_unmappable`
  (flagged/placeholder/legacy) — genuine gaps the adapter refuses to fabricate.
- The real `--apply` must (a) recompute source-blob SHAs from the real source tree
  (the rehearsal leaves `evidence.source_blob_sha256` unset by design), (b) bind
  the manifest curator to an authenticated session and re-sign each attestation,
  and (c) run only after H1/H2/H6 governance approvals. **None of that is done
  here — this remains a DRY-RUN measurement.**
