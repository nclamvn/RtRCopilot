# VERIFY REPORT — TIP-012 · Production Hardening

**Date:** 01/08/2026
**Verifier:** Contractor (independent of the five builder agents)
**Environment:** cloud sandbox — native PostgreSQL 16 (fresh DB per run),
MinIO, Redis; Docker compose hardened stack with rebuilt TIP-012 images behind
the Caddy ingress at `https://rtr.local`; chromium; production `next start`.
**Method:** independent rerun of every gate on the final tree (builder numbers
not trusted), adversarial + through-ingress probes, SLO evaluation, drill
review, per-AC verdict.

---

## Verdict

**VERIFIED · READY.**

- Acceptance criteria: **16/16 PASS** (deferred items are scoped-out, not
  failures — see Deferred).
- P0 open: **0**. P1 open: **0**.
- Gate chính — *SLO/load targets met; restore and rollback drill pass; hệ
  thống thất bại có kiểm soát, quan sát được, phục hồi được*: **PASS** — SLO
  10/10, restore RESTORE PASS + measured RTO, rollback drilled green,
  breaker/rate-limit hold under load.

## REQUIREMENT COVERAGE

- **Owned, now implemented+enforced:** REQ-005 (HTTPS, session, headers,
  rate/body/cost limits), REQ-029 (CI: unit/integration/E2E/security/load +
  migration gate), REQ-030 (metrics/alerts/backup/restore/rollback/RPO/RTO
  runbook), REQ-031 (per-user + workload quota/cost, no single call blocks the
  app).
- **Hardened:** REQ-002 (config now fail-closed too), REQ-006 (audit export),
  REQ-021 (no object-key/URL leaks re-proven through the ingress).

## SCENARIO RESULTS (independently rerun)

| AC | Verdict | Evidence |
|---|---|---|
| AC-01 TLS ingress fronts all | PASS | 15/15 through-ingress probes; only ingress publishes ports; 308 redirect; auth completes on `https://rtr.local` |
| AC-02 security headers | PASS | probe asserts HSTS/CSP/XFO/nosniff/Referrer/Permissions; browser smoke 0 CSP violations |
| AC-03 prod boot fail-closed | PASS | boot guard refuses all default secrets (subprocess test); leak probes over 10 surfaces clean |
| AC-04 rate + body limits | PASS | per-class 429+Retry-After (unit+integration+under-load 120→429); typed 413 |
| AC-05 cost budgets | PASS | per-subject+global daily debit/breach `budget_exhausted`, admin-editable, audited |
| AC-06 slow provider survivable | PASS | timeout-bounded hung call; breaker open→503 half-open (integration) |
| AC-07 queue backpressure | PASS | concurrency caps → typed `queue_saturated`; hermetic after refine |
| AC-08 metrics meaningful | PASS | api+worker Prometheus exposition; promtool 11 rules SUCCESS |
| AC-09 logs traceable + leak-free | PASS | request-id ingress→api→worker proven; 0 leaks over 6 error paths |
| AC-10 audit export | PASS | admin-gated checksummed JSONL; non-admin 403; export self-audited |
| AC-11 CI gate blocks | PASS | actionlint exit 0; ci-local.sh end-to-end green; migration-gate proven-failing (exit 2/3) |
| AC-12 deploy + rollback drilled | PASS | versioned deploy+rollback through ingress, health green both ways, timed; schema never auto-downgraded |
| AC-13 SLOs declared then met | PASS | `docs/slo.md` targets pre-committed; evaluate-slo.sh PASS 10/10 |
| AC-14 recovery measured | PASS | RESTORE PASS on hardened stack; RTO ~236s; RPO = backup-cadence window (marker-verified); rollback timed |
| AC-15 no regression | PASS | backend full 377/18/0 ×2; web 146+build; Playwright 73/73; Trivy Clean; data-integration PASS; probes zero |
| AC-16 full verification | PASS | zero P0/P1 across every gate above |

Failed: **0**.

## TECHNICAL HEALTH (independent)

Build PASS both sides; ruff/mypy(98)/tsc clean; backend full **377 passed / 18
skipped / 0 failed** run twice on fresh then populated DB (hermetic, after the
one refine); web vitest 146; Playwright 73/73; through-ingress security probes
15/15; SLO 10/10; Trivy Clean; data-integration PASS; promtool/actionlint/
caddy/image-policy all valid; single alembic head `0009` (no migration in this
TIP).

## REFINE FOUND BY THIS VERIFY

The Contractor's full one-DB suite run (not the builders' per-file runs) caught
an order-dependent failure in the job-capacity integration test — it assumed an
empty `ingestion_jobs` table. Returned to Builder 2, fixed to be hermetic (live
outstanding counts + relative caps + in-body settings reset), re-verified
377/18/0 twice. Product code untouched; the gate demonstrably has teeth.

## DEFERRED (scoped-out, not failures)

1. **File-version-scoped ask retrieval** — D-012-09, inherited TIP-007
   deferral; TIP-013 decides.
2. **ClamAV signature freshness ≤48h** — sandbox egress limitation; local
   machine boots healthy at default. Hardened runs used the documented
   `MALWARE_SIGNATURE_MAX_AGE_SECONDS` override.
3. **External penetration test** — TIP-013 go/no-go input; only internal
   probes here.
4. **Production re-baseline** (DB pool sizing, `mc mirror` restore, real-
   provider latency/cost, CSP nonce-tightening, branch-protection enforcement)
   — carried to TIP-013 with concrete pointers in the completion report.

## CRITICAL ISSUES

None. Non-blocking follow-ups recorded above.

## DECISIONS NEEDED FROM HOMEOWNER

None blocking. TIP-012 is eligible to merge to `main`. Next per Task Graph:
**TIP-013 Migration, Pilot & Final Verify** — the go-live gate with real data,
34/34 REQ matrix, staged pilot and go/no-go.

*Không sửa ngược sau khi commit; bổ sung bằng addendum nếu có kết quả mới.*
