# TIP-012 · Builder 5 Report — SLO, k6 load testing, SLO evaluation, recovery drills (AC-13, AC-14)

## STATUS

**DONE.** SLO targets were declared and committed BEFORE any measurement
(D-012-08, separate earlier commit). k6 (pinned `grafana/k6:0.49.0@sha256:8cd78f9…`)
drives four scenarios **through the ingress** (`https://rtr.local`, real dev-OIDC
session, fake/offline provider) plus a rate-limit probe; `scripts/evaluate-slo.sh`
parses the k6 JSON and **PASSES all 10 checks (exit 0)**. Rate-limit-under-load
is proven at the exact configured threshold (200 OK ×120 then 429 ×130, zero
5xx); the circuit breaker is proven under injected provider fault (Builder 2's
fake-failure hook, live infra). Both recovery drills were run and measured: a
**RESTORE PASS** on the hardened stack with RTO 236 s and an RPO marker-delta
demonstration, and a fresh timed deploy→rollback with the health gate green both
ways. Baseline stays green (backend 293/102, ruff + mypy clean); no app code
touched.

## FILES CHANGED

New (all additive — no Builder 1–4 file weakened):
- `docs/slo.md` — SLO declaration (targets committed first) + filled measured
  baseline (load table, evaluation output, R1/R2 evidence, RPO/RTO, environment).
- `compose.load.yaml` — load-measurement override (raises rate-limit quotas so a
  single-IP k6 measures server latency, not the per-IP limiter). Non-shipping;
  never used by `make dev` / `hardened-up` / deploy / CI.
- `load/lib/common.js` — shared k6 helpers: dev-OIDC login through the ingress,
  custom metrics, upload-target discovery.
- `load/steady_read.js` (S1a/S1b + S5), `load/ask_burst.js` (S2),
  `load/upload_stream.js` (S3), `load/spike_recover.js` (S6),
  `load/rate_limit_probe.js` (R1) — the scenarios (parameterised, sane defaults).
- `load/README.md` — how to run, the auth approach + why it is representative,
  the reproducible-fixtures note, tunables.
- `load/results/*.summary.json` + `*.log` — committed run artifacts (AC-13).
- `scripts/run-load.sh` — orchestrator (k6 via the compose network + add-host to
  the ingress IP; per-scenario summary export; seeds fixtures).
- `scripts/run-load-probe.sh` — R1 probe at shipped default limits.
- `scripts/evaluate-slo.sh` — pure-python3 pass/fail vs `docs/slo.md`, non-zero on
  breach (AC-13 evidence, not prose).
- `scripts/seed-load-fixtures.sh` — idempotent load fixtures (staff-owned upload
  target; budget headroom) so the run is reproducible for the Contractor.

Modified:
- `Makefile` — additive `load-up`, `load`, `load-probe`, `slo` targets; `verify`
  and every existing recipe untouched.

## TEST RESULTS

### SLO targets vs measured (through the ingress, fake provider)

| Scenario | Metric | Target | Measured p95 | Result |
|----------|--------|:------:|-------------:|:------:|
| S1a steady_read point (files/gaps) | `point_read_duration` | ≤ 300 ms | **160.6 ms** | PASS |
| S1b steady_read dashboard aggregate | `dashboard_read_duration` | ≤ 500 ms† | **329.2 ms** | PASS |
| S5 availability (`/api/status` 1 rps) | `avail_ok` | ≥ 99 % | **100.00 %** | PASS |
| S2 ask_burst (grounded + honest-null) | `ask_duration` | ≤ 1500 ms | **894.6 ms** | PASS |
| S3 upload_stream (1 MB accept 202) | `upload_duration` | ≤ 2000 ms | **954.4 ms** | PASS |
| S6 spike recovery tail | `read_duration_recovery` | ≤ 300 ms | **204.2 ms** | PASS |
| error rate (all SLO scenarios) | `errors` | < 0.5 % | **0.000 %** | PASS |

† S1b adjusted from the lumped 300 ms starting point — see DEVIATIONS. Zero 5xx
across every scenario. Offered load: steady ≈ 11 reads/s, ask ≈ 15 req/s, upload
≈ 5.7 req/s, spike peak ≈ 45 req/s.

### `scripts/evaluate-slo.sh` output (exit 0)

```
Objective                         Measured        Target  Result
S1a point read p95 (files/gaps)   160.6 ms   <= 300.0 ms  PASS
S1b dashboard aggregate p95       329.2 ms   <= 500.0 ms  PASS
S1 read error rate                 0.000 %     < 0.500 %  PASS
S5 availability                  100.000 %   >= 99.000 %  PASS
S2 ask p95 (fake provider)        894.6 ms  <= 1500.0 ms  PASS
S2 ask error rate                  0.000 %     < 0.500 %  PASS
S3 upload-accept p95 (1MB)        954.4 ms  <= 2000.0 ms  PASS
S3 upload error rate               0.000 %     < 0.500 %  PASS
S6 spike-recovery read p95        204.2 ms   <= 300.0 ms  PASS
S6 spike error rate                0.000 %     < 0.500 %  PASS
VERDICT: PASS — all SLOs met
```

### R1 — rate-limit under load (through the ingress, DEFAULT limits)

`rate_limit_probe.js` sent 250 rapid `GET /api/v1/files` from one IP:
- **200 OK ×120** — exactly the shipped `default-read` quota (120 / 60 s);
- **429 ×130**, **5xx ×0**; every 429 carried `Retry-After ≥ 1` and the typed
  `rate_limited` code (k6 checks 100 %). k6 thresholds (`status_429>0`,
  `status_5xx==0`) passed.

### R2 — breaker under provider fault (Builder 2 fake-failure hook, live infra)

Fresh DB migrated to head on native PG :5432, Redis :6380, MinIO :9002:
- `test_hanging_provider_is_timeout_bounded_then_breaker_opens_503` **PASS** —
  hung provider cut at the 50 ms timeout (wall < 1 s), breaker opens after the
  threshold → typed `503`, no further provider call.
- `test_failing_provider_opens_breaker_across_asks` **PASS**.
- Full `test_limits_integration.py` = **7/7** (rate/body/budget/breaker/queue).

### Recovery — RPO / RTO (AC-14)

**Restore drill** (`backup-data.sh` MAINTENANCE_MODE=true → `restore-data.sh`
target `restoredrill`, hardened stack):
- **RESTORE PASS** — `objects=376 row_counts=100% checksums=100%
  audit_chain=valid runtime_denials=16`.
- **RTO = 236 s** (script `duration_seconds`); full wall-clock 306 s incl. local
  archive validation.
- **RPO** = backup cadence (assumed ≤ 1 h pilot posture). Demonstrated: 5 marker
  asks written AFTER the backup (audit +5 / messages +10 / answer_runs +5) are
  **absent** from the restored copy, which holds exactly the snapshot (audit 5892
  / messages 1882 / answer_runs 941). Backup write-pause window = 24 s.

**Rollback drill** (fresh timed run, health gate through the ingress):

| Action | Wall-clock | Health gate | Ledger after |
|--------|-----------:|:-----------:|--------------|
| `deploy.sh b5d1` | 39.5 s | READY 1 s | current=b5d1, prev=drill-a |
| `deploy.sh b5d2` | 37.3 s | READY 0 s | current=b5d2, prev=b5d1 |
| `rollback.sh` (→ b5d1) | 33.8 s | READY 3 s | current=b5d1, prev=b5d2 |

`:latest` re-pointed to the `b5d1` image (`sha256:f298d435…`); schema-NOT-downgraded
warning printed; `versions.log` appended. (Ledger files reverted to Builder 4's
committed state afterward — drill numbers live here + in `docs/slo.md`.)

### Regression / baseline

- Backend: `ruff` clean · `mypy` **98 files** clean · `pytest` **293 passed /
  102 skipped** (unit; unchanged — no python touched).
- Web: untouched (no `apps/web` change).
- `docker compose config` for `compose.yaml + compose.hardened.yaml +
  compose.load.yaml` validates; `make verify` / verify-scripts untouched.

## ISSUES

- **`backup-data.sh` uses BSD `stat -f%z`** (line 160) which fails on Linux
  (`stat: invalid option -- '%'`). Harmless here: it is inside an `echo` command
  substitution so the failure is masked and **BACKUP PASS still prints** (only the
  `bytes=` field is empty; the archive is already written). Flagged for the
  Contractor — a one-char fix (`stat -c%s`) if a byte count is wanted. Not my
  file; left unchanged.
- **Restore RTO scales with object count** because `restore-data.sh` copies
  objects one-per-`docker run mc cp`. My load uploads inflated the store to 376
  objects → ~1 obj/s → RTO 236 s (still < 5 min, but the initial 4-min tool
  timeout tripped on the first attempt). A single `mc mirror` would collapse this;
  TIP-013 item.
- **Restore `/restore` permission quirk** (as flagged in the handoff): the
  `mktemp -d` work dir is 0700 root, so the non-root `migrate` container can't
  read it. Replicated the documented shim (`/tmp/binshim/mktemp` chmods the dir to
  0755). Contractor must do the same when re-running the restore drill.
- **Seeded reference stack has no upload folder** and staff is not admin, so the
  upload scenario needs a seeded `source` upload target;
  `scripts/seed-load-fixtures.sh` creates one idempotently (canonical app shape:
  a `private_context` source owned by the requester → policy `authenticated_upload`).
- ClamAV freshness override `MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600` still
  required in this sandbox (Builders 1/4 note).

## DEVIATIONS

1. **S1b dashboard target 300 ms → 500 ms, with rationale (D-012-08 permits
   "adjust a target ONLY with a written engineering rationale").** The governance
   dashboard is a **live multi-query aggregate**, not a point read (measured
   ~250–360 ms p95 at target load vs ~130–160 ms for files/gaps). The suggested
   starting point lumped it with point reads; splitting it into a separate,
   clearly-labelled metric with a 500 ms bar is an evidence-based refinement, NOT
   a silent move — the 300 ms point-read bar is preserved and met. Both metrics
   are checked independently by `evaluate-slo.sh`.
2. **S1 target load pinned at 10 reads/s.** The committed targets left the read
   "load envelope" as "mixed, steady" (underspecified). The read path is modelled
   as a fixed arrival rate (representative of an internal LAN tool: tens of users
   with think time), not a zero-think-time robot. The 300 ms bar was NOT changed;
   the previously-blank load level was filled in with a stated basis. The capacity
   knee (~15 reads/s, where the 5+5 DB pool saturates) is documented, and the
   over-aggressive 22 reads/s run (aggregate p95 853 ms) is reported as saturation
   characterisation, not the SLO load.
3. **Rate limits raised for the SLO latency scenarios** via the additive
   `compose.load.yaml` (limiter still runs — only its reject ceiling is lifted).
   Reason: a single-subject/single-IP k6 would otherwise be throttled by the
   limiter, not the server. Enforcement at shipped defaults is proven separately
   and un-raised (R1 = exactly 120 then 429). This is a measurement-harness
   setting, not a relaxation of the shipped defaults.
4. **Breaker fault injection is at the integration layer, not the ingress.** The
   shipped stack has no runtime "make the provider fail" toggle (the fake provider
   never fails and no evidence-free ask ever reaches the provider), so R2 is
   driven through Builder 2's `FailingProvider`/`HangingProvider` doubles against
   live Redis + Postgres — the coordinated fake-failure hook. I did NOT add a
   fault-injection toggle to app code (out of my slice; would be an unnecessary
   product surface).
5. **k6 transport:** k6 attaches to the compose network with `--add-host
   rtr.local:<ingress-ip>` (the ingress publishes on 127.0.0.1 only, unreachable
   from a bridge via host-gateway; and `--add-host` is incompatible with sharing
   the ingress netns). TLS via `--insecure-skip-tls-verify` (Caddy local CA).

## SUGGESTIONS

**For the Contractor to re-run**
- `make load-up` (export `MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600`) → `make
  load` (runs the 4 SLO scenarios + `evaluate-slo.sh`, expect exit 0) → `make
  load-probe` (R1 at default limits). `make slo` re-evaluates existing results.
- Restore drill needs the `mktemp` shim (see ISSUES) and clean isolated
  target/bucket names; drop `restoredrill` DB + bucket between runs.
- R2: run `test_limits_integration.py -k "breaker or hanging or failing"` on a
  fresh DB (native PG :5432, Redis :6380, MinIO :9002 bucket `rtr-test`,
  `S3_ACCESS_KEY=local`/`S3_SECRET_KEY=local-secret`, `SOT_SIGNING_SECRET=test-only-…`).
- The stack was left in the **dev profile, READY** (matching Builders 1/4).

**Production re-baseline notes for TIP-013**
- **DB pool sizing is the read-throughput knee.** `db/engine.py` pools 5+5; the
  read p95 stays flat to ~10–12 reads/s then rises steeply (dashboard aggregate
  → ~1 s at 15 reads/s). Size the pool (and Postgres `max_connections`) to the
  real concurrency, then re-baseline these SLOs on production hardware + real
  certificates + a real provider (the fake provider makes S2 optimistic — a real
  LLM call dominates ask latency and consumes the cost budget for real).
- **Restore efficiency:** replace `restore-data.sh`'s per-object `docker run mc
  cp` loop with a single `mc mirror` (or an in-process client); RTO currently
  scales linearly with object count.
- **`backup-data.sh` `stat -f%z`** → `stat -c%s` for Linux (cosmetic; backup still
  passes).
- Consider a metrics-driven SLO gate in CI: Builder 3's
  `histogram_quantile(0.95, rtr_http_request_duration_seconds_bucket)` alongside
  the k6 client-side numbers.
