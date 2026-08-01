# RtR Copilot v2 — Incident Runbook

Operator playbooks for the compose deployment (Blueprint §3: Docker Compose on a
private Linux VM behind the Caddy HTTPS ingress, VPN/LAN only). Each playbook is
one screen, names the **alert** that pages it (see
`infra/observability/prometheus.yml` + `infra/observability/alerts.yml`), and
uses **real** commands. Metrics are defined in
`apps/backend/src/rtr_copilot/observability/metrics.py`.

## Orientation

- **Metrics.** The api exposes `/metrics` on its internal app port (`8000`); the
  worker on `WORKER_METRICS_PORT` (default `9100`). Neither is routed through the
  ingress — scrape on the compose network only. Prometheus config +
  alert rules are committed under `infra/observability/`. Lint them with the
  official container:
  ```
  docker run --rm --entrypoint promtool \
    -v "$PWD/infra/observability:/etc/prom" prom/prometheus:v2.53.2 \
    check config /etc/prom/prometheus.yml
  ```
- **Reach a service (compose):** `make ps` · `make logs` ·
  `docker compose exec <api|worker|postgres|redis> …`. Hardened stack:
  `make hardened-up` / `make hardened-down`; readiness via
  `scripts/wait-ready-hardened.sh`.
- **SLO thresholds** live in `docs/slo.md` (Builder 5). The alert thresholds
  here are the paging tripwires, not the SLO itself.
- **First 60 seconds of any page:** confirm the target is up
  (`up{job=~"rtr-.*"}`), skim `make logs`, and check whether a deploy just
  happened (`docker compose images`).

---

## High API error rate

**Alert:** `HighApiErrorRate` (5xx ratio > 5% for 5m).

1. Scope it: `sum by (route_class) (rate(rtr_http_errors_total{code="internal_error"}[5m]))`
   shows which class is 5xx-ing; `rtr_http_request_duration_seconds_count{status=~"5.."}`
   confirms.
2. Correlate with dependencies: is `ProviderCallFailureRateHigh` or
   `TargetDown` also firing? If a provider is the cause, follow
   [Provider outage](#provider-outage); if the worker is down, follow
   [Service down](#service-down).
3. Check the DB pool: `rtr_db_pool_connections{state="checked_out"}` at/over
   `size`+`overflow` means pool exhaustion — restart the api
   (`docker compose restart api`) and investigate a slow query.
4. Logs are leak-safe by design (fingerprints only). Use the request-id from a
   failing client response (`X-Request-ID`) to grep the structured logs.
5. If a bad deploy is implicated, go to [Rollback](#rollback).

---

## High API latency

**Alert:** `HighApiLatencyP95` (api p95 > 1.5s for 10m).

1. Localize: `histogram_quantile(0.95, sum by (le,route_class)
   (rate(rtr_http_request_duration_seconds_bucket[5m])))`.
2. If the `ask` class dominates, check `rtr_provider_call_duration_seconds` —
   provider slowness. The breaker bounds a hung provider; see
   [Breaker storm](#breaker-storm).
3. If reads are slow, check DB pool saturation
   (`rtr_db_pool_connections`) and queue pressure
   (`rtr_job_queue_depth`) — a saturated worker starves shared DB capacity.
4. Confirm rate limiting isn't masking a flood: `rtr_rate_limit_rejections_total`.
5. Mitigate: scale the worker cap settings down to shed load, or restart the
   hottest service. Record the incident window for the SLO review.

---

## Provider outage

**Alert:** `ProviderCallFailureRateHigh` (failures > 0.2/s for 5m); often
precedes `ProviderBreakerOpen`.

1. Confirm blast radius: `sum by (provider) (rate(rtr_provider_call_failures_total[5m]))`.
   Ask returns typed `honest_null`/503 — it never hangs (timeout + breaker are
   proven in `test_limits_integration`).
2. The breaker will open automatically after
   `LIMITS_BREAKER_FAILURE_THRESHOLD` consecutive failures, sparing request
   slots. Watch `rtr_provider_breaker_open`.
3. If the provider is externally down, no app action recovers it — communicate
   degraded ask, keep serving grounded reads.
4. On recovery the breaker half-opens after
   `LIMITS_BREAKER_COOLDOWN_SECONDS`; a successful trial closes it
   (`rtr_provider_breaker_open` → 0). No restart required.
5. If failures are actually timeouts from a slow (not down) provider, consider
   raising `RAG_PROVIDER_TIMEOUT_SECONDS` only after confirming it will not
   re-introduce slot exhaustion.

---

## Breaker storm

**Alert:** `ProviderBreakerOpen` (breaker open ≥ 5m).

1. The breaker being open is the *correct* protective state under provider
   failure — do not force it closed. Confirm the underlying cause via
   [Provider outage](#provider-outage).
2. Inspect shared breaker state directly:
   `docker compose exec redis redis-cli --scan --pattern 'rtr:cb:*'`.
3. A genuine false-positive (provider healthy, breaker stuck) is cleared by
   letting the cooldown elapse, or, as a deliberate operator action, deleting
   the breaker keys: `redis-cli del rtr:cb:<provider>:failures rtr:cb:<provider>:opened_at`.
   Only do this if you have independently confirmed provider health.
4. If storms recur, the threshold/cooldown
   (`LIMITS_BREAKER_*`) may be mistuned for a flaky provider — adjust and note
   the change.

---

## Budget exhaustion

**Alert:** `ProviderBudgetExhaustionSpike` (> 5 `budget_exhausted` in 15m).

1. Identify scope: `sum by (scope) (increase(rtr_provider_budget_exhausted_total[1h]))`
   — `subject` (one runaway caller) vs `global` (system-wide cap hit).
2. Budgets are admin-editable governance settings, not env vars. Review current
   values and versions:
   `GET /api/v1/admin/settings` (admin session) or query
   `governance_settings` for `limits.budget.subject_daily_units` /
   `limits.budget.global_daily_units`.
3. If demand is legitimate, raise the cap via the settings API
   (`PUT /api/v1/admin/settings/limits.budget.global_daily_units`) — the change
   is versioned and audited.
4. If a single subject is abusing spend, keep the per-subject cap and follow up
   out-of-band; usage counters reset at UTC midnight
   (`rtr:budget:*` keys in Redis carry a TTL to just past midnight).

---

## Queue saturation

**Alerts:** `JobQueueDepthHigh` (depth > 100 for 10m) and `JobQueueSaturation`
(submissions shed at the cap).

1. Which family? `max by (family) (rtr_job_queue_depth)` and
   `increase(rtr_job_queue_saturation_total[10m])` (ingestion / render / index).
2. Confirm the worker is alive and draining: `up{service="worker"}`,
   `make logs` (worker heartbeat), and job throughput
   `rate(rtr_worker_jobs_total[5m])`.
3. If the worker is wedged, restart it: `docker compose restart worker`. Jobs
   are durable (outbox + lease reclaim), so in-flight work resumes.
4. Over-cap submissions correctly return typed 429 `queue_saturated` with
   `Retry-After` — clients back off; this is backpressure, not data loss.
5. If depth is structural (real demand), raise the family cap in governance
   settings (`limits.jobs.*`) after confirming the worker can keep up.

---

## Audit-chain failure

**Alert:** `AuditChainVerifyFailure` (`rtr_audit_chain_valid == 0`);
`AuditChainVerifyStale` if the gauge stops refreshing.

1. **Treat as a potential integrity incident.** The worker re-verifies the
   append-only hash-chain every `AUDIT_VERIFY_INTERVAL_SECONDS` and publishes
   `rtr_audit_chain_valid`.
2. Reproduce out-of-band with the same verifier the app uses
   (`AuditRepository.verify`) or `make db-verify` (`scripts/verify-database.sh`),
   which checks audit invariants against the live DB.
3. The DB enforces append-only at the storage layer (update/delete/truncate
   triggers on `audit_events` + anchor protection). A verify failure means
   either a chain gap or hash mismatch — capture the failing sequence from the
   verifier output.
4. Preserve evidence: do **not** mutate `audit_events`. Snapshot the DB
   (`make backup`) before any remediation and escalate to the Homeowner —
   audit integrity is a governance decision, not an operator fix.
5. If `AuditChainVerifyStale` fires alone (gauge frozen, chain not proven bad),
   the worker is likely down — see [Service down](#service-down).

---

## Service down

**Alert:** `TargetDown` (`up{job=~"rtr-.*"} == 0` for 2m).

1. Which target? The alert labels carry `job`/`service` (api or worker).
2. `make ps` and `make logs`; a crash-loop shows in the restart count.
3. Common causes: a fail-closed config boot (production secret guard — check
   for a `configuration_rejected` log), a dependency down (postgres/redis/minio
   health), or an OOM.
4. Restart the single service: `docker compose restart <api|worker>`. Full
   stack: `make hardened-down && make hardened-up`, then
   `scripts/wait-ready-hardened.sh`.
5. If it will not boot after a recent release, go to [Rollback](#rollback).

---

## Restore

**Trigger:** data loss / corruption; RPO/RTO drill (`make restore-drill`).

1. Backups are produced by `scripts/backup-data.sh` (`make backup`) — Postgres
   dump + MinIO object sync, timestamped.
2. Run the restore into a scratch DB/bucket first:
   `scripts/restore-data.sh` (driven by `make restore-drill`). It restores the
   dump, re-syncs objects, and passes the existing **RESTORE PASS** integrity
   gate (`scripts/verify-data-integration.sh`).
3. RPO = time since the last successful backup (backup cadence). RTO =
   wall-clock of the restore drill; both are recorded in `docs/slo.md`
   (Builder 5).
4. For a real restore, stop writers first (`make hardened-down` or scale the
   api/worker to zero), restore into the live DB/bucket, run
   `make db-verify`, then bring services back and
   `scripts/wait-ready-hardened.sh`.
5. After restore, expect `AuditChainVerifyFailure` to clear on the next worker
   verify cycle; confirm `rtr_audit_chain_valid == 1`.

---

## Rollback

**Trigger:** a bad release; often paged as `HighApiErrorRate` or `TargetDown`
right after a deploy.

1. Rollback returns to the **previous image tag** and NEVER auto-downgrades the
   schema (D-012-07). Intended entrypoint: `scripts/rollback.sh` (delivered by
   Builder 4). Until then, the manual equivalent below applies.
2. Identify the previous good version (`docker compose images`, deploy log).
3. Pin the previous tag and bring the stack up:
   set the image tag env for api/web/worker to the last good SHA, then
   `make hardened-up` and `scripts/wait-ready-hardened.sh`.
4. **Schema posture (manual decision):** if the bad release ran a forward
   migration, rolling code back does *not* revert it. Confirm the previous code
   is compatible with the current head (`make migration-check`). A schema
   downgrade is a Homeowner decision, executed separately — never as a rollback
   side effect.
5. Verify health: `up{job=~"rtr-.*"} == 1`, error rate back under threshold,
   and a smoke of the auth flow through the ingress (`make hardened-probe`).

---

## Cert renewal

**Alert:** `TlsCertExpirySoon` (placeholder — inert until a TLS cert exporter
feeds `rtr_tls_cert_expiry_timestamp_seconds`; D-012-05).

1. TLS is terminated at the Caddy ingress (`infra/ingress/Caddyfile`). In the
   default hardened profile Caddy uses its **internal CA** and rotates certs
   automatically — no operator action.
2. With **real certificates** (`INGRESS_TLS_MODE` configured, certs mounted at
   `infra/ingress/certs/`), renewal is: drop the new cert/key in that mount and
   reload the ingress: `docker compose exec ingress caddy reload
   --config /etc/caddy/Caddyfile`.
3. Verify: `curl --cacert <root> -sI https://$INGRESS_HOST/` returns 200 with a
   fresh `Not After`, or `make hardened-probe`.
4. Set HSTS max-age to ≥ 1 year only once real certs and renewal are proven
   (`INGRESS_HSTS_MAX_AGE`); the dev default is 7 days.
5. When a cert exporter is added, wire it into
   `infra/observability/prometheus.yml` so `TlsCertExpirySoon` becomes live.
