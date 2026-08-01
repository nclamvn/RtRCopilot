# Quotas, limits, budgets and resilience (TIP-012 Task 2)

App-layer enforcement of rate limits, request body sizes, provider cost budgets,
a per-provider circuit breaker and job backpressure. Everything here is enforced
in the API application (D-012-03) so the guarantees survive an ingress bypass and
are unit/integration testable — the ingress body cap is defence-in-depth on top,
not the only line.

Typed error codes and status: `rate_limited` (429), `body_too_large` (413),
`budget_exhausted` (429), `provider_unavailable` (503), `queue_saturated` (429),
`rate_limiter_unavailable` (503). Each carries the standard
`{"error": {code, message}, "request_id": ...}` envelope; retry-able ones add a
`Retry-After` header.

## Where each limit lives

| Concern | Configured in | Why |
|---|---|---|
| Rate-limit windows/quotas | env `Settings` (`LIMITS_RATE_*`) | Enforced in middleware on every request — the hot path must not depend on Postgres. |
| Body-size caps | env `Settings` (`LIMITS_MAX_BODY_BYTES`, `INGESTION_MAX_UPLOAD_BYTES`) + ingress `INGRESS_MAX_*` | Header-only middleware check; ingress mirrors it. |
| Circuit breaker | env `Settings` (`LIMITS_BREAKER_*`) | Resilience tuning at deploy time. |
| Cost budgets | governance `SETTING_REGISTRY` (`limits.budget.*`) | REQ-031: admin-editable at runtime, versioned, audited. |
| Job concurrency caps | governance `SETTING_REGISTRY` (`limits.jobs.*`) | Admin-editable operational tuning; checked only at submission. |

Governance settings are adjusted through the existing admin surface
(`PUT /api/v1/admin/settings/{key}`), are versioned and every change is audited.

## Default limits table (for the operator / Contractor)

### Rate limiting (Redis fixed window, keyed on subject id AND client IP)

| Class | Env var | Default (per window) | Paths |
|---|---|---|---|
| window | `LIMITS_RATE_WINDOW_SECONDS` | 60 s | (shared window) |
| `auth` | `LIMITS_RATE_AUTH_MAX` | 20 | `/auth/*` |
| `ask` | `LIMITS_RATE_ASK_MAX` | 30 | `/api/v1/ask` |
| `upload` | `LIMITS_RATE_UPLOAD_MAX` | 20 | `POST /api/v1/files/uploads*` |
| `render` | `LIMITS_RATE_RENDER_MAX` | 30 | `POST /api/v1/templates/*/render` |
| `admin` | `LIMITS_RATE_ADMIN_MAX` | 60 | `/api/v1/admin/*` |
| `default-read` | `LIMITS_RATE_DEFAULT_READ_MAX` | 120 | every other authenticated request |

`Retry-After` = seconds until the current fixed window rolls over. Both the
per-IP and per-subject windows are enforced; either tripping rejects. The client
IP is the last hop of `X-Forwarded-For` (appended by the trusted Caddy ingress);
the dev profile with no proxy falls back to the socket peer.

`LIMITS_ENABLED=false` turns the whole middleware off (not recommended).

### Body size (typed 413)

| Setting | Default | Applies to |
|---|---|---|
| `LIMITS_MAX_BODY_BYTES` | 1 MiB (1048576) | non-upload JSON bodies |
| `INGESTION_MAX_UPLOAD_BYTES` | 50 MiB (52428800) | upload endpoints |

Keep the ingress caps in sync: `INGRESS_MAX_BODY` (default `1MiB`) and
`INGRESS_MAX_UPLOAD` (default `50MiB`) in `infra/ingress/Caddyfile`. Uploads
posted through the web same-origin proxy (`/api/files/uploads` → web → api) get
the larger bound on both the api and web handles, so a small default cap cannot
break uploads through the ingress.

### Provider cost budgets (`SETTING_REGISTRY`, admin-editable)

| Key | Default | Bounds | Meaning |
|---|---|---|---|
| `limits.budget.subject_daily_units` | 500 | 1 … 1e8 | per-subject daily provider usage |
| `limits.budget.global_daily_units` | 20000 | 1 … 1e9 | global daily provider usage |

The debited **unit is a provider call** (a grounding-repair retry counts as two).
Budgets are enforced on `/api/v1/ask` before any DB write, so a breach leaves no
orphaned answer run. Counters live in Redis, keyed by UTC date, and roll over at
UTC midnight; `Retry-After` on a breach is the seconds until reset. **Persistence
assumption:** counters survive a process restart only while the Redis instance
persists (AOF or RDB). If Redis is wiped, the day's usage resets to zero — which
fails safe (never over-charges). Debits and breaches are audited
(`limits.budget.debit`, `limits.budget.exhausted`, `resource_id` NULL).

### Provider circuit breaker

| Setting | Default | Meaning |
|---|---|---|
| `LIMITS_BREAKER_FAILURE_THRESHOLD` | 5 | consecutive failures that open the breaker |
| `LIMITS_BREAKER_COOLDOWN_SECONDS` | 30 | open→half-open cooldown |

State is per-provider in Redis (shared across API replicas). While open, the
provider is not called at all — the caller returns `provider_unavailable` (503)
with `Retry-After` = cooldown remaining. After the cooldown one half-open trial
is admitted; success closes, failure re-opens. This wraps the existing per-call
`asyncio.timeout`: the timeout bounds one call's wall time, the breaker stops
making calls once a provider is unhealthy. A hung provider therefore never ties
up a request slot (proven: a 60 s hang under a 50 ms timeout returns in < 1 s).

### Job backpressure (`SETTING_REGISTRY`, admin-editable)

| Key | Default | Bounds | Family |
|---|---|---|---|
| `limits.jobs.ingestion_max_inflight` | 100 | 1 … 1e6 | ingestion uploads |
| `limits.jobs.render_max_inflight` | 50 | 1 … 1e6 | document renders |
| `limits.jobs.index_max_backlog` | 200 | 1 … 1e6 | SOT reindex backlog |

"Outstanding" = jobs not yet in a terminal state. When a family is at/over its
cap a **new submission** is refused at the API layer (`POST /uploads`,
`POST /templates/{v}/render`) with `queue_saturated` (429) +
`Retry-After = LIMITS_QUEUE_RETRY_AFTER_SECONDS` (default 15). The index family
has no direct user-facing submission API (reindex is triggered by governed,
admin-rate-limited SOT publishes and drained one-at-a-time by the single worker);
its cap is enforced worker-side, logging and auditing on the rising edge of
saturation while continuing to drain — index work is never dropped. Every shed is
audited (`ingestion.queue.shed`, `document.render.shed`, `sot.reindex.backpressure`).

## Redis-down policy (rationale)

Redis backs sessions, rate limits, budgets and the breaker. The design choice
(recorded in the completion report DEVIATIONS):

- The rate-limit **decision** is fail-closed in the normal sense: a reachable
  Redis reporting an over-limit count rejects.
- When Redis is **unreachable**, the limiter degrades to **fail-open for every
  class except `auth` in production**, which fails closed (503
  `rate_limiter_unavailable`). Non-production fails fully open so the unit suite
  (no live Redis) is unaffected.
- Budget and breaker Redis faults **fail open** (they are spend/resilience
  guards, not security controls) and are logged.

Rationale: Redis is a hard dependency — the auth login/callback flow itself
stores state in Redis, so a Redis outage already denies new authenticated
sessions at the source. Turning every request into a 503 during a transient
Redis blip would convert a soft-dependency hiccup into a self-inflicted full
outage of the ingress surface. Production auth remains fail-closed because that
is the one surface where an unbounded flood during an outage is genuinely
dangerous, and the ingress-level rate limit is the outer defence.
