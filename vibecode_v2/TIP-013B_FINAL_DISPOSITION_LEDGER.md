# TIP-013B — FINAL Disposition Ledger (all 259 kernel facts, DRY-RUN)

**Status:** DRY-RUN ONLY — nothing was activated. No `--apply`, no production-DB
write, no real-data activation, **no write-back to the read-only kernel snapshot**.
This ledger completes the curation per the Homeowner's final decision (02/08/2026):
*"finalize per the recommendation, resolve everything, leave nothing out."*

**The point of this ledger:** prove **nothing is in limbo**. Every one of the 259
kernel facts ends in exactly one terminal disposition — **ready** (strict / soft /
strategic), **held-with-reason** (claim / derived), **irreducible-gap** (with the
exact missing field named), or **excluded** — each with a one-line defensible
reason. Totals reconcile to **259**.

- **Date:** 2026-08-02
- **Inputs (READ-ONLY):** `/home/claude/kernel-real/registry/*.yaml` +
  `/home/claude/kernel-real/_dist/` strategic docs. Never written back.
- **Overlay (auditable decision map):** `v2/eval/migrate/curation_overlay.py`
  (`decide` = the transforms; `final_disposition` = this ledger's classifier).
- **Adapter / CLI:** `v2/eval/migrate/kernel_adapter.py` +
  `run_migration.py --curated`.
- **Reconciliation is code, not prose:** `final_disposition(...)` assigns every
  converted outcome to a terminal bucket; the test
  `test_final_disposition_reconciles_the_real_run_to_259` asserts the totals below.

Reproduce:

```
uv run python v2/eval/migrate/run_migration.py --curated   # 219 ready / 259 facts
```

---

## 1. Headline — 259 facts, 219 ready, 0 in limbo

| Terminal disposition | Count | % of 259 |
|---|---:|---:|
| **ready — strict** (verified + verbatim span + locator, no caveat) | **8** | 3.1% |
| **ready — soft** (verified/approved/promoted + source note + `needs_double_check`) | **205** | 79.2% |
| **ready — strategic** (grounded on a staged strategic doc + caveat) | **6** | 2.3% |
| **READY total** (strict + soft + strategic) | **219** | **84.6%** |
| **held — claim** (cost/price + interim specs; explicit hold, not limbo) | **30** | 11.6% |
| **held — derived** (calculations; computed layer, never a frozen SOT fact) | **6** | 2.3% |
| **irreducible-gap** (held; exact missing field named; never fabricated) | **3** | 1.2% |
| **excluded** (toolkit/process reference, not a SOT fact) | **1** | 0.4% |
| **TOTAL** | **259** | **100%** |

Held/derived/irreducible/excluded = **40** facts, each with a recorded reason
below — none is "unresolved". Ready-with-caveat (soft + strategic) = **211** of the
219 carry `needs_double_check`; the 8 strict carry none.

Milestone kept visible: the prior approved wave produced **131 ready**; this final
completion lifts it to **219** by promoting the 67 capability claims (+ the 20
cascade kernel_refs + the 1 interim-spec duplicate).

---

## 2. Comprehensive disposition table (grouped, reconciles to 259)

Grouped by file × final tier × the decision that produced it. Every row is a real
group from the curated dry-run; counts sum to 259.

| File | Final tier | Disposition | Decision | Count | One-line reason |
|---|---|---|---|---:|---|
| specs | strict | ready | D1b + native | 8 | verified primary + verbatim source span + row locator (no caveat) |
| specs | soft | ready | D3B (interim-dup) | 1 | `SPEC.HERA.MTOW.HC001` duplicates the verified `SPEC.HERA.MTOW` → approved_internal + caveat |
| specs | soft | ready | native-soft | 1 | `SPEC.HERA.SIGNATURE.PAYLOAD_SIMUL`: verified_primary + source, no formal span/locator |
| specs | claim | **held-claim** | D3 (interim spec) | 7 | interim spec (status INT, no `raw_text`) — not primary-sourced; verify then promote |
| specs | curate | **irreducible** | D6 | 1 | `SPEC.HERA.PAYLOAD.BAYS`: missing `verified_value` — 3-vs-4 payload-bay CONFLICT (flagged) |
| capabilities | soft | ready | D1B (cap promote) | 76 | capability claim carrying a real `evidence` reference (or already-verified) → approved_internal + caveat |
| prices | soft | ready | native-soft | 13 | verified sell-side prices (MSRP/discounts), source + no formal span → soft + caveat |
| prices | claim | **held-claim** | D3 (price/cost) | 1 | `FX.RATE.REF`: cost/price sensitive + fast drift; leader-zone; confirm currency before promote |
| prices | curate | **irreducible** | D6 | 2 | `PRICE.VEGA.MSRP.VN` (placeholder, value TBD) · `PRICE.RMUS.LEGACY.HERA` (legacy, retire/supersede) |
| boms | soft | ready | native-soft | 3 | verified BOM lines (airframe/GCS/battery) → soft + caveat |
| boms | claim | **held-claim** | D3 (buy-price) | 22 | restricted buy-price/supplier cost; leader-zone + fast drift; per-item currency confirm before promote |
| l3_facts | soft | ready | D1a + D2 + D2B + native | 110 | l3 promotions (see §3) + double-check caveat |
| l3_facts | strategic | ready | D3 (strategic doc) | 6 | grounded on a staged strategic doctrine doc + double-check caveat |
| l3_facts | excluded | **excluded** | D5 | 1 | `L3R.K.005`: toolkit `rtr-van-phong-nha-nuoc`, a process reference, not a fact |
| derived_costs | soft | ready | native-soft | 1 | `DERIVED.HERA.PREMIUM_VS_IF1200`: verified_primary + source → soft + caveat |
| derived_costs | claim | **held-derived** | D4 | 3 | calculation, not a primary fact — computed layer, never frozen as a SOT fact |
| derived_costs | curate | **held-derived + irreducible** | D4 + D6 | 3 | calculation held as derived AND missing a derivation source (see §4) |
| | | | | **259** | |

Totals by disposition: ready 219 (8 + 1 + 1 + 76 + 13 + 3 + 110 + 6 + 1) · held-claim
30 (7 + 1 + 22) · held-derived 6 (3 + 3) · irreducible 3 (1 + 2) · excluded 1.

---

## 3. `l3_facts` soft (110) — decision attribution

The 117 `l3_facts` (85 facts + 32 kernel_refs) carry every l3 decision. The 110
soft split, verified against the overlay:

| Decision | Count | What | Grounding |
|---|---:|---|---|
| D2 — claim-with-span promoted | 79 | l3 claims that already carry a real `evidence_span` | the verbatim span (approved_internal + caveat) |
| **D2B — cascade from a promoted capability** | **20** | curate kernel_refs whose `kernel_ref` names a now-promoted cap | inherit soft from the cap (see §5) |
| D1a — verified-primary inherit | 5 | kernel_refs resolving to a `verified_primary` cap | the inherited kernel record |
| native soft (verified/derived) | 6 | 4 `verified_primary` + 2 `derived_from_verified` l3 facts | source note, no formal span |
| **l3 soft total** | **110** | | |

Plus 6 `strategic` (D3) + 1 `excluded` (D5) = 117.

---

## 4. Held-derived (6) — calculations, never frozen as SOT fact (Decision 4)

| Fact id | Tier | Reason / named gap |
|---|---|---|
| `DERIVED.HERA.BASE_BUILD_COST` | claim | calculation (build-cost roll-up) — computed layer |
| `DERIVED.ALMO.MARGIN.HERA_VN` | claim | calculation (margin) — computed layer |
| `DERIVED.ALMO.MARGIN.HERA_US` | claim | calculation (margin) — computed layer |
| `DERIVED.HERA.PREMIUM_VS_VN` | curate | calculation; **irreducible gap — missing `source`** (derivation source pointer) |
| `DERIVED.HERA.BUNDLE_GAP_US` | curate | calculation; **irreducible gap — missing `source` + resolve the $580 bundle-vs-list gap flag** |
| `DERIVED.HERA.BUNDLE_GAP_VN` | curate | calculation; **irreducible gap — missing `source` + resolve the $5,580 VN markup gap flag** |

The 3 curate derived double as irreducible gaps (Decision 6) — held with the exact
missing field named, never fabricated.

---

## 5. The wave-2 promotions, named (audit)

**Decision 1B — 67 capability claims → soft + caveat (RULE).** Every one of the 67
`capabilities` records with kernel provenance `claim` carries a non-empty
`evidence` documentary reference (brochure XPO26 / KB v1.0 sheet / DCMA submission /
patent table). The rule maps `claim → approved_internal` (never a masquerading
verified state) with a source note built from that **real** `evidence` reference +
`needs_double_check`. The 9 already-verified caps stay soft via the native path →
all 76 capabilities are ready.

**Decision 2B — cascade, 20 curate kernel_refs → soft + caveat.** A curate
`l3_facts` kernel_ref (provenance_missing) whose `kernel_ref` names a *now-promoted
capability* inherits soft + caveat, its note citing the cap. Resolved against the
promoted-capability id set the adapter computes from the same registry — a genuine
dependency cascade, not a hand list. All 20 resolve to a promoted cap:

| kernel_ref fact | inherits from cap(s) | · | kernel_ref fact | inherits from cap(s) |
|---|---|---|---|---|
| `L3R.1.005` | HC-001 | · | `L3R.1.036` | SC-015 |
| `L3R.1.006` | HC-001 | · | `L3R.2.014` | HC-001 |
| `L3R.1.007` | HC-017 | · | `L3R.2.028` | HC-001 · HC-002 |
| `L3R.1.009` | HC-017 | · | `L3R.2.029` | SC-020 |
| `L3R.1.010` | HC-002 | · | `L3R.3.031` | OC-020 |
| `L3R.1.013` | HC-013 | · | `L3R.K.001` | HC-001 |
| `L3R.1.015` | HC-012 | · | `L3R.K.002` | HC-001 |
| `L3R.1.016` | HC-014 | · | `L3R.K.003` | HC-019 · HC-017 |
| `L3R.1.017` | HC-015 | · | `L3R.K.007` | HC-001 · HC-002 |
| `L3R.1.018` | HC-016 | · | `L3R.1.021` | HC-001 |

**Decision 3B — 1 interim-spec exception.** `SPEC.HERA.MTOW.HC001` (status INT, no
`raw_text`) duplicates the already-verified, unit-fixed `SPEC.HERA.MTOW` → promoted
to soft + caveat (`approved_internal`), its source note naming the verified spec it
duplicates. The other 7 interim specs are **not** duplicates of a verified spec and
stay `claim` (held, Decision 3). NOTE: the kernel marks this record `CONFLICT với
HERA SPEC TBD · Engineering chốt số chính xác` — the promotion is deliberately
`approved_internal` + `needs_double_check` (not `verified_primary`), so the residual
engineering reconciliation rides visibly with the fact and no verified value is
misrepresented.

---

## 6. Held-claim (30) — explicit hold, NOT limbo (Decision 3)

| Group | Count | Ids | Reason |
|---|---:|---|---|
| boms buy-price / supplier | 22 | `BOM.*` + `SKU.*` (claim) | leader-zone cost; fast drift; promote only after per-item currency confirmation |
| price (FX) | 1 | `FX.RATE.REF` | exchange-rate reference; fast drift; confirm currency before promote |
| interim specs | 7 | `SPEC.HERA.EDGE_AI.TOPS`, `SPEC.HERA.COMM.CHANNELS`, `SPEC.HERA.SIGNATURE.SOLDIER`, `SPEC.HERA.SIGNATURE.WEIGHT_KG`, `SPEC.HERA.SIGNATURE.WEIGHT_LB`, `SPEC.VEGA.SIGNATURE.WEIGHT_KG`, `SPEC.VEGA.SIGNATURE.WEIGHT_LB` | status INT, no `raw_text` — not primary-sourced; verify then promote |

The 13 verified sell-side prices stay **soft** (ready) — the hold is on the
cost/buy side only; no previously-ready fact was downgraded.

---

## 7. Irreducible gaps (3) + the derived-irreducible (3) — named missing field (Decision 6)

Genuinely lacking a resolvable source/provenance. Held; the exact missing field is
named; the adapter fabricates nothing.

| Fact id | Tier | Missing field (named, honest) |
|---|---|---|
| `SPEC.HERA.PAYLOAD.BAYS` | curate | `verified_value` — 3-vs-4 payload-bay CONFLICT; provenance `flagged`; engineering queue |
| `PRICE.VEGA.MSRP.VN` | curate | `value` — placeholder; VEGA-VN price still `verify_pending` |
| `PRICE.RMUS.LEGACY.HERA` | curate | `supersession` — legacy HERA 1.0 listing; retire or supersede |
| `DERIVED.HERA.PREMIUM_VS_VN` | curate | `source` — derivation source pointer (also held-derived, §4) |
| `DERIVED.HERA.BUNDLE_GAP_US` | curate | `source` + resolve the $580 bundle-vs-list gap flag (also held-derived, §4) |
| `DERIVED.HERA.BUNDLE_GAP_VN` | curate | `source` + resolve the $5,580 VN markup gap flag (also held-derived, §4) |

(The 6 `curate` facts total: 3 counted under **irreducible-gap**, 3 under
**held-derived** — the derived calculations that also lack a source. Both are
terminal dispositions with a named reason.)

---

## 8. Excluded (1) — Decision 5

`L3R.K.005` — its `kernel_ref` is the toolkit `rtr-van-phong-nha-nuoc` (a process
reference, not a fact). Emitted in no tier and no package; reported for audit.

---

## 9. Reconciliation proof

```
ready-strict        8
ready-soft        205
ready-strategic     6
--- READY        219
claim-held         30
derived-held        6
irreducible-gap     3
excluded            1
================  259   ✓ (asserted by test_final_disposition_reconciles_the_real_run_to_259)
```

Nothing is in limbo: 219 ready + 30 claim-held + 6 derived-held + 3 irreducible + 1
excluded = **259**. DRY-RUN only — no activation, no kernel write-back.
