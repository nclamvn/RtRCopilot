# TIP-013 Phase B — Real-Data Migration Readiness (DRY-RUN dress rehearsal)

**Status:** DRY-RUN ONLY — nothing was activated. No `--apply`, no production DB
write, no real-data activation. This report measures how many of the real RtR
kernel facts convert cleanly into the V2 SOT package format and would pass the
existing publish gate, and exactly what curation remains before a real cutover.

- **Date:** 2026-08-02
- **Inputs (READ-ONLY snapshot):** `/home/claude/kernel-real/registry/` — `specs.yaml`,
  `capabilities.yaml`, `prices.yaml`, `boms.yaml`, `l3_facts.yaml`, `derived_costs.yaml`,
  `leader_allowlist.yaml`, `source_hashes.yaml` (a point-in-time copy; never written back).
- **Adapter:** `v2/eval/migrate/kernel_adapter.py` (+ CLI `v2/eval/migrate/run_migration.py`).
- **Gate exercised:** the SAME pure, no-DB validators the onboarding tool uses in
  dry-run — `rtr_copilot.sot.package.PackageParser` + `validate_package`, driven
  through `commands.onboard_batch.OnboardBatch.validate_all`. No DB/Redis/S3 touched.

---

## 1. Headline result

| Bucket | Count | % of 259 |
|---|---:|---:|
| **ready** (converts clean, PASSES the gate) | **5** | 1.9% |
| **needs_curation** (a required field is missing; adapter refuses to fabricate) | **254** | 98.1% |
| **rejected** (converts complete but the gate rejects on policy) | **0** | 0.0% |
| **Total facts** | **259** | 100% |

`rejected` is 0 by design: the adapter's conservative mapping surfaces every
defect as `needs_curation` **before** a package is built, so the gate never has a
complete-but-illegal package to reject. The gate's rejection path is still proven
live by a negative test (see §7).

The 5 ready facts (all `specs.yaml`, all `verified_primary`, all with a verbatim
source quote) were emitted as one real staged package `rtr.specs` and **passed the
real gate**: `records=5, evidence=5, valid=True, findings=0`.

> Read this honestly: **~2% of the real kernel is package-ready today.** That is
> the expected shape of a first rehearsal — the kernel was built for a lookup bot,
> not for the V2 grounded-evidence contract. The 254 are not "bad data"; they are
> good facts missing the *packaging* the V2 gate requires (a verbatim evidence
> span with a structured locator, and an honest verified/claim provenance). The
> worklist in §5 is finite and mostly mechanical.

---

## 2. Totals by file

| File | Facts | ready | needs_curation |
|---|---:|---:|---:|
| `specs.yaml` | 18 | 5 | 13 |
| `capabilities.yaml` | 76 | 0 | 76 |
| `prices.yaml` | 16 | 0 | 16 |
| `boms.yaml` | 25 | 0 | 25 |
| `l3_facts.yaml` | 117 | 0 | 117 |
| `derived_costs.yaml` | 7 | 0 | 7 |
| **Total** | **259** | **5** | **254** |

The 5 ready facts: `SPEC.HERA.PAYLOAD.MAX`, `SPEC.HERA.MOTORS`,
`SPEC.HERA.FLIGHT.NO_PAYLOAD`, `SPEC.HERA.FLIGHT.1KG`, `SPEC.HERA.FLIGHT.14KG`.

> `entities.yaml` (34 provinces + 106 organizations + 2 suggested merges) is an
> **entity registry, not a set of publishable facts**, and is deliberately out of
> scope for this fact→record adapter. It does not count toward the 259.

---

## 3. Classification split (staff vs leader)

From `leader_allowlist.yaml`. The doctrine (file header) is one layer:
**staff see the SELL price + discounts + positioning; ONLY leaders see the BUY
price** (component cost + supplier name). Machine-readably, the only
leader-exclusive tier is the section carrying `scope: leader_only` — `l2_cost`,
sourced from `registry/boms.yaml`.

| Tier | V2 classification | Count | Which facts |
|---|---|---:|---|
| **leader** | `restricted` | **25** | all `boms.yaml` (buy price + supplier) |
| **staff** | `internal` | **234** | specs, capabilities, sell-prices, positioning, all L3, derived |

21 of the 25 BOM facts are also on the allowlist `deny` list (kept out of the
staff pack) — consistent with "leader-only". None of the 25 are ready yet
(they lack an evidence span, §5), so **no restricted package was emitted** in this
rehearsal; the classification is recorded per-fact for when they are curated.

---

## 4. Provenance coverage (kernel `provenance_level`, all 259)

| kernel provenance_level | Count | V2 mapping used | Effect |
|---|---:|---|---|
| `verified_primary` | 40 | → `verified_primary` / verified | eligible (needs an evidence span too) |
| `claim` | 180 | → `claim` / claim | eligible as a **claim** record (not a verified fact) |
| `(none)` | 32 | — | `needs_curation: provenance_missing` (all `l3_facts.kernel_refs`) |
| `flagged` | 3 | — | `needs_curation: provenance_unmappable` (unresolved flag) |
| `derived_from_verified` | 2 | — | `needs_curation: provenance_unmappable` (no V2 equivalent — see §6) |
| `placeholder` | 1 | — | `needs_curation: provenance_unmappable` (`PRICE.VEGA.MSRP.VN`, value TBD) |
| `legacy` | 1 | — | `needs_curation: provenance_unmappable` (`PRICE.RMUS.LEGACY.HERA`) |

Only **40 / 259 (15%)** carry `verified_primary`; **180 (69%)** are `claim`-tier.
Even after evidence is added, the 180 claims would import as **claim records**,
not verified facts (the gate's `claim_masquerades_as_approved` guard forbids
promoting a claim to verified without curator sign-off) — so the pool of facts
that can ever be *verified* SOT is bounded by that 40 plus whatever claims the
curator promotes.

**Source-hash coverage:** of the distinct source files referenced by ready facts,
the kernel `source_hashes.yaml` had a stored (truncated) drift hash for 1/1. See
§6 for why source *blob* fingerprints must be recomputed at real `--apply`.

---

## 5. Curation worklist (prioritized, grouped by gap type)

Every `needs_curation` fact names its precise missing field. Grouped by primary
gap (a fact may carry more than one; it is listed under its most-blocking one):

| # | Gap | Count | What the curator must add | Example ids |
|---|---|---:|---|---|
| 1 | `no_evidence_span` | **126** | a **verbatim source quote** (`raw_text`). These facts have a value + source pointer but no quotable evidence text, so no grounded citation can be built. | `PRICE.HERA.MSRP.US`, all `BOM.*`, all `HC-*`/`SC-*` capabilities |
| 2 | `evidence_locator_unmappable` | **83** | a **structured locator** (page/sheet/cell/paragraph). All `l3_facts.facts` have a verbatim `evidence_span` but only a `source_path` — no positional key the V2 evidence contract accepts. | `L3F.1.001`, `L3F.1.008`, … |
| 3 | `provenance_missing` | **32** | a `provenance_level`. All `l3_facts.kernel_refs` (duplicate an existing kernel record) carry no provenance and no span — resolve each against its `kernel_ref` source record. | `L3R.1.005`, `L3R.K.006`, … |
| 4 | `missing_source` | **5** | a `source` block. Derived facts computed from a formula with no source pointer. | `DERIVED.HERA.PREMIUM_VS_VN`, `DERIVED.ALMO.MARGIN.HERA_VN/US`, `DERIVED.HERA.BUNDLE_GAP_US/VN` |
| 5 | `provenance_unmappable` | **5** | resolve the flag / decide the mapping. `flagged`/`placeholder`/`legacy`/`derived_from_verified` have no honest V2 provenance. | `SPEC.HERA.PAYLOAD.BAYS`, `PRICE.VEGA.MSRP.VN`, `PRICE.RMUS.LEGACY.HERA` |
| 6 | `unit_drift` | **3** | reconcile the `unit` field with the source quote. Recorded `unit: lb` while the source says "… kg" (a known atomizer bug, already noted in the kernel). | `SPEC.HERA.WEIGHT.EMPTY`, `SPEC.HERA.WEIGHT.TAKEOFF`, `SPEC.HERA.MTOW` |

### Per-file worklist detail

- **specs (13):** 9 × `no_evidence_span` (the `RtR_Product_Quantitative_Advantages.xlsx`
  signature facts have only `{file}` — no `raw_text`), 3 × `unit_drift` (lb/kg bug),
  1 × `provenance_unmappable` (`SPEC.HERA.PAYLOAD.BAYS` is `flagged` + value `null`).
- **capabilities (76):** all `no_evidence_span` — the `evidence` field is a list of
  source *names*, not a verbatim quote; the `description` is RtR's own prose.
- **prices (16):** 14 × `no_evidence_span` (source is a cell reference, no quote),
  2 × `provenance_unmappable` (`placeholder` VEGA-VN TBD, `legacy` RMUS).
- **boms (25):** all `no_evidence_span` (cost + supplier + `{sheet,row}` but no quote).
  These are the **leader/restricted** tier.
- **l3_facts (117):** 83 × `evidence_locator_unmappable` (verbatim span but no
  structured locator), 32 × `provenance_missing` (kernel_refs), 2 × `provenance_unmappable`
  (`derived_from_verified`).
- **derived_costs (7):** 5 × `missing_source`, 2 × `no_evidence_span`.

### Highest-leverage curation moves (do these first)

1. **L3 locators (83 facts, one file, one shape):** add a page/sheet/cell locator
   to `l3_facts.facts`. They already have verbatim `evidence_span` — this alone
   converts the single largest block and is mechanical.
2. **specs signatures + unit bug (13 facts):** add `raw_text` to the 9
   quantitative-advantage specs and fix the 3 lb/kg unit fields — small, high-value
   (these are core product numbers).
3. **prices/boms quotes (39 facts):** attach the one-line source quote for each
   price cell / BOM line so sell-price and (leader) buy-price become grounded.
4. **Decide the ambiguous provenance (5) and formula sources (5)** with the curator.

---

## 6. Conservative mapping assumptions (Homeowner: please confirm)

Every assumption is chosen to push a doubtful fact toward `needs_curation`, never
toward a falsely-"ready" claim. These are the decisions to ratify before `--apply`:

1. **Evidence is REQUIRED for "ready" (stricter than the bare validator).** The raw
   package validator treats evidence as *optional*; this rehearsal requires a
   resolvable evidence span (verbatim quote + valid locator) for a fact to be
   "ready", because an SOT record with no citation is not fit to activate as a
   grounded fact. This is the single largest driver of `needs_curation`. **If you
   accept ungrounded records, ~40 more verified facts would flip to "ready".**
2. **Source *blob* fingerprints are placeholders in the rehearsal.** The real
   source tree (the `.xlsx`/`.docx` files) is not in the snapshot, so the package
   `source_hashes.json` uses a deterministic migration fingerprint over the
   kernel's recorded source identity, and `evidence.source_blob_sha256` is left
   unset. **At real `--apply` the adapter MUST be re-run against the real source
   tree so fingerprints attest to real bytes.**
3. **`claim` → V2 `claim` record only.** A kernel `claim` never maps to
   verified/approved; it stays a claim so the gate's `claim_masquerades_as_approved`
   guard remains meaningful. Promoting any claim to a verified fact is a curator
   decision, not an adapter transform.
4. **`flagged` / `placeholder` / `legacy` / `derived_from_verified` → `needs_curation`.**
   None has an honest V2 provenance. In particular `derived_from_verified` (2 L3
   facts) *could* be `verified_secondary` — **confirm** whether you want that
   mapping; today it is conservatively withheld.
5. **Classification = leader only for `l2_cost` (boms).** Sell-prices and
   positioning are also enumerated in the allowlist but only because the leader
   pack is a superset; per the doctrine they are staff-visible, so they map to
   `internal`, not `restricted`. **Confirm** this reading of the allowlist.
6. **Kernel `row` → V2 `region="row:<n>"`.** `row` is not a V2 locator key; it is
   carried losslessly in the free-form `region` span rather than coerced into a
   numeric page/paragraph. **Confirm** whether region-encoded rows satisfy your
   citation UX or should be replaced with true page/cell references.
7. **Synthetic principals + timestamps.** Owner/curator subject ids and effective
   dates are deterministic placeholders for the dry-run; the real `--apply` binds
   the manifest curator to an authenticated session and re-signs each attestation.

---

## 7. The real activation — command and safeguards

The Homeowner never runs the adapter's dry-run to activate. Activation is the
existing curator-gated tool, unchanged:

```bash
# 1. Re-run the adapter against the REAL source tree (not the snapshot) so source
#    fingerprints attest to real bytes, emitting into the tool's staging root.
#    (dry-run first — see command in §8 — and only proceed when the readiness
#    report shows the batch is clean.)

# 2. Activate ONLY the curated, ready batch — the existing gate, two-phase:
cd v2 && scripts/onboard-batch.sh \
    --manifest path/to/curated_manifest.json \
    --apply --approve \
    --report /tmp/onboard-ledger.json
```

Safeguards that stop a defective `--apply` (all pre-existing; not weakened here):

- **Dry-run by default.** Without `--apply` the tool only validates; `--apply`
  additionally requires `--approve` (curator approval), or the tool returns
  `approval_required` and activates nothing.
- **Two-phase, fail-closed.** Every item is validated (pure, no-DB) before any
  activation; a single defective item rejects the whole batch with a typed reason
  and **zero partial activation**.
- **Curator-signed attestation.** The publish gate verifies each package's
  attestation is signed by the manifest's `curator_subject_id` (HMAC over the
  canonical payload) — a mis-signed or curator-mismatched package cannot publish.
- **Adapter-side pre-gate.** `needs_curation` facts are never emitted into a
  package, so a fact with a missing field cannot reach `--apply` at all.
- **`claim_masquerades_as_approved` guard (proven live).** A negative test builds
  a package where a `claim` is mis-mapped to a `verified` state and confirms the
  gate rejects it — the control that stops a bad promotion at `--apply`.
- **Idempotent + audited.** Re-running the same manifest re-uses gate idempotency
  (no double-activation) and every gate call appends an append-only audit event.

---

## 8. The dry-run command + output (reproduce this rehearsal)

**A. Adapter + gate in one CLI (per-fact readiness JSON):**

```bash
cd v2/apps/backend
uv run python ../../eval/migrate/run_migration.py \
    --kernel-root /home/claude/kernel-real/registry \
    --out /tmp/rtr-migration-dryrun/staging \
    --report-json /tmp/rtr-migration-dryrun/readiness.json
# -> total facts: 259 | final status: {'needs_curation': 254, 'ready': 5}
# -> dry-run per-package gate: rtr.specs records=5 valid=True findings=0
# -> NOTHING WAS ACTIVATED. No --apply, no DB writes.
```

**B. The literal onboarding tool in dry-run (NO `--apply`)** on the converted
`rtr.specs` package:

```bash
cd v2 && scripts/onboard-batch.sh --manifest /tmp/rtr-migration-dryrun/manifest.json
```
```json
{
  "activated_count": 0,
  "apply": false,
  "approved": false,
  "status": "validated",
  "items": [
    { "kind": "sot", "ref": "package-45f576f2-…", "phase": "validate",
      "ok": true, "state": "planned_valid",
      "detail": { "record_count": 5, "evidence_count": 5, "source_key": "rtr.specs", "revision": 1 } }
  ],
  "summary": "Dry-run: all 1 item(s) would pass their gate. Re-run with --apply --approve to activate."
}
```
Exit code 0. `apply=false`, `activated_count=0` — the dress rehearsal activates nothing.
