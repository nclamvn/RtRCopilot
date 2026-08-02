# TIP-013 Phase B · Builder-3 Report — kernel→package adapter + migration dry-run

## STATUS
DONE — DRY-RUN ONLY. Built the kernel→V2-SOT-package adapter, ran the full real
kernel registry (259 facts) through the existing onboarding dry-run gate, and
produced the per-fact readiness report. **Nothing was activated** — no `--apply`,
no production DB write, no real-data activation. All gates green; additive only.

## FILES CHANGED (all additive; no product/onboarding/gate code touched)
- `v2/eval/migrate/__init__.py` — package marker.
- `v2/eval/migrate/kernel_adapter.py` — the adapter: read the read-only kernel
  registry, conservatively map each fact → V2 SOT record/evidence, classify via
  the leader allowlist, emit deterministic staged packages, summarize.
- `v2/eval/migrate/run_migration.py` — thin CLI: convert → emit → drive the
  emitted packages through the tool's dry-run validators → write per-fact
  readiness JSON. Has **no `--apply` flag**; cannot activate anything.
- `v2/apps/backend/tests/test_tip013_migrate_unit.py` — 11 hermetic unit tests.
- `vibecode_v2/TIP-013_PHASE_B_MIGRATION_READINESS.md` — the readiness report.
- `vibecode_v2/_tip013_builder3_report.md` — this report.

## RESULTS

**Adapter fact totals (259 real facts):**

| File | Facts | ready | needs_curation | rejected |
|---|---:|---:|---:|---:|
| specs | 18 | 5 | 13 | 0 |
| capabilities | 76 | 0 | 76 | 0 |
| prices | 16 | 0 | 16 | 0 |
| boms | 25 | 0 | 25 | 0 |
| l3_facts | 117 | 0 | 117 | 0 |
| derived_costs | 7 | 0 | 7 | 0 |
| **Overall** | **259** | **5** | **254** | **0** |

Ready facts (all `verified_primary`, all with a verbatim source quote):
`SPEC.HERA.PAYLOAD.MAX`, `SPEC.HERA.MOTORS`, `SPEC.HERA.FLIGHT.NO_PAYLOAD`,
`SPEC.HERA.FLIGHT.1KG`, `SPEC.HERA.FLIGHT.14KG` — emitted as one real package
`rtr.specs` that **passed the real gate** (records=5, evidence=5, valid=True,
findings=0).

**Gap histogram (primary blocker, sums to 254):** `no_evidence_span` 126,
`evidence_locator_unmappable` 83, `provenance_missing` 32, `missing_source` 5,
`provenance_unmappable` 5, `unit_drift` 3.

**Classification split (from `leader_allowlist.yaml` doctrine):** leader/`restricted`
25 (all `boms.yaml` buy-price + supplier), staff/`internal` 234.

**Provenance coverage:** `verified_primary` 40, `claim` 180, `(none)` 32,
`flagged` 3, `derived_from_verified` 2, `placeholder` 1, `legacy` 1. Only 15% is
verified; 69% is claim-tier (would import as *claim* records, never verified).

**Dry-run command + output (the literal tool, NO `--apply`):**
```
$ cd v2 && scripts/onboard-batch.sh --manifest /tmp/rtr-migration-dryrun/manifest.json
{ "apply": false, "approved": false, "activated_count": 0, "status": "validated",
  "items": [ { "kind":"sot", "ok":true, "state":"planned_valid",
               "detail": {"record_count":5,"evidence_count":5,"source_key":"rtr.specs"} } ],
  "summary": "Dry-run: all 1 item(s) would pass their gate. Re-run with --apply --approve to activate." }
exit 0
```

**Gate counts (must stay green — maintained):**
- `uv run ruff check .` → All checks passed (backend + `eval/migrate`).
- `uv run mypy` → Success, 99 source files (unchanged); adapter+CLI also mypy-strict clean (2 files).
- `uv run pytest` → **315 passed, 108 skipped** (baseline 304 + 11 new hermetic tests; integration self-skips without a DB). No regressions.

## ISSUES
- The kernel is not built for the V2 grounded-evidence contract, so only ~2% is
  package-ready today. This is a real finding, not a tooling defect: the gaps are
  missing verbatim spans / structured locators / honest provenance, not bad data.
- The real source blobs (`.xlsx`/`.docx`) are not in the snapshot, so true source
  content hashes cannot be computed in the rehearsal (see DEVIATIONS #2).
- `l3_facts.yaml` holds two lists (`facts` 85 + `kernel_refs` 32 = 117); both are
  processed. `entities.yaml` is an entity registry, not facts — excluded (documented).

## DEVIATIONS (every conservative mapping assumption — Homeowner to confirm)
1. **Evidence REQUIRED for "ready"** (stricter than the bare validator, which
   treats evidence as optional). An SOT record without a citation is not counted
   ready. Accepting ungrounded records would flip ~40 more verified facts to ready.
2. **Source-blob fingerprints are placeholders** (deterministic migration
   fingerprint over the kernel's recorded source identity; `evidence.source_blob_sha256`
   left unset). The real `--apply` must re-run the adapter against the real source
   tree so fingerprints attest to real bytes.
3. **`claim` → V2 `claim` only** (never verified/approved) — keeps the gate's
   `claim_masquerades_as_approved` guard meaningful.
4. **`flagged`/`placeholder`/`legacy`/`derived_from_verified` → `needs_curation`**
   (no honest V2 provenance). `derived_from_verified` (2 facts) could be
   `verified_secondary` — confirm.
5. **Classification: only `l2_cost` (boms) is leader/`restricted`;** sell-price and
   positioning are staff/`internal` per the allowlist doctrine (leader pack is a
   superset). Confirm this reading.
6. **Kernel `row` → V2 `region="row:<n>"`** (lossless free-form span, not coerced
   into a numeric page/paragraph). Confirm this satisfies citation UX.
7. **Synthetic deterministic principals/timestamps** for the dry-run; real
   `--apply` binds an authenticated curator and re-signs attestations.

## SUGGESTIONS
**Curation worklist headline for the Homeowner** — 254 facts, four mechanical moves:
1. **L3 locators (83, one file, one shape):** add a page/sheet/cell to
   `l3_facts.facts` (they already carry a verbatim `evidence_span`) — biggest single win.
2. **specs (13):** add `raw_text` to the 9 quantitative-advantage signature specs +
   fix the 3 lb/kg unit-drift fields (core product numbers).
3. **prices + boms (39):** attach the one-line source quote per cell/line so sell
   price and (leader) buy price become grounded.
4. **Decide the 5 ambiguous-provenance and 5 no-source facts** with the curator.
Also: attach `provenance_level` to the 32 `l3_facts.kernel_refs` (resolve against
their `kernel_ref` source record).

**What the real `--apply` needs (in order):** (a) re-run the adapter against the
real source tree so source fingerprints are true blob hashes; (b) run the curation
worklist so a batch converts clean; (c) dry-run the curated manifest and confirm
the readiness report is clean; (d) run `scripts/onboard-batch.sh --manifest … --apply
--approve --report …` under an authenticated curator with a real `SOT_SIGNING_SECRET`.
The pre-existing safeguards (two-phase fail-closed, curator-signed attestation,
`claim_masquerades` guard — proven live by a negative test, idempotency, audit)
stop the batch if anything is defective. This de-risks H3 ("curated SOT batches")
in `TIP-013_GO_NO_GO.md` by making the remaining curation finite and explicit.
```
Scope note: adapter + report + tests only, all additive under v2/eval/migrate/
and vibecode_v2/. No onboarding/gate/product code modified. DRY-RUN ONLY.
```
