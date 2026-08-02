# TIP-013B — Builder Report (comprehensive completion of the curation, DRY-RUN)

## STATUS
**DONE — GREEN.** The overlay is extended with the Homeowner's final decision
(02/08/2026): every one of the **259** kernel facts now ends with an explicit,
defensible final disposition. Ready **131 → 219**. **DRY-RUN ONLY** — no `--apply`,
no activation, no production-DB write, **no write-back to the read-only kernel
snapshot** (mtime verified unchanged before/after). All 6 emitted packages PASS the
real publish-gate validators; checksums deterministic; nothing in limbo.

Gates before → after (all green, unchanged status):
- ruff (backend + `eval/migrate`): **All checks passed** → **All checks passed**
- mypy canonical **99** files clean + `eval/migrate` **4** files clean → same
- pytest migrate unit **30 → 41** passed (+11 hermetic); unit subset **238 passed, 1
  skipped** (pre-existing skip elsewhere)
- Did NOT run the heavy battery (parity/eval) — that is the Contractor's step.

## FILES CHANGED (additive only; no product/gate/onboarding code touched)
- `v2/eval/migrate/curation_overlay.py` — added wave-2 rules: D1B (67-cap promote
  RULE), D2B (20-kernel_ref cascade RULE resolved against a promoted-capability id
  set), D3B (interim-spec-duplicate promote); + `capability_is_promoted` /
  `promoted_capability_ids` helpers; + the `final_disposition(...)` classifier and
  `IRREDUCIBLE_GAP` / `PROMOTE_INTERIM_SPEC_DUP` constants that make every fact's
  terminal disposition explicit and testable.
- `v2/eval/migrate/kernel_adapter.py` — `convert_registry` computes the
  promoted-capability id set once from the same registry and threads
  `promoted_source_ids` into `convert_fact` → `overlay.decide` (drives the cascade
  as a genuine dependency, not a hand list). Baseline behavior unchanged when no
  overlay is passed.
- `v2/apps/backend/tests/test_tip013_migrate_unit.py` — +11 hermetic tests (see
  Tests below).
- `vibecode_v2/TIP-013B_FINAL_DISPOSITION_LEDGER.md` — **NEW.** Comprehensive
  ledger covering all 259 facts (grouped, reconciles to 259), each with FINAL tier +
  one-line reason; proves nothing is in limbo.
- `vibecode_v2/TIP-013B_MIGRATION_READINESS_CURATED.md` — updated to the final
  post-completion numbers (219 ready), 131 milestone kept visible.

## RESULTS

### Final split — overall (259 facts)
| Tier | Count | Terminal disposition |
|---|---:|---|
| strict | 8 | ready (no caveat) |
| soft | 205 | ready + `needs_double_check` |
| strategic | 6 | ready + caveat |
| **READY** | **219** | strict + soft + strategic |
| claim | 33 | held (30 claim-hold + 3 derived-hold) |
| curate | 6 | irreducible (3 unmappable) + derived-hold-missing-source (3) |
| excluded | 1 | `L3R.K.005` |

### Final split — by file
| File | Facts | strict | soft | strategic | curate | claim | excluded |
|---|---:|---:|---:|---:|---:|---:|---:|
| specs | 18 | 8 | 2 | — | 1 | 7 | — |
| capabilities | 76 | — | 76 | — | — | — | — |
| prices | 16 | — | 13 | — | 2 | 1 | — |
| boms | 25 | — | 3 | — | — | 22 | — |
| l3_facts | 117 | — | 110 | 6 | — | — | 1 |
| derived_costs | 7 | — | 1 | — | 3 | 3 | — |
| **Total** | **259** | **8** | **205** | **6** | **6** | **33** | **1** |

soft +88 vs the 131 wave = 67 caps (D1B) + 20 cascade (D2B) + 1 interim-dup (D3B).

### Disposition-ledger reconciliation to 259 (nothing in limbo)
```
ready-strict     8 | ready-soft 205 | ready-strategic 6   -> READY 219
claim-held      30 | derived-held  6                       -> HELD  36
irreducible-gap  3 | excluded      1
=================================================== TOTAL   259  ✓
```
Asserted in code by `final_disposition(...)` +
`test_final_disposition_reconciles_the_real_run_to_259`.

### Per-package publish-gate result (DRY-RUN, real validators)
All 6 packages **PASS** — `valid=True, findings=0`. Deterministic (byte-identical
across two independent runs; unchanged packages keep their 131-wave checksum).
| Package | records | evidence | valid | findings | checksum(12) |
|---|---:|---:|:---:|---:|---|
| rtr.specs | 10 | 8 | ✅ | 0 | `e6c2cc922534` |
| rtr.capabilities | 76 | 0 | ✅ | 0 | `39cc87daccdd` |
| rtr.prices | 13 | 0 | ✅ | 0 | `f3cc905b8186` |
| rtr.boms (leader) | 3 | 0 | ✅ | 0 | `154ec5c7f248` |
| rtr.l3_facts | 116 | 0 | ✅ | 0 | `ccb8a7de25d9` |
| rtr.derived_costs | 1 | 0 | ✅ | 0 | `fccafd57c4c6` |

**0 activation confirmed:** every tool-plan item is `phase=validate,
state=planned_valid`; CLI prints `NOTHING WAS ACTIVATED. No --apply, no DB writes.`
Kernel snapshot mtime identical before/after the run.

### Any fact held back at the gate?
**None.** Every fact the decisions named was promotable and PASSED the gate — no
promoted package failed a required-field check, so nothing had to be force-held.
The 40 non-ready facts are held by the *decisions themselves* (explicit hold /
derived / irreducible / excluded), not by a gate rejection.

### Wave-2 decisions, honesty
- D1B: all 67 promoted caps carry a real non-empty `evidence` documentary reference;
  each maps `claim → approved_internal` (never masquerading verified) with a source
  note built from that real `evidence` ref + `needs_double_check`. No fabrication.
- D2B cascade: all 20 curate kernel_refs verified to resolve to a now-promoted
  capability (full mapping in the ledger §5); resolved against the id set computed
  from the same registry.
- D3B: `SPEC.HERA.MTOW.HC001` duplicates the verified `SPEC.HERA.MTOW`; promoted
  `approved_internal` + caveat (see Issues for the deliberate honesty choice).

## ISSUES
- **`SPEC.HERA.MTOW.HC001` carries a residual conflict.** The kernel marks it
  `CONFLICT với HERA SPEC TBD · Engineering chốt số chính xác`, its own matrix figure
  is `30.5` with unit `lb (+)` while the verified `SPEC.HERA.MTOW` is `31 kg`. The
  Homeowner decision is explicit ("promote that one"), so I promoted it — but
  deliberately to **`approved_internal` + `needs_double_check`** (NOT
  `verified_primary`), with a source note naming the verified spec it duplicates, so
  the value is never misrepresented as verbatim-from-verified and the engineering
  reconciliation rides visibly with the fact. It PASSES the gate (the gate does not
  cross-check sibling values). Flagging for Homeowner awareness; easy to revert to
  `claim`-held if preferred.
- No other issues. No product/gate/onboarding code was changed.

## DEVIATIONS
- The cascade (D2B) is implemented as a **RULE resolved against the
  promoted-capability id set the adapter computes from the same registry**, rather
  than a hardcoded 20-id list — this makes it a genuine dependency ("kernel_ref
  inherits soft because its source cap is now promoted") and is future-proof if the
  cap set changes. The 20 real linkages are also documented in the ledger.
- The holds/derived/irreducible dispositions are **not transforms** (claim/curate is
  already the default outcome); they are recorded as an explicit, tested classifier
  (`final_disposition`) + reasons, which is what makes "nothing in limbo"
  machine-checkable. This is additive and pure.
- `TIP-013B_KERNEL_REF_RESOLUTION.md` referenced in the overlay docstring does not
  exist on disk (pre-existing reference, not introduced here); the 20-cap cascade
  mapping is instead documented in the disposition ledger §5.

## SUGGESTIONS
- **Nothing is in limbo — confirmed.** All 259 facts reconcile: 219 ready + 30
  claim-held + 6 derived-held + 3 irreducible-gap + 1 excluded. The 40 non-ready are
  held by decision with a named reason, not left unresolved.
- **What remains is strictly the Homeowner's, not a build step:**
  1. The real `--apply` (H1 OIDC / H2 TLS cert / H6 secrets) — I hold no real
     credentials; recommend the Contractor's pilot-batch path (8 strict + ~10 soft
     HERA/VEGA core → `make parity`/`make eval` → then batch the rest under a curator
     attestation signature).
  2. Later promotions that need a *human* input, not code: per-item currency
     confirmation before promoting the 23 cost/price holds (leader-zone); an
     engineering number for `SPEC.HERA.MTOW.HC001` and `SPEC.HERA.PAYLOAD.BAYS`
     (3-vs-4 bays); a decision to retire/supersede `PRICE.RMUS.LEGACY.HERA`; the
     VEGA-VN price for `PRICE.VEGA.MSRP.VN`; derivation `source` pointers for the 3
     `DERIVED.*` gaps.
  3. The 3 derived-held stay in the computed layer by design — recommend never
     freezing them as SOT facts; recompute from L1 inputs at answer time.
- **Optional next build (only if the Homeowner asks):** a curated per-package
  manifest generator so a real `--apply --approve` is one signed step per batch. Not
  done here — DRY-RUN discipline.
