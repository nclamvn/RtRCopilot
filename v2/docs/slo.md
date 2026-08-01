# RtR Copilot V2 — Service Level Objectives (local reference stack)

**Status of this document:** targets declared FIRST (D-012-08 — "targets first,
numbers second, no post-hoc goalposts"). The [Measured baseline](#measured-baseline)
section is filled in only AFTER the load run and the recovery drills; the target
table above it is committed in a separate, earlier commit than the numbers.

**Scope.** These SLOs apply to the **hardened local reference stack** — Docker
Compose on a single Linux host, TLS ingress (Caddy) fronting web + API, the
**fake/offline provider** (`RAG_PROVIDER_MODE=local`, `OfflineExtractiveAnswer`
+ `OfflineHashEmbedding` — deterministic, no external network, no provider
spend). They are the acceptance evidence for AC-13/AC-14. A production
re-baseline on real hardware, real certificates and a real provider is
**TIP-013+** (D-012-08); do not read these numbers as a production SLA.

**How load is driven.** k6 (official `grafana/k6` container, digest-pinned)
drives traffic **through the ingress** (`https://rtr.local`), i.e. the full
Caddy → app path including TLS, security headers, request-id middleware, the
Redis-backed rate limiter and the body-size guard. Auth is a real dev-OIDC
session obtained through the ingress (see [`load/README.md`](../load/README.md)).

---

## 1. Latency & error targets (declared before the run)

| # | SLO | Metric (k6) | Target | Load envelope (default) |
|---|-----|-------------|--------|--------------------------|
| S1 | Authenticated **read** latency | `read_duration` p95 | **≤ 300 ms** | mixed `files`+`gaps`+`dashboard`, steady |
| S2 | **Ask** latency (fake provider) | `ask_duration` p95 | **≤ 1500 ms** | grounded + honest-null ask burst |
| S3 | **Upload-accept** latency (1 MB) | `upload_duration` p95 | **≤ 2000 ms** | 1 MB streamed `POST /uploads` (202) |
| S4 | **Error rate** at target load | `errors` (custom Rate) | **< 0.5 %** | all SLO scenarios (S1–S3, spike) |
| S5 | **Availability** (functional) | `avail_ok` (Rate) | **≥ 99 %** | 1 rps `GET /api/status` probe |
| S6 | **Spike recovery** | `read_duration` p95 during+after | **≤ 300 ms after recovery**, errors < 0.5 % | ramp to spike, then back down |

### Definitions

- **read / ask / upload_duration** are custom k6 `Trend` metrics recording the
  wall-clock of the HTTP request as seen by the client, through the ingress.
  p95 is read from k6's `--summary-export` JSON (`metrics.<name>."p(95)"`).
- **error** (`errors` Rate) = any happy-path request that did **not** return its
  expected status (read → 200, ask → 200, upload → 202, status → 200), OR any
  HTTP `5xx`. In the SLO scenarios the rate limits are raised (see below) so a
  `429` is itself counted as an error — it must not happen there. The dedicated
  `rate_limit_probe` scenario is the ONLY place a `429` is the desired outcome,
  and it is **excluded** from S4.
- **availability probe** = `GET https://rtr.local/api/status` (unauthenticated,
  leak-safe aggregate `{ok,status,request_id}`) returning HTTP 200 within 1 s.
  Availability over a run = passing probes / total probes. This is a **functional
  liveness** objective for a **single-node** stack (no redundancy); it is not an
  uptime SLA. HA / multi-node availability is out of scope (TIP-013).

### Target rationale (validated from the TIP's suggested starting points)

- **S1 read ≤ 300 ms (kept).** A read is a Redis session lookup + one
  policy-scoped Postgres query + the per-request limiter round-trip. Expected
  typical latency is tens of ms on a warm local stack; 300 ms p95 leaves headroom
  for GC/JIT pauses and the fresh-Redis-client-per-request pattern Builder 2
  documented (~sub-ms up).
- **S2 ask ≤ 1500 ms (kept).** The fake provider is effectively instantaneous;
  ask latency is dominated by hybrid retrieval (pgvector similarity + lexical
  scan) plus 4–7 serialized DB writes (conversation, message, answer_run,
  citations/gap, audit). 1.5 s p95 covers the grounded path with grounding-verify.
- **S3 upload-accept ≤ 2000 ms (kept).** Accept = stream receive + **ClamAV
  clamd scan of the 1 MB body** + MinIO put + `upload_session`/`ingestion_job`
  insert + audit, returning `202`; the heavy parse/rendition work is async in the
  worker and NOT in this number. The clamd scan is the dominant term.
- **S4 error < 0.5 % (kept).** A hardened stack under its intended load must not
  emit `5xx`; limit rejections are typed `429/413`, not errors, and are proven
  separately.
- **S5 availability ≥ 99 % (added definition).** Made concrete as a status-probe
  success ratio so it is machine-checkable, with the single-node caveat stated.

### Rate limits during the SLO measurement (documented, not a goalpost move)

The Redis rate limiter (Builder 2) keys per **subject AND per client IP**. A k6
run is one dev-OIDC subject from one source IP, so at default per-IP quotas
(`default-read` 120/min, `ask` 30/min, `upload` 20/min) a single load generator
would be throttled long before it could stress the server — the limiter, not the
server, would set the p95. For the **latency** scenarios (S1–S3, S6) the numeric
rate quotas are therefore raised via an additive `compose.load.yaml` override
(the limiter still runs on every request, so its per-request cost is still
measured — only the reject threshold is lifted). Enforcement at the **configured
default thresholds** is proven independently and un-raised by the
`rate_limit_probe` scenario (§2 below) and by Builder 2's integration tests. This
is a measurement-harness setting, not a relaxation of the shipped defaults.

---

## 2. Resilience-under-load targets (declared before the run)

| # | Behaviour | Expectation |
|---|-----------|-------------|
| R1 | **Rate limit under load** | Driving one class past its **configured** threshold returns typed `429` + `Retry-After` starting at the limit; **zero `5xx`**; requests below the limit still succeed. |
| R2 | **Breaker under provider fault** | Injected consecutive provider failures open the circuit breaker (typed `503 provider_unavailable`, half-open recovery); a hung provider is **timeout-bounded** (wall time < 1 s at a 50 ms timeout); request slots are freed (no 5xx storm, no thread pinning). |

R1 is driven through the ingress with default limits (`rate_limit_probe`). R2 is
driven at the integration layer through Builder 2's fake-failure hook
(`FailingProvider` / `HangingProvider` against live Redis + Postgres) because the
shipped stack has no runtime "make the provider fail" toggle (the fake provider
never fails) — see the report's DEVIATIONS. Both map to Builder 3's metrics
`rtr_rate_limit_rejections_total` and `rtr_provider_breaker_open`.

---

## 3. Recovery objectives (RPO / RTO — measured in the drills)

| # | Objective | Definition | Target (local ref) |
|---|-----------|------------|--------------------|
| C1 | **RTO — restore** | Wall-clock of `scripts/restore-data.sh` to a clean isolated target that passes the RESTORE PASS gate | ≤ 5 min |
| C2 | **RPO — restore** | Worst-case data-loss window = backup cadence; the drill demonstrates it with a post-backup marker delta (rows written after the backup are absent from the restored copy) | = backup cadence (assumption stated in baseline) |
| C3 | **RTO — rollback** | Wall-clock of `scripts/deploy.sh` → `scripts/rollback.sh` returning the previous version with the through-ingress health gate green | ≤ 3 min |

RPO is bounded by **how often `backup-data.sh` runs**, not by the restore
mechanics: any write committed after the last successful backup and before the
next one is lost on a restore-from-backup. The drill states the assumed cadence
and proves the window empirically with timestamped marker rows.

---

## Measured baseline

> Filled AFTER the run/drills (separate commit from the targets above). Until
> then this section reads `PENDING`.

**Status:** PENDING — awaiting the load run and recovery drills.

### M1 · Load results (per scenario)
_PENDING_

### M2 · SLO evaluation (`scripts/evaluate-slo.sh`)
_PENDING_

### M3 · Rate-limit-under-load (R1) & breaker-under-fault (R2)
_PENDING_

### M4 · Recovery — RPO / RTO
_PENDING_

### Environment of record
_PENDING_
