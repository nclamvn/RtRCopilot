# TIP-013B Phase B — Curated Migration Readiness (DRY-RUN, FINAL completion 02/08/2026)

**Status:** DRY-RUN ONLY — nothing was activated. No `--apply`, no production DB
write, no real-data activation, no write-back to the read-only kernel snapshot.
This run applies the Homeowner's curation decisions as an explicit, auditable
**overlay** the adapter reads at convert time. The kernel snapshot is **never
modified**: the unit fix, the promotions, the cascade, the strategic tier and the
exclusion are transforms on the *emitted V2 packages* only. Every
promoted/soft/strategic record still references a REAL source (real
`evidence_span`, real `evidence` reference, real source record / kernel_ref, or
real staged strategic doc) and carries the `needs_double_check` marker where the
tier is soft/strategic. **No fabrication.**

> **FINAL COMPLETION (this update):** per the Homeowner's final decision — *"finalize
> per the recommendation, resolve everything, leave nothing out"* — the overlay now
> also (1B) promotes the **67 capability claims** with a real `evidence` reference →
> soft + caveat, (2B) **cascades** the 20 curate kernel_refs that inherit from a
> now-promoted capability → soft + caveat, and (3B) promotes the 1 interim spec that
> **duplicates a verified spec** (`SPEC.HERA.MTOW.HC001`). Ready **131 → 219**. Every
> remaining fact has an explicit final disposition — see
> `TIP-013B_FINAL_DISPOSITION_LEDGER.md` (reconciles all 259, nothing in limbo).

- **Date:** 2026-08-02
- **Milestones kept for the record:** the **131-ready** wave (5+3 strict / 117 soft /
  6 strategic) was the prior approved milestone; the relaxed re-run (pre-decision)
  yielded **38 ready** (5 strict + 33 soft) / 41 curate / 180 claim — see
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
uv run python v2/eval/migrate/run_migration.py --curated  # curated FINAL: 219 ready
```

---

## 1. The decisions, as applied

**Wave 1 (the 131-ready milestone):**

| # | Decision | Overlay transform | Result tier |
|---|---|---|---|
| 1a | Promote the 5 Group-1 `kernel_ref` facts that resolve to `verified_primary` (inherit the source record's verified provenance) | inject `provenance_level = verified_primary`; source note cites the inherited kernel record | **soft** (no formal span/locator on a kernel_ref) + caveat |
| 1b | Fix the 3 HERA unit-drift facts `lb → kg` (evidence = each fact's own `raw_text` + `notes`) | rewrite `unit` only when it is exactly `lb`; drift clears | **strict** (verbatim span + row locator), **no** caveat |
| 2 | Promote the 79 l3-claim facts that already carry an `evidence_span` | RULE (not a hand list): l3 fact, kernel `claim`, non-empty `evidence_span` → inject `approved_internal`; grounded on the real span | **soft** + `needs_double_check` |
| 3 | The 6 strategic-doc `kernel_ref` facts | inject `approved_internal`, relabel tier `strategic`; note cites the staged strategic doc named in `kernel_ref` | **strategic** (ready-with-caveat) |
| 4/5 | Exclude `L3R.K.005` (kernel_ref = toolkit `rtr-van-phong-nha-nuoc`, a process reference) | emitted in no tier / no package | **excluded** |

**Wave 2 (FINAL completion — lifts 131 → 219):**

| # | Decision | Overlay transform | Result tier |
|---|---|---|---|
| 1B | Promote the **67 capability claims** that carry a non-empty `evidence` reference | RULE (not a hand list): file `capabilities`, kernel `claim`, non-empty `evidence` → inject `approved_internal`; source note built from the real `evidence` ref | **soft** + `needs_double_check` |
| 2B | **Cascade:** the 20 curate kernel_refs whose `kernel_ref` names a now-promoted capability | RULE resolved against the promoted-capability id set (computed from the same registry) → inject `approved_internal`; note cites the cap it inherits from | **soft** + `needs_double_check` |
| 3B | Promote the 1 interim spec that **duplicates a verified spec** (`SPEC.HERA.MTOW.HC001` ↔ verified `SPEC.HERA.MTOW`) | inject `approved_internal`; note names the verified spec it duplicates | **soft** + `needs_double_check` |
| 3-hold | HOLD as `claim`: 22 boms buy-price + 1 price (FX) + 7 interim specs | no transform (claim is the default); recorded final disposition + reason | **claim** (held, not limbo) |
| 4-derived | KEEP as `derived`: 3 derived_costs claims + 3 `DERIVED.*` in curate | no transform; recorded final disposition + reason | **derived** (held) |
| 6-gap | Irreducible gaps: the 3 `provenance_unmappable` (+ the 3 derived missing-source) | no transform; held with the exact missing field named | **curate** (irreducible) |

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

## 2. Headline result (curated FINAL) — 259 facts

| Tier | Count | % of 259 | 131-wave → FINAL |
|---|---:|---:|---|
| **strict**-ready | **8** | 3.1% | 8 → 8 |
| **soft**-ready + caveat | **205** | 79.2% | 117 → 205 (+67 caps, +20 cascade, +1 interim-dup) |
| **strategic**-ready + caveat | **6** | 2.3% | 6 → 6 |
| **READY total** (strict+soft+strategic) | **219** | **84.6%** | **131 → 219** |
| `curate` (irreducible + derived-missing-source) | 6 | 2.3% | 26 → 6 (−20 cascade) |
| `claim` (held: cost/price + interim specs + derived) | 33 | 12.7% | 101 → 33 (−67 caps, −1 interim-dup) |
| `excluded` | 1 | 0.4% | 1 → 1 (`L3R.K.005`) |

Ready-with-caveat (soft + strategic) = **211** of the 219 carry
`needs_double_check`; the 8 strict carry none. Every fact has an explicit final
disposition (ready / held-claim / held-derived / irreducible-gap / excluded) —
reconciled to 259 in `TIP-013B_FINAL_DISPOSITION_LEDGER.md`.

---

## 3. Final split by file

| File | Facts | strict | soft | strategic | curate | claim | excluded |
|---|---:|---:|---:|---:|---:|---:|---:|
| specs | 18 | 8 | 2 | — | 1 | 7 | — |
| capabilities | 76 | — | 76 | — | — | — | — |
| prices | 16 | — | 13 | — | 2 | 1 | — |
| boms | 25 | — | 3 | — | — | 22 | — |
| l3_facts | 117 | — | 110 | 6 | — | — | 1 |
| derived_costs | 7 | — | 1 | — | 3 | 3 | — |
| **Total** | **259** | **8** | **205** | **6** | **6** | **33** | **1** |

- `capabilities` (76): all 76 now soft — 67 claim-with-`evidence` promoted (D1B) +
  9 already-verified.
- `l3_facts` (117 = 85 facts + 32 kernel_refs): 79 claim-with-span (D2) + 20 cascade
  (D2B) + 5 inherited kernel_refs (D1a) + 6 native verified/derived softs → 110 soft;
  6 strategic (D3); `L3R.K.005` excluded (D5). Zero l3 curate remain.
- `specs` (18): 8 strict; 2 soft = `SIGNATURE.PAYLOAD_SIMUL` (native) +
  `MTOW.HC001` (D3B interim-dup); 7 interim claims held; 1 curate
  (`PAYLOAD.BAYS`, irreducible CONFLICT).
- `prices`/`boms`/`derived_costs`: the held cost/price + derived facts — see the
  disposition ledger for the per-fact reason.

---

## 4. Per-package publish-gate result (DRY-RUN, real validators)

All 6 emitted packages **PASS** — `valid=True, findings=0`. Checksums are
deterministic (byte-identical across two independent runs).

| Package (source_key) | records | evidence | valid | findings | deterministic_checksum (12) |
|---|---:|---:|:---:|---:|---|
| rtr.specs | 10 | 8 | ✅ | 0 | `e6c2cc922534` |
| rtr.capabilities | 76 | 0 | ✅ | 0 | `39cc87daccdd` |
| rtr.prices | 13 | 0 | ✅ | 0 | `f3cc905b8186` |
| rtr.boms (restricted/leader) | 3 | 0 | ✅ | 0 | `154ec5c7f248` |
| rtr.l3_facts | 116 | 0 | ✅ | 0 | `ccb8a7de25d9` |
| rtr.derived_costs | 1 | 0 | ✅ | 0 | `fccafd57c4c6` |
| **Total ready records** | **219** | **8** | | **0** | |

`rtr.boms`, `rtr.prices`, `rtr.derived_costs` checksums are byte-identical to the
131-wave (their ready set did not change); `rtr.capabilities` (9→76),
`rtr.l3_facts` (96→116) and `rtr.specs` (9→10) grew by the wave-2 promotions.

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
- **Decision 2 → soft + caveat:** the 79 l3 claims with `evidence_span` (rule-selected).
- **Decision 3 → strategic + caveat:** `L3R.2.023`, `L3R.2.024`, `L3R.2.025`,
  `L3R.2.026`, `L3R.2.032`, `L3R.K.004` (grounded on SPEC_CHANGELOG /
  CEO_STRATEGIC_STANCE / POSITIONING_5CHAN / DOCTRINE_1PAGE).
- **Decision 4/5 → excluded:** `L3R.K.005`.
- **Decision 1B → soft + caveat (FINAL):** the 67 capability claims that carry a
  real `evidence` reference (brochure/KB/DCMA/patent); the 9 already-verified caps
  stay soft → all 76 capabilities ready. Source note built from the real `evidence`.
- **Decision 2B → soft + caveat (FINAL, cascade):** the 20 curate kernel_refs whose
  `kernel_ref` names a now-promoted capability (e.g. `L3R.1.005` ⇐ HC-001,
  `L3R.1.013` ⇐ HC-013, `L3R.3.031` ⇐ OC-020). Resolved against the promoted-cap id
  set — see the disposition ledger §5 for the full 20 → cap mapping.
- **Decision 3B → soft + caveat (FINAL):** `SPEC.HERA.MTOW.HC001` duplicates the
  verified `SPEC.HERA.MTOW`; promoted `approved_internal` (not verified_primary — its
  own matrix figure carries an engineering-TBD conflict, so the caveat rides with it).

Nothing decision-covered was held back at the gate: every fact the decisions named
passed the publish gate. All remaining held/derived/irreducible facts carry an
explicit final disposition + reason in `TIP-013B_FINAL_DISPOSITION_LEDGER.md`.

---

## 6. What is left before a real `--apply`

Nothing is in limbo — the 40 non-ready facts each have an explicit final
disposition (`TIP-013B_FINAL_DISPOSITION_LEDGER.md`). What remains is either a
future curator decision or governance, NOT an unresolved fact:

- **33 held `claim`** (explicit hold, reason recorded, never auto-ready): 22 boms
  buy-price + 1 price (FX) — leader-zone cost, fast drift, promote only after
  per-item currency confirmation; 7 interim specs (INT, no `raw_text`) — verify
  then promote; 3 derived (calculations, held as `derived`, never frozen as a SOT
  fact).
- **6 `curate` (irreducible gaps)**, each with the exact missing field named: 3
  `provenance_unmappable` (`SPEC.HERA.PAYLOAD.BAYS` flagged CONFLICT,
  `PRICE.VEGA.MSRP.VN` placeholder, `PRICE.RMUS.LEGACY.HERA` legacy) + 3 derived
  missing a derivation `source`. The adapter refuses to fabricate these.
- **1 `excluded`** (`L3R.K.005`, toolkit/process reference).
- The real `--apply` must (a) recompute source-blob SHAs from the real source tree
  (the rehearsal leaves `evidence.source_blob_sha256` unset by design), (b) bind
  the manifest curator to an authenticated session and re-sign each attestation,
  and (c) run only after H1/H2/H6 governance approvals. **None of that is done
  here — this remains a DRY-RUN measurement.**
