# TIP-012 · Builder 2 Report — quotas, rate/body/cost limits, provider circuit breaker, job backpressure (AC-04, AC-05, AC-06, AC-07)

## STATUS

**DONE.** App-layer (D-012-03) Redis-backed rate limiting (per subject AND per
IP, 6 distinct classes, typed 429 + `Retry-After`), typed 413 body-size limits
consistent with a new ingress `request_body max_size` hook, per-subject + global
daily provider cost budgets in `SETTING_REGISTRY` (typed 429 `budget_exhausted`,
admin-editable, audited), a per-provider circuit breaker (typed 503
`provider_unavailable`, half-open recovery, proven wall-time-bounded), and job
backpressure (typed 429 `queue_saturated` + `Retry-After` at the submission API)
are all implemented, unit-tested and integration-tested against live native
infra. Baseline gates stay green; the new limit middleware never 500s a request
and fails safe when Redis is down.

## FILES CHANGED

New (app-layer limits package `v2/apps/backend/src/rtr_copilot/limits/`):
- `__init__.py`, `errors.py` (typed codes + status table + `Retry-After`
  envelope), `redis_support.py` (short-timeout client factory), `rate_limit.py`
  (fixed-window `RateLimiter`), `budget.py` (`CostBudget`, UTC daily rollover),
  `breaker.py` (`CircuitBreaker`, `ProviderUnavailable`), `backpressure.py`
  (`QueueSaturated`, `check_capacity`/`outstanding_count`), `settings_access.py`
  (governed int-setting reader, deferred import to avoid a cycle), `middleware.py`
  (`apply_limits` decision + `install_limits_middleware`, classification, client-IP
  resolution, best-effort de-duplicated audit).
- `v2/apps/backend/tests/test_limits_unit.py` — 27 unit tests (fakes only).
- `v2/apps/backend/tests/test_limits_integration.py` — 7 integration tests (live
  Postgres + Redis, ASGITransport, skip-marked on `INTEGRATION_DATABASE_DSN`).
- `v2/docs/limits.md` — operator guide (defaults table, Redis-down policy, budget
  persistence assumption, ingress/app 413 consistency).

Modified:
- `config.py` — env `Settings`: `limits_enabled`, `limits_rate_window_seconds`,
  six `limits_rate_*_max`, `limits_max_body_bytes`, `limits_breaker_*`,
  `limits_queue_retry_after_seconds` (all bounded `Field`s).
- `api/main.py` — register the limits middleware INSIDE the request-context
  middleware; request-context now reuses an existing `request.state.request_id`.
- `governance/service.py` — 5 new `SETTING_REGISTRY` entries (`limits.budget.*`,
  `limits.jobs.*`), typed/bounded/versioned/audited via the existing surface.
- `governance/api.py` — extended `STATUS_BY_CODE` with the 6 limit codes.
- `rag/answering.py` — `ask` gated by `_enforce_budget` (before any DB write);
  provider call wrapped by `_guarded_generate` (breaker allow → existing
  `asyncio.timeout` repair loop → success/failure record → honest usage debit);
  debits + breaches audited (`resource_id` NULL, ids in details).
- `rag/api.py` — `/ask` catches `BudgetExhausted`→429, `ProviderUnavailable`→503.
- `ingestion/api.py` — `POST /uploads` capacity guard (ingestion family) → 429
  `queue_saturated` + `Retry-After`, audited.
- `documents/api.py` — `POST /templates/{v}/render` capacity guard (render family).
- `worker/main.py` — rising-edge index-backlog backpressure audit/log per loop.
- `infra/ingress/Caddyfile` — `request_body max_size` hooks (only Builder-1 touch
  authorized): `{$INGRESS_MAX_BODY:1MiB}` on general handles,
  `{$INGRESS_MAX_UPLOAD:50MiB}` on `/api/v1/files/uploads*` (api) AND
  `/api/files/uploads*` (web proxy path). `caddy validate` → **Valid configuration**.
- `.env.example` — `INGRESS_MAX_BODY/UPLOAD` + the `LIMITS_*` block, documented.
- `tests/test_governance_service_unit.py`, `tests/test_governance_admin_integration.py`
  — updated the two exact-set registry assertions to include the 5 new keys
  (+ added bound/type coverage). Additive, reflecting the grown registry.

## TEST RESULTS

Before → after (unit, `uv run ruff check . && uv run mypy && uv run pytest`):
- ruff: PASS → PASS
- mypy: 83 files → **92 files** (9 new `limits/` modules), strict PASS
- pytest unit: **237 passed / 90 skipped → 264 passed / 97 skipped**
  (+27 `test_limits_unit.py`; +7 integration tests skipped without a DSN)

Integration (live native infra — Postgres :5432 fresh DB migrated to head,
Redis :6380, MinIO :9002 bucket `rtr-test`):
- `test_limits_integration.py`: **7 passed** (re-run twice, deterministic).
  Proves: real 429 per class + `Retry-After` through the ASGI stack; two-caller
  isolation; app-layer 413 (before auth); budget breach 429 `budget_exhausted`
  on `/ask` with subject isolation (bystander → honest-null 200) and the breach
  audited; a 60 s-hung provider under a 50 ms timeout returning in < 1 s then the
  breaker opening to an immediate 503 (no further call made); a failing provider
  opening the breaker across asks; real DB-backed job-cap admit/shed.
- Regression (fresh DB, my changed paths): `test_rag_integration` +
  `test_ingestion_integration` + `test_documents_integration` → **25 passed /
  2 skipped**; `test_governance_admin_integration` → **8 passed** (after the
  registry-set assertion update). No regression from the budget/breaker wrap or
  the backpressure guards.

Ran only my integration set + the directly-impacted suites (not the full
battery — Contractor's job). No image rebuild was required (all changes are
Python + Caddyfile; unit/integration run natively).

## ISSUES

- Governance settings are DB-global and persist across tests; budget-sensitive
  integration tests therefore set the budget they need at their start (helper
  `_set_int_setting`). An unfiltered `/ask` in a shared DB can match leftover
  indexed evidence, so the budget test's bystander scopes to a non-existent
  `source_key` for a deterministic honest-null. Both are test-hygiene fixes, not
  product issues.
- `caddy` is not installed natively in this sandbox; validated the Caddyfile via
  `docker run caddy:2.11.4 caddy validate` (→ Valid). Docker Hub reachable.

## DEVIATIONS

1. **Redis-down policy (recorded per instruction).** The rate-limit *decision*
   is fail-closed in the normal sense (reachable Redis over-limit → 429). When
   Redis is *unreachable* the limiter **fails open for every class except `auth`
   in production**, which fails closed (503 `rate_limiter_unavailable`);
   non-production fails fully open. Budget/breaker Redis faults fail open (spend
   / resilience, not security). Rationale: Redis is a hard dependency — the auth
   login/callback flow itself stores state in Redis, so an outage already denies
   new sessions at the source; turning every request into a 503 on a transient
   blip would be a self-inflicted full outage. Production auth stays fail-closed
   because that is the one surface where an unbounded outage-time flood is truly
   dangerous, backed by the ingress-level limit. Full text in `docs/limits.md`.
2. **Where limits live.** Task 7 says "each limit in `SETTING_REGISTRY`". I split
   it: **cost budgets and job caps** are in `SETTING_REGISTRY` (admin-editable at
   runtime, low-frequency reads — REQ-031 mandates this for budgets), but
   **rate-limit windows/quotas and body-size caps** are bounded env `Settings`.
   Reason: they are enforced in middleware on *every* request; a per-request
   Postgres read for config would itself be a DoS vector and couple the hot path
   to the DB (defeating the Redis-backed independence D-012-03 requires). All are
   still "configurable with safe bounded defaults", documented in `.env.example`.
3. **Budget unit = provider call**, not token estimate ("keep simple"). A
   grounding-repair retry counts as two. Swappable to tokens once a real provider
   reports usage (Builder 3 handoff below).
4. **Budget gated at the top of `ask`** (before any DB write) so a breach never
   leaves an orphaned `answer_run`. Consequence: once a subject's daily cap is
   reached, even an evidence-free question is refused (a "you're locked out for
   the day" posture) rather than returning a free honest-null. Deemed correct for
   a spend cap.
5. **Index-family backpressure has no user-facing submission API** (reindex is
   triggered by governed, admin-rate-limited SOT publishes and drained
   one-at-a-time by the single-consumer worker — already bounded, not unbounded).
   Its cap (`limits.jobs.index_max_backlog`) is enforced worker-side: on the
   rising edge of saturation the worker logs + audits `sot.reindex.backpressure`
   and keeps draining (never drops). Ingestion + render (which *have* submission
   APIs) get the typed-429-at-submission treatment.
6. **The rate-limit middleware catches any exception** (not just `RedisError`) in
   its Redis-dependent section and applies the fail policy. Required because the
   existing test suite monkeypatches the *shared* `redis.asyncio.Redis` class, so
   operation-specific fakes (e.g. the ping/auth fakes lacking `expire`) leak into
   the middleware — a limiter must never turn that into a 500. The error type is
   logged; classification and body checks stay outside the guard so real bugs
   there still surface.
7. **Two existing exact-set assertions updated** (`test_governance_service_unit`,
   `test_governance_admin_integration`) to include the 5 new registry keys, plus
   `request_context` made request-id-idempotent. Additive; no behavior change.

## SUGGESTIONS

### Limit-defaults table (for the Contractor)

| Limit | Setting | Default | Bounds |
|---|---|---|---|
| rate window | `LIMITS_RATE_WINDOW_SECONDS` | 60 s | 1…3600 |
| rate: auth / ask / upload / render / admin / default-read | `LIMITS_RATE_*_MAX` | 20 / 30 / 20 / 30 / 60 / 120 | 1…1e6 |
| body (JSON) | `LIMITS_MAX_BODY_BYTES` | 1 MiB | ≥1024 |
| body (upload) | `INGESTION_MAX_UPLOAD_BYTES` | 50 MiB | ≥1 MiB |
| ingress body / upload | `INGRESS_MAX_BODY` / `INGRESS_MAX_UPLOAD` | `1MiB` / `50MiB` | Caddy size |
| breaker threshold / cooldown | `LIMITS_BREAKER_*` | 5 / 30 s | 1…1000 / 1…3600 |
| queue Retry-After | `LIMITS_QUEUE_RETRY_AFTER_SECONDS` | 15 s | 1…3600 |
| budget subject / global daily | `limits.budget.*_daily_units` (SETTING_REGISTRY) | 500 / 20000 | 1…1e8 / 1…1e9 |
| job caps ingestion / render / index | `limits.jobs.*` (SETTING_REGISTRY) | 100 / 50 / 200 | 1…1e6 |

Run my integration set with: fresh DB migrated to head, `INTEGRATION_DATABASE_DSN`
+ `POSTGRES_DSN` = runtime dsn, `REDIS_URL=redis://localhost:6380/0`,
`S3_*` → MinIO :9002 bucket `rtr-test`,
`SOT_SIGNING_SECRET=test-only-dedicated-sot-signing-secret-32bytes`.

### Builder 3 (observability) should meter
Audit actions ready to scrape into counters/histograms: `limits.rate.rejected`
(labels: class, scope), `limits.body.rejected`, `limits.budget.debit`
(units/totals) + `limits.budget.exhausted` (scope), `limits.breaker.open`
(provider), `ingestion.queue.shed` / `document.render.shed` /
`sot.reindex.backpressure` (family, outstanding, cap). Add a token-estimate
gauge alongside the call-count budget so the budget unit can migrate to tokens.
`docs/limits.md` lists the typed codes to bucket error counts by. Note: the
current budget/breaker/queue events are audited, not yet Prometheus-exposed.

### Builder 5 (load test) should exercise
429s appearing exactly at the configured thresholds with no 5xx storm (steady
mixed read + ask burst); breaker engaging under provider fault injection and
freeing request slots (p95 stays bounded despite a hung provider); queue
saturation returning 429 not silent growth. Perf note for the SLO: each rate-
limited request opens/closes a fresh Redis client (matches the app-wide
per-request pattern, ~sub-ms up, ~6 ms fast-fail when down) — a shared pool is a
p95 optimization if the limiter shows up in the tail. Test through the hardened
ingress to also cover the `request_body` caps (413) end-to-end.
