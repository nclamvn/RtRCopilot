# _tip013_builder2_report — Phase-A tooling (items 2–4 + item-5 triage)

## STATUS

**DONE.** Curator-gated batch onboarding, V1 parity harness, representative
evaluation set + scorer, and the deferred-ledger triage (with the cheap/safe
fixes applied) are all built, exercised on **synthetic fixtures only**, and green
through the existing gates. Working tree left uncommitted for the Contractor
checkpoint. No real corpus / kernel / KnowledgeBase / research / pilot store was
read or mutated. No schema migration. No gate bypassed.

- **AC-A2** (onboarding): met — clean batch onboards through the real gates; a
  defective batch is rejected fail-closed, audited, zero partial activation;
  dry-run default; idempotent; curator approval required. Unit + integration proven.
- **AC-A3** (parity): met — fixed question set run against the pilot oracle +
  V2; per-question report committed; divergence triaged.
- **AC-A4** (eval): met — scorer emits grounded-rate, honest-null-quality,
  leak-count (0), citation-accuracy; baseline committed.
- **AC-A5** (deferred ledger): met — every TIP-007…012 deferred item dispositioned;
  the in-scope safe fixes applied keep all gates green.

## FILES CHANGED

**New**
- `v2/apps/backend/src/rtr_copilot/commands/onboard_batch.py` — the additive,
  mypy-strict onboarding command (manifest → gates; two-phase fail-closed).
- `v2/scripts/onboard-batch.sh` — thin wrapper (dry-run default; `+x`).
- `v2/apps/backend/tests/test_tip013_onboard_unit.py` — 7 hermetic unit tests.
- `v2/apps/backend/tests/test_tip013_onboard_integration.py` — 3 DB tests.
- `v2/apps/backend/tests/test_tip013_eval_unit.py` — 4 hermetic tests (oracle+scorer).
- `v2/apps/backend/tests/test_tip013_harness_integration.py` — 3 DB tests.
- `v2/eval/lib/{pilot_oracle,scoring,harness}.py` + `__init__.py` — harness.
- `v2/eval/parity/questions.json` + `pilot_fixtures/{GOI_L3.yaml,TIP7_…md,ui.html}`.
- `v2/eval/parity/parity_report.{md,json}` — generated baseline (committed).
- `v2/eval/quality/eval_set.json` + `baseline_result.{md,json}` — set + baseline.
- `v2/eval/{run_parity.py,run_eval.py,README.md}` + `onboard/sample_manifest.json`.
- `v2/load/ci-smoke/{README.md,pass/*,fail/*}` — SLO-smoke fixtures for CI.
- `vibecode_v2/TIP-013_DEFERRED_LEDGER.md` — item-5 triage.

**Modified**
- `v2/apps/backend/tests/sot_fixtures.py` — additive keyword-only overrides
  (`provenance_level`, `verification_state`, `fact_state`, `source_classification`)
  for defect injection; defaults preserve every existing caller.
- `v2/scripts/backup-data.sh` — `stat -f%z` BSDism → portable `stat -c%s`→`-f%z`→`wc -c`.
- `.github/workflows/verify.yml` — push branch `[main, tip-012]`→`[main, tip-013]`;
  new `load-smoke` job (k6-inspect parse + SLO evaluator teeth) added to `verify` needs.
- `v2/Makefile` — additive `onboard-batch`, `parity`, `eval` targets.

## TEST RESULTS

- **Backend unit (no DSN): 293 passed / 102 skipped → 304 passed / 108 skipped /
  0 failed.** (+11 hermetic unit tests: 7 onboard + 4 oracle/scorer; +6 skipped
  integration.) `ruff` clean, `mypy` strict **Success (99 source files)**.
  Suite stays hermetic — a first draft that called `asyncio.run()` inside sync
  tests broke a later async worker test in the full run; fixed by making the
  onboarding unit tests proper `async def` (TIP-012 refine lesson applied).
- **Integration (live native PG :5432 as `rtr_app`, Redis :6380; fresh DB
  `rtr_tip013` migrated to head 0009):** my subset + SOT/research =
  **19 passed** — `test_tip013_onboard_integration.py` (3), `…_harness_integration.py`
  (3), `test_sot_integration.py` (4), `test_research_integration.py` (9). Ran
  `rtr_app` (restricted role) so the append-only/REVOKE protections actually bite.
- **Parity baseline (`make parity`): answer agreement 6/7 (85.7%).** P1–P6
  (source-scoped fact-lookup + honest-null) agree exactly, including citation
  agreement on fact-lookups (pilot `HERA-END` ↔ V2 `HERA-END`). P7 is a
  **deliberately-unscoped honest-null probe → 1 triaged divergence** (see ISSUES).
- **Eval baseline (`make eval`): grounded-rate 100% (3/3), honest-null-quality
  100% (4/4), leak-count 0, citation-accuracy 100% — baseline PASSED.** Covers
  fact-lookup, honest-null, cross-version/freshness, ACL-restricted (deny → refuse,
  0 leak), verification gating (claim filtered under `require_verified`),
  research-vs-SOT (beacon lives only in the research zone, labeled `research`,
  never surfaces in the SOT answer). Idempotent across re-runs (proven by test).
- **Ops fixes re-verified:**
  - `backup-data.sh`: `bash -n` clean; portable size returns 4096 on this Linux host.
  - `verify.yml`: **`actionlint` v1.7.7 exit 0**; `evaluate-slo.sh` on the committed
    fixtures → pass-fixture **exit 0**, breach-fixture **exit 1** (SLO gate teeth).
  - `onboard-batch.sh` CLI: dry-run → `status=validated` exit 0; `--apply` without
    `--approve` → exit 3 (`approval_required`).

## ISSUES

1. **Parity P7 divergence (expected, triaged, non-blocking).** On an UNSCOPED
   honest-null question the pilot honest-nulls but V2 grounds. Root cause is the
   documented REQ-010 limitation: V2's 64-dim **offline hash embedding is
   functional, not semantic**, so it returns an arbitrary nearest neighbour and
   the offline extractive provider grounds on it. Every source-scoped ask
   (the TIP-011 file-scope feature) agrees. Re-measured with the real semantic
   embedding + provider on the real corpus in Phase B. Kept in the set on purpose
   so the harness demonstrably catches divergence rather than being curated to pass.
2. **`restore-data.sh` `mc cp`→`mc mirror` NOT done (fix-in-pilot).** It is *not*
   a clean swap: the per-object loop writes per-object `--attr` metadata
   (`restore-operation-id`/`sha256`/`byte-size`) that `restore_bucket_guard.py::complete`
   re-verifies to keep RESTORE PASS green; `mc mirror` sets no per-object metadata,
   so a naive swap turns the drill RED. It also can't be safely verified here (no
   MinIO/full stack). Left as Phase B with rationale in the ledger.

## DEVIATIONS

- **Pilot oracle is loaded, not spun up.** Importing `phase1_pilot/copilot_server.py`
  reads the REAL `l3_pipeline/GOI_L3.yaml` at module load, which is off-limits.
  Per the TIP constraint's sanctioned fallback, `eval/lib/pilot_oracle.py` execs the
  pilot source in an isolated namespace with `__file__` pointed at a **synthetic**
  fixture dir, so its `find()`/`HERE` resolve only the synthetic GOI/prompt/ui.html.
  This reads the pilot's real answering logic (`search`+`confident`+`mock_answer`)
  without ever touching or mutating its store (the HTTP server binds only under
  `__main__`, never entered).
- **Research "graduation gate" correctly stops at STAGED.** Per REQ-033 the
  graduation gate never auto-activates; the tool runs import→propose→decide(approve)
  which stages a candidate into the SOT publish pipeline and stops (the integration
  test asserts the candidate lifecycle is `staged`, not `active`).
- Full heavy integration battery (compose/Trivy/data-integration/Playwright, MinIO
  tests) NOT run — MinIO isn't available here and the task assigns the heavy battery
  to the Contractor.

## SUGGESTIONS (Contractor rerun / Phase B inheritance)

**Contractor must rerun:**
- The heavy AC-A6 battery on the full stack: backend full one-DB suite **twice,
  hermetic** (my additions use unique/deterministic keys and idempotent seeding —
  verify no order-dependence), web vitest, Playwright, compose build, Trivy,
  data-integration.
- The new **`load-smoke` CI job with real Docker+k6** (I validated its YAML with
  actionlint and the SLO-evaluator teeth locally, but couldn't run `docker`/`k6
  inspect` in this sandbox). All k6 scenarios read `__ENV` with defaults and the
  only `throw` is inside `setup()` (not run by `inspect`), so it should pass.
- Re-exercise `make onboard-batch`, `make parity`, `make eval` on a fresh migrated
  synthetic DB to reproduce the committed baselines (both runners are idempotent).

**Phase B inherits (from the ledger):** restore `mc mirror` (with per-object
markers preserved) + re-run RESTORE PASS on the real deployment; DB pool sizing
re-baseline (5+5 knee ~15 reads/s); CSP nonce-tightening; real-provider
latency/cost calibration; ClamAV signature freshness; file-version/attachment
retrieval (REQ-020); and the whole real data/identity/certs cutover — which is
exactly what the Phase-A onboarding + parity + eval tooling here is built to re-run.
Owner actions at go: mark `verify` a required status check; external pen test.
