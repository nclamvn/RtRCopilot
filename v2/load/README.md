# RtR Copilot V2 — k6 load suite (TIP-012 Task 5)

k6 scenarios that drive the **hardened stack through the ingress**
(`https://rtr.local`) with the **fake/offline provider** (no external spend).
Targets and the measured baseline live in [`../docs/slo.md`](../docs/slo.md).

## Layout

| File | SLO | What it does |
|------|-----|--------------|
| `lib/common.js` | — | shared: dev-OIDC login, custom metrics, upload-target discovery |
| `steady_read.js` | S1a/S1b + S5 | mixed files/gaps/dashboard reads at a fixed arrival rate + a 1 rps `/api/status` availability probe |
| `ask_burst.js` | S2 | concurrent `POST /api/v1/ask` (grounded + honest-null) against the fake provider |
| `upload_stream.js` | S3 | 1 MB streamed `POST /uploads`, measures the 202 accept latency |
| `spike_recover.js` | S6 | ramp read load to a spike and back, measuring the recovery-tail p95 |
| `rate_limit_probe.js` | R1 | drives one IP past the **default** `default-read` quota; asserts 429 + Retry-After, zero 5xx |
| `results/` | — | `--summary-export` JSON (consumed by `scripts/evaluate-slo.sh`) + per-scenario logs |

## How to run

```bash
# 1. Bring up the hardened stack WITH the load-measurement override.
make load-up            # sandbox: export MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600 first

# 2. Run the 4 SLO scenarios + evaluate against docs/slo.md targets.
make load               # = scripts/run-load.sh && scripts/evaluate-slo.sh
#    (run-load.sh seeds the reproducible fixtures via scripts/seed-load-fixtures.sh)

# 3. R1 rate-limit-under-load probe at the SHIPPED default limits.
make load-probe         # recreates api WITHOUT compose.load.yaml, then probes

# Re-evaluate existing results only:
make slo
```

k6 runs in the pinned `grafana/k6:0.49.0@sha256:8cd78f9…` container. It attaches
to the compose network and maps `rtr.local` to the ingress container IP
(`--add-host rtr.local:<ingress-ip>`) — the ingress publishes on `127.0.0.1`
only, so `host-gateway` cannot reach it, and sharing the ingress netns is
incompatible with `--add-host`. TLS uses `--insecure-skip-tls-verify` (Caddy's
local CA); the exported root CA (`docker compose cp
ingress:/data/caddy/pki/authorities/local/root.crt`) is the alternative.

## Auth: how a valid session is obtained (and why it is representative)

Each scenario's `setup()` calls `login()` (in `lib/common.js`), which performs a
**real dev-OIDC login through the ingress** — the exact flow Builder 1's
through-ingress probe uses:

1. `GET /api/auth/login` (web-proxied) → 302 to `/api/auth/dev/authorize`;
2. k6's per-VU cookie jar carries the PKCE/state cookies across the redirect
   chain → `dev/authorize` → 302 to the callback on `rtr.local`;
3. the callback sets the `HttpOnly`+`Secure` `rtr_session` cookie.

`login()` returns that cookie as a header string; every VU attaches it
explicitly (setup's jar is not shared with VU jars). This is representative
because it is the same session the browser holds after signing in: the API
validates it exactly as it would a human's, and the request also traverses the
rate limiter and security headers at the ingress. No cookie is hand-forged.

## Reproducible fixtures (`scripts/seed-load-fixtures.sh`)

The seeded reference stack ships **no upload folder**, and grounded ask bursts
debit the per-subject daily provider budget. `run-load.sh` calls
`seed-load-fixtures.sh` (idempotent) to:

- create one staff-owned `source` upload target (written to
  `/tmp/upload_target_rid.txt`, read by `upload_stream.js`);
- raise `limits.budget.{subject,global}_daily_units` (append-only governance
  version) so repeated same-day runs do not hit the daily cap.

Both are within the app's normal admin-editable ranges; the fake provider means
raising the budget spends nothing real.

## Tunables (env)

`STEADY_RATE` (reads/s, default 10), `ASK_VUS`/`ASK_DURATION`,
`UPLOAD_VUS`/`UPLOAD_DURATION`, `BASE_VUS`/`SPIKE_VUS`, `PROBE_REQUESTS`/`PROBE_VUS`.
See each scenario file's header.
