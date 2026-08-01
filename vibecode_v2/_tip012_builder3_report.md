# TIP-012 · Builder 3 Report — observability (AC-08, AC-09, AC-10)

## STATUS

**DONE.** Prometheus exposition now covers the api AND worker (worker on a
dedicated internal port, never via the ingress); HTTP latency/error, DB pool,
provider call/budget/breaker, rate-limit, queue depth/duration and audit-chain
integrity are all metered — Builder 2's limit/breaker/budget/queue events
instrumented at their emission points (no rewrite of their logic). Request-id
propagation is proven end-to-end (api logs R → job row persists R → worker logs
R). A log-leak probe exercises six error paths and finds zero secrets. Committed
`infra/observability/prometheus.yml` + `alerts.yml` (11 rules, each with a
runbook pointer) pass `promtool check config` + `check rules`. An admin-gated,
checksummed JSONL audit export (`GET /api/v1/audit/export`) is itself audited.
`docs/runbook.md` carries 11 playbooks cross-linked to the alert names.
Baseline stayed green throughout.

## FILES CHANGED

New:
- `apps/backend/src/rtr_copilot/observability/` — `metrics.py` (all metric
  objects, bounded labels), `http.py` (route-class classifier + outermost
  latency middleware + `meter_error`), `db.py` (crash-safe pool-gauge refresh),
  `worker.py` (`start_worker_metrics_server`, `observe_job`, `log_job_request_id`),
  `__init__.py`.
- `apps/backend/src/rtr_copilot/governance/audit_export.py` — `AuditExportService`
  + router (`/api/v1/audit/export`); admin policy gate, bounded/checksummed JSONL,
  redacted details, self-audited export.
- `infra/observability/prometheus.yml` — scrape config (`api:8000`,
  `worker:9100` on the compose network; self-scrape).
- `infra/observability/alerts.yml` — 11 curated rules, each `runbook`-annotated.
- `docs/runbook.md` — 11 incident playbooks referencing real commands + alerts.
- `apps/backend/tests/test_observability_unit.py` — 29 unit tests.
- `apps/backend/tests/test_observability_integration.py` — 5 integration tests.

Modified (all at documented integration points):
- `api/main.py` — install metrics middleware OUTERMOST (sees terminal status of
  limit 429/413 and synthesized 500); `meter_error` in the three exception
  handlers; `/metrics` refreshes DB-pool gauges at scrape; include audit-export
  router.
- `worker/main.py` — start the worker metrics server; per-loop refresh of
  job-queue-depth + DB-pool gauges; throttled audit-chain verify (feeds
  `rtr_audit_chain_valid`); `observe_job` duration by family; queue-saturation
  counter on the index rising edge; request-id log for ping.
- `rag/answering.py` — provider call latency/failure histograms + counters,
  breaker open gauge/refusals, budget debit units + exhaustion counter (at
  Builder 2's emission points).
- `limits/middleware.py` — rate-limit/body rejection counter + typed-error meter.
- `limits/backpressure.py` — queue-saturation counter on `QueueSaturated`.
- `ingestion/service.py`, `documents/service.py` — worker request-id log line
  when a job is processed (id read from the persisted job row).
- `config.py` — `worker_metrics_port` (default 9100, bounded).
- `compose.yaml` — worker `WORKER_METRICS_PORT` env + `expose: 9100` (network
  only, unpublished).
- `.env.example` — `WORKER_METRICS_PORT` documented.

No schema migration. `prometheus-client==0.22.1` was already pinned in
`pyproject.toml` (used by the pre-existing `ingestion/metrics.py`); no new dep
was needed — the standard pure-python exposition lib is already in place.

## TEST RESULTS

Backend gate (`uv run ruff check . && uv run mypy && uv run pytest`):
- ruff: PASS → PASS
- mypy: **92 → 98 files**, strict PASS (+6: 5 observability modules + audit_export)
- pytest unit: **264 passed / 97 skipped → 293 passed / 102 skipped**
  (+29 `test_observability_unit.py`; +5 integration tests skipped without a DSN)

Integration (live native infra — Postgres :5432 fresh DB migrated to head,
Redis :6380, MinIO :9002 bucket `rtr-test`, `SOT_SIGNING_SECRET=test-only-…`):
- `test_observability_integration.py`: **5 passed** —
  - request-id chain: api logs R (`event=request`) → `ingestion_jobs.request_id == R`
    → worker logs R (`event=worker_job_processing, family=ingestion`).
  - log-leak probe over not-found / denied / oversized-body(413) /
    rate-limited(429) / provider-failure / internal-exception(500): **0 leaks**
    against live secret values, DSN/URL shapes and internal host:ports; the 500
    path (deliberately raising a message containing `postgres:5432` and
    `postgresql://…`) logs a fingerprint only.
  - audit export two-subject: non-admin → typed **403 admin_required** with no
    export event; admin → **200** `application/x-ndjson`, checksum header equals
    `sha256(body)`, count == line count, export event present in the trail;
    inverted range → typed **400 invalid_time_range**.
  - worker metrics server binds an ephemeral port and serves the exposition.
- Impacted suites, each re-run on its own fresh DB (no regression from the
  instrumentation): `test_rag_integration` **13 passed**,
  `test_ingestion_integration` **10 passed / 2 skipped**,
  `test_documents_integration` **2 passed**, `test_limits_integration` **7 passed**,
  `test_governance_admin_integration` **8 passed**.

promtool lint (official `prom/prometheus:v2.53.2`, `--entrypoint promtool`):
```
check config /etc/prom/prometheus.yml
  SUCCESS: 1 rule files found
  SUCCESS: /etc/prom/prometheus.yml is valid prometheus config file syntax
  SUCCESS: 11 rules found (alerts.yml)
check rules /etc/prom/alerts.yml
  SUCCESS: 11 rules found
```

Ran only my integration set + the directly-impacted suites (not the full
battery — Contractor's job). No image rebuild required (all Python + committed
YAML; the api `/metrics` content is proven live through the ASGI stack in unit
tests).

## ISSUES

- When several integration suites share one DB in a single pytest run, two
  tests fail on **DB-global governance-settings pollution** (a subsequent suite
  sees `limits.*` values another suite wrote): `test_limits_integration`'s
  `test_job_capacity_admits_when_empty` (leftover non-terminal jobs) and
  `test_governance_admin_integration`'s settings-overview (bumped versions).
  This is Builder 2's documented "governance settings are DB-global and persist
  across tests" behavior, **not a regression** — each suite passes cleanly on
  its own fresh DB. Contractor: run integration suites on a fresh DB per suite
  (as I did), or accept the ordering caveat.
- Pre-existing latent flake (not mine, not in scope): `test_documents_unit.py`'s
  xlsx byte-determinism check failed ~1 run in 5 — `openpyxl` writes zip-entry
  timestamps at 2s DOS resolution, so two back-to-back renders occasionally
  straddle a boundary. Ran 264→293 passing across many runs. Fix belongs in the
  document renderer (pin `ZipInfo.date_time`); flagged for the Contractor.
- ClamAV/live-image notes from Builders 1/2 unchanged; I ran natively so they
  did not apply.

## DEVIATIONS

1. **Audit export lives at `/api/v1/audit/export`, NOT under `/api/v1/admin`.**
   The admin surface is a closed, enumerated set whose `audit` sub-path is an
   immutability boundary (`admin_truth_immutable`) — mounting a route there
   would both collide with that guard and break the exact-set
   `test_admin_surface_inventory` assertion. A read-only export on its own prefix
   is admin-gated by the same `policy.decide("manage_policies")` (Role.ADMIN),
   which is the actual gate; the URL is not the gate. No existing test changed.
2. **`prometheus-client` was already present** (pinned 0.22.1, used by
   `ingestion/metrics.py`). The handoff framed it as "add + justify + pin"; it
   was already the standard exposition lib in the tree, so I extended the
   existing default-registry pattern rather than adding a dep.
3. **DB-pool metric is refreshed, not a scrape-time custom collector** — the
   worker refreshes each loop, the api refreshes inline on `/metrics`. Cheaper
   and avoids reaching into the engine on the metrics thread; reading the pool
   never opens a connection.
4. **Audit-chain integrity is metered by a throttled worker verify** (every
   `AUDIT_VERIFY_INTERVAL_SECONDS`, default 60s) publishing `rtr_audit_chain_valid`
   — the `AuditChainVerifyFailure`/`AuditChainVerifyStale` alerts need a metric to
   fire on, and `AuditRepository.verify` scans the chain so it cannot run per
   request. This is the one place I added a periodic worker task.
5. **Cert-expiry is a genuine placeholder** (`TlsCertExpirySoon` over
   `rtr_tls_cert_expiry_timestamp_seconds`): Caddy manages cert lifetime and the
   app emits no cert metric, so the rule is lint-valid but inert until a cert
   exporter is wired (documented in `alerts.yml` + runbook `#cert-renewal`).
6. **Provider budget unit remains "provider calls"** (Builder 2's choice);
   `rtr_provider_budget_debit_units_total` counts those units, ready to migrate
   to tokens when a real provider reports usage.

## SUGGESTIONS (Builder 5 SLO wiring + Contractor verify)

**Metric names (all `rtr_`-prefixed, on the default registry):**
- HTTP: `rtr_http_request_duration_seconds{route_class,method,status}` (histogram;
  use `_bucket`/`_count` for p95 + error-rate SLOs), `rtr_http_errors_total{code,route_class}`.
- DB: `rtr_db_pool_connections{state=size|checked_in|checked_out|overflow}`.
- Provider: `rtr_provider_call_duration_seconds{provider,result}`,
  `rtr_provider_call_failures_total{provider}`,
  `rtr_provider_budget_debit_units_total`, `rtr_provider_budget_exhausted_total{scope=subject|global}`,
  `rtr_provider_breaker_open{provider}`, `rtr_provider_breaker_refusals_total{provider}`.
- Limits: `rtr_rate_limit_rejections_total{reason,route_class,scope}`.
- Jobs (worker): `rtr_job_queue_depth{family=ingestion|render|index}`,
  `rtr_job_queue_saturation_total{family}`,
  `rtr_worker_job_duration_seconds{family,result}`, `rtr_worker_jobs_total{family,result}`.
- Integrity: `rtr_audit_chain_valid`, `rtr_audit_chain_last_verified_timestamp_seconds`.
- Pre-existing (still exposed): `rtr_ingestion_*` from `ingestion/metrics.py`.
- Labels are bounded (route CLASS, not path; no subject-id/IP/object-key) — a
  unit test asserts no metric carries an unbounded/PII label.

**Alert names → runbook anchors** (`infra/observability/alerts.yml` →
`docs/runbook.md`): `HighApiErrorRate`→#high-api-error-rate,
`HighApiLatencyP95`→#high-api-latency, `JobQueueDepthHigh`/`JobQueueSaturation`→#queue-saturation,
`ProviderBreakerOpen`→#breaker-storm, `ProviderCallFailureRateHigh`→#provider-outage,
`ProviderBudgetExhaustionSpike`→#budget-exhaustion,
`AuditChainVerifyFailure`/`AuditChainVerifyStale`→#audit-chain-failure,
`TargetDown`→#service-down, `TlsCertExpirySoon`→#cert-renewal (placeholder).

**For Builder 5 (load test / SLO):** the p95 read SLO should read
`histogram_quantile(0.95, sum by (le,route_class) (rate(rtr_http_request_duration_seconds_bucket[…])))`
filtered to `route_class="files"|"documents"` (reads) vs `"ask"`; watch
`rtr_rate_limit_rejections_total` and `rtr_provider_breaker_open` engage under
fault injection with p95 staying bounded. The api `/metrics` is on port 8000
(internal), the worker on `WORKER_METRICS_PORT` (9100); scrape on the compose
network, not the ingress.

**For the Contractor:** lint with
`docker run --rm --entrypoint promtool -v "$PWD/v2/infra/observability:/etc/prom"
prom/prometheus:v2.53.2 check config /etc/prom/prometheus.yml` (and `check rules
/etc/prom/alerts.yml`). Audit export = `GET /api/v1/audit/export?start=<iso>&end=<iso>&limit=<n>`
(admin only; headers `X-Audit-Export-Checksum: sha256:…`, `X-Audit-Export-Count`,
`X-Audit-Export-Truncated`; hard cap 50k rows). Run integration suites on a
fresh DB per suite to avoid the DB-global-settings ordering caveat above.
