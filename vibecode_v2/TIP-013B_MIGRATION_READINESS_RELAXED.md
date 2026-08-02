# TIP-013B Phase B — Relaxed-Policy Migration Readiness (DRY-RUN re-run, 02/08/2026)

> **Superseded for the ready count by the curated re-run.** After the Homeowner
> approved the 4 curation decisions (02/08/2026), `run_migration.py --curated`
> takes ready **38 → 131** (8 strict + 117 soft + 6 strategic), curate 41 → 26,
> claim 180 → 101, 1 excluded — all 6 packages still pass the gate. See
> `TIP-013B_MIGRATION_READINESS_CURATED.md`. The **38-ready** number below is the
> pre-decision relaxed baseline, kept for the record.

**Status:** DRY-RUN ONLY — nothing was activated. No `--apply`, no production DB
write, no real-data activation, no write-back to the read-only kernel snapshot.
This is the re-run of the dress rehearsal under the Homeowner's **relaxed
ready-policy** (02/08/2026): `verified_primary` / `derived_from_verified` facts
are now accepted **without a formal evidence span**, provided they carry an honest
source note and a `needs_double_check` marker so answers built on them can surface
a small caveat (Part B). The strict baseline is preserved for the record in
`TIP-013_PHASE_B_MIGRATION_READINESS.md` (5 ready / 254 curation) — see §1.

- **Date:** 2026-08-02
- **Inputs (READ-ONLY snapshot):** `/home/claude/kernel-real/registry/` — `specs.yaml`,
  `capabilities.yaml`, `prices.yaml`, `boms.yaml`, `l3_facts.yaml`, `derived_costs.yaml`,
  `leader_allowlist.yaml`, `source_hashes.yaml` (never written back).
- **Adapter:** `v2/eval/migrate/kernel_adapter.py` (+ CLI `v2/eval/migrate/run_migration.py`).
- **Gate exercised:** the SAME pure, no-DB validators the onboarding tool uses in
  dry-run — `rtr_copilot.sot.package.PackageParser` + `validate_package`, driven
  through `commands.onboard_batch.OnboardBatch.validate_all`. No DB/Redis/S3 touched.

---

## 1. Confidence tiers (the relaxed spine)

Every one of the 259 facts is assigned exactly one `confidence_tier`:

| Tier | Definition | Migration outcome | Emitted? |
|---|---|---|---|
| `strict` | verified/approved provenance **+ verbatim span + usable locator** | ready, no caveat | yes, with a real evidence entry |
| `soft` | `verified_primary`/`verified_secondary`/`approved_internal`/`derived_from_verified` with a **value + source**, but no formal span/locator | **ready** + `source_note` + `needs_double_check` | yes, **no** fabricated evidence |
| `curate` | missing source, missing value, ambiguous/placeholder/flagged/legacy provenance, or unit-drift | stays `needs_curation` (precise gap) | no |
| `claim` | kernel `claim` provenance | **never auto-ready as a fact** (curator promotion) | no |

---

## 2. Headline result (relaxed re-run)

| Bucket | Count | % of 259 | vs strict baseline |
|---|---:|---:|---|
| **strict**-ready | **5** | 1.9% | = 5 (unchanged) |
| **soft**-ready (new) | **33** | 12.7% | +33 (was 0) |
| **Ready total (strict + soft)** | **38** | 14.7% | **was 5** |
| **curate** (still `needs_curation`) | **41** | 15.8% | was 254 (before claim split) |
| **claim** (never auto-ready) | **180** | 69.5% | separated out |
| **rejected** (gate rejects a complete package) | **0** | 0.0% | = 0 |
| **Total** | **259** | 100% | |

- **Ready jumped from 5 → 38** (5 strict + 33 soft) — the ~38 verified/derived
  facts that carry a real value and a source pointer are now package-ready.
- **0 activation.** The tool's plan is `phase=validate, state=planned_valid` for
  every package; `apply=false`, `activated_count=0`.
- **All 6 emitted packages PASS the real gate** (findings=0). The soft-only
  packages carry no `evidence.jsonl` member at all (evidence is optional) — the
  "soft" tier is exactly "no formal span/locator", not a fabricated one.

---

## 3. Split by file (confidence tier)

| File | Facts | strict | soft | curate | claim |
|---|---:|---:|---:|---:|---:|
| `specs.yaml` | 18 | 5 | 1 | 4 | 8 |
| `capabilities.yaml` | 76 | 0 | 9 | 0 | 67 |
| `prices.yaml` | 16 | 0 | 13 | 2 | 1 |
| `boms.yaml` | 25 | 0 | 3 | 0 | 22 |
| `l3_facts.yaml` | 117 | 0 | 6 | 32 | 79 |
| `derived_costs.yaml` | 7 | 0 | 1 | 3 | 3 |
| **Total** | **259** | **5** | **33** | **41** | **180** |

`entities.yaml` is an entity registry (not publishable facts) and remains out of
scope; it does not count toward the 259.

---

## 4. Per-package gate result (DRY-RUN — nothing activated)

One package is emitted per source key that has ready records. Each is driven
through the real `PackageParser` + `validate_package`:

| Package (source_key) | records | evidence | classification | valid | findings |
|---|---:|---:|---|:--:|---:|
| `rtr.specs` | 6 | 5 | internal | ✅ | 0 |
| `rtr.capabilities` | 9 | 0 | internal | ✅ | 0 |
| `rtr.prices` | 13 | 0 | internal | ✅ | 0 |
| `rtr.boms` | 3 | 0 | **restricted** (leader) | ✅ | 0 |
| `rtr.l3_facts` | 6 | 0 | internal | ✅ | 0 |
| `rtr.derived_costs` | 1 | 0 | internal | ✅ | 0 |
| **Total ready records** | **38** | **5** | | ✅ | **0** |

- `rtr.specs` mixes 5 strict (with a real span) + 1 soft (no span) in one package.
- `rtr.boms` is the first **restricted** (leader-only) package emitted — the 3
  verified buy-price BOM lines are now soft-ready; the classification (leader vs
  staff) reading is unchanged from the strict rehearsal.
- Output is byte-for-byte deterministic: two independent runs produced identical
  package bytes and an identical readiness JSON (apart from the output path).

---

## 5. The 33 soft-ready facts (verified/derived facts that flipped to ready)

These carry `needs_double_check: true` + a deterministic `source_note`. Part B
reads the marker from `record.value["confidence_signal"]` (see §7).

- **prices (13):** `PRICE.HERA.MSRP.US`, `PRICE.HERA.MSRP.VN`, `PRICE.VEGA.MSRP.US`,
  `PRICE.HERA.BUNDLE.MSRP`, `PRICE.VEGA.BUNDLE.MSRP`, `PRICE.HERA.BUNDLE.DIST`,
  `PRICE.VEGA.BUNDLE.DIST`, `DISCOUNT.TIER.STANDARD`, `DISCOUNT.TIER.PREFERRED`,
  `DISCOUNT.TIER.STRATEGIC`, `DISCOUNT.TIER.MIN`, `REG.HOLD_TIME`, `REG.SLA.APPROVAL`.
- **capabilities (9):** `HC-003`, `HC-004`, `HC-011`, `HC-030`, `HC-042`, `HC-043`,
  `HC-056`, `OC-001`, `SC-002`.
- **l3_facts (6):** `L3F.ENT.001`, `L3F.PRD.001` (`derived_from_verified` →
  `verified_secondary`), `L3F.RES.001`, `L3F.RES.002`, `L3F.RES.003`, `L3F.RES.004`.
- **boms (3, restricted):** `BOM.HERA.AIRFRAME`, `BOM.HERA.GCS`, `BOM.HERA.BATTERY`.
- **derived_costs (1):** `DERIVED.HERA.PREMIUM_VS_IF1200`.
- **specs (1):** `SPEC.HERA.SIGNATURE.PAYLOAD_SIMUL`.

Example source notes (built ONLY from real kernel metadata; a quote is included
only when the kernel actually carries one):

```
BOM.HERA.AIRFRAME  →  RtR_Hardware_AI_Cost_Source_of_Truth.xlsx · row 5
PRICE.HERA.MSRP.US →  RtR_Pricing_Master_v1_0.xlsx · sheet 01_MSRP_Final!C6
L3F.RES.001        →  Lâm confirm 27/07/2026 · DISP.001 · "tên chính thức là HeraSight LR …"
```

The 5 **strict** facts are unchanged from the baseline: `SPEC.HERA.PAYLOAD.MAX`,
`SPEC.HERA.MOTORS`, `SPEC.HERA.FLIGHT.NO_PAYLOAD`, `SPEC.HERA.FLIGHT.1KG`,
`SPEC.HERA.FLIGHT.14KG`.

---

## 6. What still needs curation (41) + the claim bucket (180)

The remaining **41 `curate` facts** are a finite, grouped worklist —
`TIP-013B_CURATION_WORKLIST.md`:

| Gap | Count | One-line fix |
|---|---:|---|
| `provenance_missing` | 32 | attach `provenance_level` to the `l3_facts.kernel_refs` (resolve each against its `kernel_ref` source) |
| `unit_drift` | 3 | reconcile the `unit` with the source quote (the lb/kg atomizer bug) |
| `provenance_unmappable` | 3 | resolve the `flagged`/`placeholder`/`legacy` flag |
| `missing_source` | 3 | add a `source` block to the derived facts |

The **180 `claim` facts are NOT in that worklist** — they are honest claims that
need a **curator promotion decision** (claim → verified), a different action than
fixing a gap. They would import as *claim* records, never verified facts; the
gate's `claim_masquerades_as_approved` guard forbids auto-promotion. Their
distribution: capabilities 67, l3_facts 79, boms 22, specs 8, derived_costs 3,
prices 1.

---

## 7. Mapping assumptions specific to the relaxed policy (Homeowner: confirm)

These are ADDITIVE to the strict-rehearsal assumptions (still listed in the
baseline readiness §6); they are the new decisions the relaxed policy introduces.

1. **Soft eligibility = verified/approved provenance + a value + a source pointer,
   minus a formal span/locator.** A verified fact that has `source.file` (or an
   l3 `source_path`) and a value, but lacks a resolvable verbatim span, is now
   `soft`-ready rather than `needs_curation`. This is the single driver of the
   5 → 38 jump. Facts still missing a value/source, or with unit-drift or
   flagged/placeholder/legacy provenance, remain `curate` (nothing fabricated).
2. **`derived_from_verified` → `verified_secondary`.** Withheld as unmappable in
   the strict rehearsal (deviation #4); under the relaxed policy it maps to
   `verified_secondary` and rides as a soft record (2 l3 facts). **Confirm.**
3. **The soft marker rides in `record.value["confidence_signal"]`** — a single
   namespaced key inside the existing `Any` value field. No schema/gate/onboarding
   change. It flows verbatim into `ActiveRecord.value` at ingest, so Part B reads
   `needs_double_check` + `source_note` from the answer's citation metadata with no
   product change. Strict records do NOT carry this key (strict is unchanged).
4. **No evidence is fabricated for soft records.** "Soft" means precisely "no
   formal span/locator"; a soft package therefore carries no `evidence.jsonl`
   member. Where the kernel *does* hold a verbatim quote it is preserved honestly
   inside the human-readable `source_note` (truncated ~120 chars), never invented
   as a machine evidence span.
5. **Soft `confidence` = 0.7** (vs strict 0.9) to encode "verified provenance but
   no formal span". The load-bearing signal is the `needs_double_check` marker,
   not this number.
6. **`claim` never auto-ready — even when fully grounded.** A claim that happens
   to carry a span + locator is still routed to the `claim` bucket, not `strict`.
   Promotion is a curator decision, keeping the `claim_masquerades_as_approved`
   guard meaningful.
7. **Source-blob fingerprints are still placeholders** (the real `.xlsx`/`.docx`
   tree is not in the snapshot). At real `--apply` the adapter MUST be re-run
   against the real source tree so fingerprints attest to real bytes (unchanged
   from the strict rehearsal).

---

## 8. Reproduce this re-run (DRY-RUN; there is no `--apply`)

```bash
cd v2/apps/backend
uv run python ../../eval/migrate/run_migration.py \
    --kernel-root /home/claude/kernel-real/registry \
    --out /tmp/rtr-migration-dryrun/staging \
    --report-json /tmp/rtr-migration-dryrun/readiness.json
# -> total facts: 259 | final status: {'needs_curation': 221, 'ready': 38}
# -> final tiers : {'strict': 5, 'soft': 33, 'curate': 41, 'claim': 180}
# -> dry-run per-package gate: all 6 packages valid=True findings=0
# -> NOTHING WAS ACTIVATED. No --apply, no DB writes.
```

Emitted package ids are deterministic (uuid5); `rtr.specs` keeps the same id as
the strict rehearsal (`package-45f576f2-…`). Every safeguard from the strict
readiness §7 (two-phase fail-closed, curator-signed attestation,
`claim_masquerades_as_approved` proven live by a negative test, idempotency,
audit, adapter-side pre-gate) is unchanged and un-weakened.
