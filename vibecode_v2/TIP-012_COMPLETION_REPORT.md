# COMPLETION REPORT — TIP-012 · Production Hardening

**STATUS:** DONE — five builder slices completed sequentially on branch
`tip-012`, consolidated by the Contractor. Individual reports:
`vibecode_v2/_tip012_builder{1..5}_report.md`.

## What was built

- **TLS ingress + secret hygiene (Builder 1):** Caddy (digest-pinned,
  read-only, cap-dropped) terminates TLS for one hostname in a `hardened`
  compose profile; HTTP→HTTPS 308; internal services publish nothing; full
  security-header set; `Secure`+`HttpOnly`+`SameSite` cookies; `APP_ENV=
  production` boot guard refuses every known-default secret and non-TLS
  config; leak probes clean. Dev profile byte-compatible with prior TIPs.
- **Quotas / limits / resilience (Builder 2):** Redis-backed per-subject+IP
  rate limits (6 classes, typed 429 + Retry-After); typed 413 body caps
  wired to an ingress `request_body max_size`; per-subject + global daily AI
  cost budgets in `governance_settings` (typed 429 `budget_exhausted`,
  admin-editable, audited); provider circuit breaker (typed 503, half-open,
  timeout-bounded); job backpressure (typed `queue_saturated`).
- **Observability (Builder 3):** Prometheus metrics on api + worker
  (internal-only, bounded labels); request-id proven ingress→api→worker;
  log-leak probe 0 leaks over 6 error paths; admin audit export (checksummed
  JSONL, self-audited); 11 alert rules (promtool-valid) + `docs/runbook.md`.
- **CI/CD + deploy/rollback (Builder 4):** `.github/workflows/verify.yml`
  (actionlint-clean, stage-mirror of the local gate); `scripts/ci-local.sh`
  (runs end-to-end here); `migration-gate.sh` (single head + pin, proven to
  fail on divergence); versioned `deploy.sh`/`rollback.sh` (drilled through
  the ingress); `verify-image-policy.sh` + 6 third-party images digest-pinned.
- **Load + SLO + drills (Builder 5):** `docs/slo.md` targets declared before
  numbers; k6 scenarios through the ingress; `evaluate-slo.sh` PASS 10/10;
  measured restore RTO and rollback timings; 429-under-load and
  breaker-under-fault verified.

## Gates (Contractor independent reruns, final tree)

| Gate | Result |
|---|---|
| backend ruff / mypy | PASS / 98 files clean |
| backend pytest unit | **293 passed / 102 skipped** |
| backend pytest FULL (live infra, one shared DB) | **377 passed / 18 skipped / 0 failed — run ×2 (fresh + populated DB), identical** |
| web eslint / tsc / vitest / build | PASS / PASS / **146** / PASS |
| Playwright (production `next start`) | **73/73** |
| through-ingress security probes (AC-01/02/03) | **15/15** via `https://rtr.local` |
| SLO evaluation (AC-13) | **PASS 10/10**, exit 0 |
| Prometheus alert rules (AC-08) | promtool **SUCCESS, 11 rules** |
| CI workflow (AC-11) | actionlint **exit 0**; ci-local.sh end-to-end green |
| migration gate (AC-11) | proven-failing on divergent head (exit 2) / pin bump (exit 3) |
| image policy (AC-12) | **PASS** — 6 third-party images digest-pinned, non-root |
| deploy/rollback drill (AC-12) | deploy ~95s cold/38s warm, rollback ~34s, health-gate green both ways |
| recovery (AC-14) | restore **RESTORE PASS**, RTO ~236s; RPO = backup-cadence window (marker-verified) |
| compose build (api/worker/web/migrate) | EXIT=0 |
| Trivy (rebuilt api image) | **Clean** — 0 HIGH/CRITICAL |
| data-integration containerized (AC-15) | **DATA INTEGRATION PASS** (tests=45, denials=18) |
| Caddyfile | `caddy validate` valid (both TLS modes) |

## Refine during verification (1 — test-only, 0 product change)

Contractor's full one-DB suite run caught an order-dependent failure in
Builder 2's `test_job_capacity_admits_when_empty_and_sheds_over_cap`: it
assumed an empty `ingestion_jobs` table, but earlier suites leave non-terminal
rows in the shared DB. Builder 2 made the test hermetic (reads live
outstanding counts, pins caps relative to them, resets limit settings in-body).
Full suite now **377/18/0** deterministically across runs. Product code
untouched — this was a harness-isolation defect, and the gate caught it.

## Deferred / environment notes

- **File-version-scoped ask retrieval** stays deferred (D-012-09; inherited
  TIP-007 deferral) — TIP-013 decides its slot.
- **ClamAV signature freshness ≤48h** — sandbox egress can't refresh; hardened
  runs used `MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600`. Local machine with
  open egress boots all 7 services healthy at the 48h default.
- **Production re-baseline (TIP-013):** DB pool 5+5 is the read-throughput
  knee (~15 reads/s local); `restore-data.sh`'s per-object mc-cp loop makes
  RTO scale with object count (switch to `mc mirror`); real-provider ask
  latency + cost budgets need remeasuring on production hardware; CSP still
  needs `'unsafe-inline'` for Next's bootstrap (nonce-tightening is an app
  change, TIP-013 candidate); branch protection must require the `verify` job.

## Deviations of note (full lists in builder reports)

Ingress routes `/api/v1/*`→api, else→web (matches the web same-origin proxy);
XFO is path-scoped (SAMEORIGIN on `/api/files/*` for the same-origin PDF
iframe); `/api/status` no longer forwards the dependency map (was leaking
internal hostnames); Redis-down policy is fail-closed for auth, fail-open+log
for reads; audit export lives at `/api/v1/audit/export` (admin-gated, not on
the closed `/admin` surface); rate limits were raised via `compose.load.yaml`
only for latency scenarios (enforcement proven separately at defaults). Only
new runtime dep is `prometheus-client` (already present); k6/promtool/
actionlint/trivy/caddy are pinned containers.
