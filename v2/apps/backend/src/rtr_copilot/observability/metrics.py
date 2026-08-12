"""Prometheus metric definitions for the api and worker (TIP-012 Task 3, AC-08).

Every metric lives on the default ``prometheus_client`` registry so the api's
``/metrics`` route (internal port, never routed through the ingress) and the
worker's dedicated metrics HTTP server expose them without extra wiring. Both
run single-process (uvicorn without ``--workers``, one worker loop), so the
default in-memory registry is correct — no multiprocess collector needed.

Label-cardinality discipline (AC-08): labels are bounded, finite sets only —
a route *class* (never a raw path or id), a bounded HTTP status, a job family,
a provider name, a limit reason. No subject id, object key, IP or other
unbounded/PII value is ever a label (that would be both a cardinality bomb and
a privacy leak). Values that must be observed per-request stay in structured
logs, not in metric labels.
"""

from prometheus_client import Counter, Gauge, Histogram

# --------------------------------------------------------------------------- #
# HTTP surface (api process)
# --------------------------------------------------------------------------- #
#: Latency of every served request, bucketed for p95/p99 alerting. Labelled by
#: the bounded route class, method and numeric status — not the raw path.
HTTP_REQUEST_DURATION = Histogram(
    "rtr_http_request_duration_seconds",
    "API HTTP request latency by route class, method and status.",
    ("route_class", "method", "status"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)
#: Count of responses carrying a typed error envelope, keyed by the machine
#: code (``not_found``, ``validation_error``, ``internal_error``, ``rate_limited``…)
#: and route class. This is the "error counts by typed code" line of the AC.
HTTP_ERRORS = Counter(
    "rtr_http_errors_total",
    "API responses carrying a typed error code, by code and route class.",
    ("code", "route_class"),
)

# --------------------------------------------------------------------------- #
# Database connection pool (api + worker)
# --------------------------------------------------------------------------- #
#: SQLAlchemy async engine pool occupancy, refreshed at scrape time. ``state``
#: is one of size / checked_in / checked_out / overflow.
DB_POOL_CONNECTIONS = Gauge(
    "rtr_db_pool_connections",
    "SQLAlchemy async engine pool connections by state.",
    ("state",),
)

# --------------------------------------------------------------------------- #
# Provider calls, cost budget and circuit breaker (api process, ask path)
# --------------------------------------------------------------------------- #
PROVIDER_CALL_DURATION = Histogram(
    "rtr_provider_call_duration_seconds",
    "AI provider answer-call latency, by provider and outcome.",
    ("provider", "result"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)
# TIP-033: end-user latency is not equivalent to provider latency. These
# bounded milestones expose time-to-first-useful evidence and final readiness
# without user/query labels or any content-bearing observation.
ASK_STREAM_MILESTONE_DURATION = Histogram(
    "rtr_ask_stream_milestone_duration_seconds",
    "Ask SSE wall time to a bounded, content-free milestone.",
    ("milestone",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 25.0, 45.0, 60.0),
)
PROVIDER_CALL_FAILURES = Counter(
    "rtr_provider_call_failures_total",
    "AI provider calls that raised or timed out, by provider.",
    ("provider",),
)
# TIP-014RE: query-path embedding failures degrade retrieval to lexical-only
# instead of failing the question; the degrade must stay observable.
EMBEDDING_QUERY_DEGRADED = Counter(
    "rtr_embedding_query_degraded_total",
    "Ask/search requests that fell back to lexical-only retrieval because "
    "the provider embedding call failed or timed out, by embedding model.",
    ("model",),
)
PROVIDER_BUDGET_DEBIT_UNITS = Counter(
    "rtr_provider_budget_debit_units_total",
    "Provider cost-budget units debited across all subjects.",
)
PROVIDER_INPUT_TOKENS = Counter(
    "rtr_provider_input_tokens_total",
    "Actual AI provider input tokens, including cached input tokens.",
)
PROVIDER_CACHED_INPUT_TOKENS = Counter(
    "rtr_provider_cached_input_tokens_total",
    "Actual AI provider cached input tokens.",
)
PROVIDER_OUTPUT_TOKENS = Counter(
    "rtr_provider_output_tokens_total",
    "Actual AI provider output tokens, including reasoning tokens.",
)
PROVIDER_REASONING_TOKENS = Counter(
    "rtr_provider_reasoning_tokens_total",
    "Actual AI provider reasoning tokens included in output usage.",
)
PROVIDER_BUDGET_EXHAUSTED = Counter(
    "rtr_provider_budget_exhausted_total",
    "Provider budget-exhaustion refusals, by breached scope (subject|global).",
    ("scope",),
)
#: Last-known circuit-breaker state observed by THIS process (1 open, 0 closed).
#: Authoritative state is shared in Redis; this reflects the most recent
#: decision seen locally, which is what a per-replica alert wants.
PROVIDER_BREAKER_OPEN = Gauge(
    "rtr_provider_breaker_open",
    "Circuit breaker open (1) / closed (0), by provider.",
    ("provider",),
)
PROVIDER_BREAKER_REFUSALS = Counter(
    "rtr_provider_breaker_refusals_total",
    "Requests refused because the provider breaker was open, by provider.",
    ("provider",),
)

# --------------------------------------------------------------------------- #
# Rate / body limits (api process, middleware)
# --------------------------------------------------------------------------- #
RATE_LIMIT_REJECTIONS = Counter(
    "rtr_rate_limit_rejections_total",
    "App-layer limit rejections, by reason, route class and scope.",
    ("reason", "route_class", "scope"),
)

# --------------------------------------------------------------------------- #
# Jobs / queues (worker process)
# --------------------------------------------------------------------------- #
#: Outstanding (non-terminal) jobs per family — the queue-depth signal.
JOB_QUEUE_DEPTH = Gauge(
    "rtr_job_queue_depth",
    "Outstanding (non-terminal) jobs by family.",
    ("family",),
)
JOB_QUEUE_SATURATION = Counter(
    "rtr_job_queue_saturation_total",
    "Job submissions/backlog shed or flagged at the family cap, by family.",
    ("family",),
)
#: Wall-clock duration of a worker job, by family and terminal result.
JOB_DURATION = Histogram(
    "rtr_worker_job_duration_seconds",
    "Worker job processing duration by family and result.",
    ("family", "result"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)
JOBS_PROCESSED = Counter(
    "rtr_worker_jobs_total",
    "Worker jobs processed by family and result.",
    ("family", "result"),
)

# --------------------------------------------------------------------------- #
# Integrity (worker process, throttled)
# --------------------------------------------------------------------------- #
#: 1 when the append-only audit hash-chain verifies end to end, 0 on any
#: tampering/gap. The worker re-verifies on a slow cadence and publishes the
#: result; the ``AuditChainVerifyFailure`` alert fires on 0.
AUDIT_CHAIN_VALID = Gauge(
    "rtr_audit_chain_valid",
    "Append-only audit hash-chain verifies end to end (1) or not (0).",
)
#: Timestamp of the last successful chain verification, for staleness checks.
AUDIT_CHAIN_LAST_VERIFIED = Gauge(
    "rtr_audit_chain_last_verified_timestamp_seconds",
    "Unix time of the last audit-chain verification run.",
)
