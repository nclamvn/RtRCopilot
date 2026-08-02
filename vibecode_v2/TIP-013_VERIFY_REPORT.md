# VERIFY REPORT — TIP-013 · Phase A (Migration & Final Verify machinery)

**Date:** 01/08/2026
**Verifier:** Contractor (independent of the two Phase-A builders)
**Scope:** Phase A only — the final-verification MACHINERY on synthetic
fixtures. Phase B (real data / identity / certs / pilot / go-no-go) is
Homeowner-gated and recorded in `TIP-013_GO_NO_GO.md`, NOT executed here.
**Environment:** cloud sandbox — native PostgreSQL 16 (fresh DB per run),
MinIO, Redis; Docker compose stack.

---

## Verdict — Phase A

**VERIFIED · READY (Phase A).** The final-verification mechanism is proven on
synthetic fixtures. Phase B remains a Homeowner-gated checklist.

- Phase-A acceptance: **AC-A1…AC-A6 all PASS**.
- P0 open: **0**. P1 open: **0**.
- The release is **NOT declared GO** by the agent. Phase A proves the
  mechanism is ready; the Homeowner authorizes the real data and the launch
  via `TIP-013_GO_NO_GO.md`.

## SCENARIO RESULTS (independently rerun)

| AC | Verdict | Evidence |
|---|---|---|
| AC-A1 34/34 REQ matrix | PASS | `TIP-013_REQ_MATRIX.md` — 34 rows, each anchored to code/test/migration/gate. Contractor sample re-check: REQ-020 confirmed `partial` (no attachment→answer path in `rag/`); REQ-007 DLP present; web+migrations untouched by TIP-013 (git-confirmed). Counts: **33 implemented / 1 partial / 0 deferred** |
| AC-A2 batch onboarding | PASS | onboarding integration test 3/3: clean synthetic batch onboards through the real publish/graduation gate; defective batch rejected fail-closed, zero partial activation; dry-run default, `--apply` requires `--approve` (exit 3 without) |
| AC-A3 V1 parity harness | PASS | `make parity` reproduced independently on a fresh DB: **6/7 agreement**; P7 is the documented unscoped-honest-null artifact (offline hash embedding), triaged, re-measured on real embedding in Phase B; scoped asks agree exactly incl. citations |
| AC-A4 evaluation scorer | PASS | `make eval` reproduced independently: **grounded 100% · honest-null 100% · leak-count 0 · citation-accuracy 100% · PASS**; ACL-restricted / verification-gating / research-vs-SOT all correctly honest-null (zero leak); research beacon labeled `research`, never in an SOT answer |
| AC-A5 deferred ledger | PASS | `TIP-013_DEFERRED_LEDGER.md` dispositions every TIP-007…012 deferred item; cheap safe fixes applied (portable `stat -c%s`; `verify.yml` load-smoke stage + `main` branch, actionlint exit 0); `mc mirror` correctly left fix-in-pilot (breaks the per-object marker the restore guard verifies — rationale recorded) |
| AC-A6 no regression | PASS | backend full suite **394 passed / 18 skipped / 0 failed — run ×2 (fresh + populated DB), identical**; ruff/mypy(99) clean; web+migrations untouched so Playwright 73/73 + axe + head `0009` stand from TIP-012; data-integration **PASS** (tests=45) |

Failed: **0**.

## TECHNICAL HEALTH (independent)

backend full **394/18/0** twice (hermetic, +17 over TIP-012's 377 from the new
onboarding/eval tests); ruff/mypy(99 files) clean; parity + eval baselines
reproduced from scratch; onboarding fail-closed proven; data-integration PASS;
actionlint exit 0 on the updated CI workflow; single alembic head `0009` (no
migration in this TIP); no new production dependency.

## WHAT PHASE A PROVES vs WHAT IT DOES NOT

**Proves (mechanism ready):** the 34 requirements are implemented in code with
runnable gates; batches can only enter through curator-approved, fail-closed
gates; V2 answer behavior can be measured against the V1 oracle; answer quality
is scorable with a zero-leak guarantee; the CI/ops debt is triaged and the
cheap fixes are in.

**Does NOT prove (Homeowner-gated, Phase B):** correctness/usefulness on the
REAL corpus; real OIDC tenant + real TLS certs live; parity on the real 137/162
records; eval thresholds on the representative real corpus; the staged pilot and
the five operating metrics; the go/no-go signature. Every REQ that is
"implemented on synthetic fixtures" still owes real-data proof — that is Phase
B, not a defect.

## DEFERRED LEDGER OUTCOME (summary; full in `TIP-013_DEFERRED_LEDGER.md`)

- **Fixed now:** `backup-data.sh` portable byte-size; `verify.yml` load/SLO
  smoke stage + `main` trigger.
- **Fix-in-pilot (Phase B):** `restore-data.sh` `mc mirror` (must keep the
  per-object restore marker); DB-pool re-baseline on production hardware; CSP
  nonce-tightening; real-provider ask latency + cost budget calibration;
  ClamAV signature freshness on open egress; file-version/attachment retrieval
  (REQ-020).
- **Accept-with-owner:** branch-protection "require the `verify` job" (a
  GitHub setting the Homeowner enables); external penetration test (Phase-B
  go/no-go input).

## DECISIONS NEEDED FROM HOMEOWNER

Phase B cannot proceed without the inputs enumerated in `TIP-013_GO_NO_GO.md`:
real Google Workspace OIDC tenant + allowed domains; real TLS certificates;
curated/classified real data batches with named owners; the pilot group and
their real questions; and the go/no-go sign-off authority. The agent has filled
every row it can from Phase A; the Homeowner-gated rows are marked
`AWAITING HOMEOWNER`.

*Không sửa ngược sau khi commit; Phase B kết quả ghi bổ sung khi thực thi.*
