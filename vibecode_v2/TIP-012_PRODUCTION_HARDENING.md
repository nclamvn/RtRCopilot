# TIP-012 · Production Hardening

## HEADER

- **TIP-ID:** TIP-012
- **Project:** RtR Copilot V2
- **Module:** TLS ingress + security headers, secret hygiene, quotas/rate/body/
  cost limits, observability, CI/CD + migration gate, deploy/rollback, load
  testing + SLO, recovery drills + RPO/RTO, incident runbook
- **Depends on:** TIP-010, TIP-011 VERIFIED
- **Priority:** P0
- **Status:** ISSUED · awaiting Builders
- **Working directory:** `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2`
- **Requirements directly implemented/advanced:** REQ-005, REQ-029, REQ-030,
  REQ-031 (owned); hardens REQ-002, REQ-006, REQ-021
- **Gate chính (Task Graph):** *SLO/load targets met; restore and rollback
  drill pass. Hệ thống thất bại có kiểm soát, quan sát được, phục hồi được.*

## CONTEXT

TIP-001…011 delivered a functionally complete, policy-correct platform that
still runs "developer-grade": web/API bind 127.0.0.1 plaintext; `.env.example`
ships default secrets that would boot; no rate/body/cost limits beyond
provider timeouts; logs are structured but unmeasured (no metrics exposition,
no alert rules, no proven no-leak guarantee); no CI pipeline file exists in
the repo; deploy is `make dev` with no versioning or rollback; backup/restore
is proven but RPO/RTO are unmeasured; no load evidence exists at all.

TIP-012 turns these into enforced, measured properties. Blueprint §3 fixes the
runtime shape: Docker Compose on a private Linux VM behind a reverse-proxy
HTTPS ingress, VPN/LAN only. This TIP hardens THAT deployment; managed-cloud
migration remains out of scope.

## DECISIONS LOG

| ID | Decision | Rationale |
|---|---|---|
| D-012-01 | Ingress = Caddy in compose, terminating TLS for web+API on one hostname; internal services lose published ports in the hardened profile | Smallest correct config; automatic local CA for dev, real certs by config only |
| D-012-02 | `APP_ENV=production` is fail-closed: booting with any known-default secret, plaintext-only config or missing TLS refuses to start with a typed error | REQ-002 doctrine extended to configuration |
| D-012-03 | Rate/body/cost limits enforced in the API app layer (Redis-backed, per subject + per IP), not only at the proxy | Limits must survive an ingress bypass and be testable in unit/integration |
| D-012-04 | AI/provider spending is budgeted per subject and per day via `governance_settings`; breach → typed 429 `budget_exhausted`; a hung provider call can never block a request slot (timeout + circuit breaker proven by test) | REQ-031 verbatim |
| D-012-05 | Observability = prometheus-client exposition + curated alert rules + scrape config committed as artifacts; no new always-on infra service is REQUIRED to run the app | Measure first; heavy APM is a later choice |
| D-012-06 | CI = GitHub Actions workflow mirroring `make verify` stage-by-stage; the repo also gains `scripts/ci-local.sh` running the identical sequence so the gate is executable without GitHub | CI must be verifiable in this environment too |
| D-012-07 | Deploy/rollback = versioned image tags + `scripts/deploy.sh` (migration gate → up → health gate) and `scripts/rollback.sh` (previous tag + documented DB posture); rollback NEVER auto-downgrades migrations | Schema rollback is a Homeowner decision, not a script side effect |
| D-012-08 | Load testing = k6 (official container image), scenarios committed in-repo, SLO targets declared in `docs/slo.md` BEFORE the run; local-stack numbers are the acceptance evidence, production re-baseline is TIP-013+ | Targets first, numbers second — no post-hoc goalposts |
| D-012-09 | File-version-scoped ask retrieval stays DEFERRED (not hardening; TIP-013 decides its slot) | Scope discipline |
| D-012-10 | Tests synthetic; live corpora read-only | House rule |

## TASK

### 1. TLS ingress, security headers, secret hygiene (Builder 1)

- Add `ingress` (Caddy, pinned digest) to compose: terminates TLS for one
  hostname, routes `/` → web and `/api/*` (and `/api/v1/*` passthrough shape
  as the web proxy expects) → api; HTTP→HTTPS redirect; internal services'
  published ports removed in a `hardened` compose profile (dev profile keeps
  today's 127.0.0.1 binds so existing gates keep working);
- security headers at the ingress AND asserted by test through it: HSTS, CSP
  (compatible with the actual app — no inline-script regressions), X-Frame,
  X-Content-Type, Referrer-Policy, Permissions-Policy;
- session cookies `Secure` + `HttpOnly` + `SameSite` behind the proxy; auth
  flow works end-to-end through the ingress (dev OIDC);
- secret hygiene: catalog every secret; `APP_ENV=production` boot guard
  refuses known-default/placeholder secrets and non-TLS config (typed,
  logged, fail-closed — with tests); document secret injection
  (env-file/docker secrets) in operator docs; `.env.example` clearly marks
  every value that MUST change;
- no object key, bucket URL, internal hostname or credential appears in any
  ingress-served response or error page (probe).

### 2. Quotas, limits, resilience (Builder 2)

- Redis-backed rate limiting per subject AND per IP with bounded windows,
  typed 429 + `Retry-After`; sensible distinct budgets for auth, ask,
  upload, render, admin;
- request body-size limits (typed 413) consistent between ingress and app;
- provider cost budgeting: per-subject daily budget + global daily budget in
  `governance_settings` (typed, versioned, admin-editable via the existing
  settings surface); ask/extract/transcribe debit usage; breach → typed 429
  `budget_exhausted`; audited;
- circuit breaker on provider calls: consecutive-failure threshold opens the
  breaker (typed 503 `provider_unavailable`, half-open recovery), and a hung
  call NEVER blocks beyond its timeout (prove with a fake provider test);
- worker job concurrency caps + queue backpressure (typed job rejection with
  retry guidance) for ingestion/render/index jobs;
- all limits configurable via settings with safe bounded defaults; every
  limit event audited (`resource_id=NULL`, ids in details).

### 3. Observability (Builder 3)

- prometheus-client exposition on api AND worker (separate port/endpoint,
  NOT exposed through ingress): HTTP latency histograms by route class,
  error counts by typed code, job queue depth/duration, provider call
  latency/failures/budget debits, rate-limit/breaker events, DB pool stats;
- structured logs: request-id propagation proven end-to-end (ingress → api →
  worker job spawned by that request); a leak probe asserting logs contain no
  secret values, object keys or bucket URLs under exercised error paths;
- committed artifacts: `infra/observability/prometheus.yml` (scrape config),
  `alerts.yml` (curated rules: error rate, p95 latency, queue depth, breaker
  open, budget exhaustion, cert expiry placeholder, audit-chain verify
  failure), each rule with a one-line runbook pointer;
- audit export: admin-gated endpoint/job producing a bounded, checksummed
  export (JSONL) of audit events by time range; the export action is itself
  audited; no payload secrets;
- `docs/runbook.md`: incident playbooks (provider outage, queue saturation,
  restore, rollback, cert renewal, breaker storm), each ≤1 page, referencing
  real commands/scripts.

### 4. CI/CD, migration gate, deploy/rollback (Builder 4)

- `.github/workflows/verify.yml`: lint/type/unit (backend+web) → compose
  build → Trivy → containerized data-integration → browser suite (mocked
  Playwright) — stage-by-stage mirror of the local gate; failure blocks;
- `scripts/ci-local.sh`: the identical sequence runnable locally (this is
  what the Contractor executes as CI evidence in this environment);
- migration gate: single alembic head, `expected_schema_revision` pin match,
  no-divergence check — as a script used by CI, deploy.sh AND `make verify`;
- versioned deploys: image tags from git SHA; `scripts/deploy.sh` (build/pull
  → migration gate → migrate → rolling up → health gate → record deployed
  version) and `scripts/rollback.sh` (previous recorded version, health gate,
  explicit warning that schema is NOT auto-downgraded); both idempotent and
  fail-closed; drill-tested;
- image policy checks in CI: pinned digests for third-party images, non-root
  runtime users, read-only where declared (script assertion, not prose).

### 5. Load testing, SLO, recovery drills (Builder 5)

- `docs/slo.md` FIRST: declared targets for the local reference stack —
  suggested starting points (Builder validates/adjusts with rationale before
  running): p95 ≤ 300 ms for authenticated reads (files/gaps/dashboard),
  p95 ≤ 1.5 s for ask (fake provider), p95 ≤ 2 s for upload accept (1 MB),
  error rate < 0.5% at target load; availability probe definition;
- k6 scenarios committed under `load/`: steady-state mixed read, ask burst,
  upload stream, spike-and-recover; run against the hardened compose stack
  (through ingress) with the FAKE provider; results exported as artifacts
  (`load/results/*.json` summary + a human-readable report section);
- SLO evaluation script: pass/fail against `docs/slo.md` (this is AC
  evidence, not a narrative);
- recovery drills, measured: backup → restore (RPO = data loss window given
  backup cadence — measured by timestamped marker rows; RTO = wall-clock of
  the restore drill), deploy → rollback drill (previous version healthy
  again, time recorded); numbers land in the completion report and
  `docs/slo.md`'s measured-baseline section;
- rate-limit behavior under load verified (429s appear at configured
  thresholds, no 5xx storm; breaker engages under provider fault injection).

### 6. Regression and gates (all Builders)

Everything TIP-001…011 stays green: backend unit/full, web unit/build,
Playwright 73 (against dev profile as today), leak/masquerade probes, compose
build, Trivy, data-integration. New capabilities ship with their own unit +
integration + (where applicable) through-ingress tests.

## ACCEPTANCE CRITERIA

### AC-01 · TLS ingress fronts everything
Through the hardened profile, web+API are reachable only via HTTPS on the
ingress; HTTP redirects; internal service ports are not published; auth flow
completes through the ingress.

### AC-02 · Security headers hold
HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy,
Permissions-Policy asserted by automated test through the ingress; the app
functions under that CSP (no console violations in a browser smoke).

### AC-03 · Production boot is fail-closed on secrets
`APP_ENV=production` with any known-default secret or non-TLS config refuses
to start with a typed error; the full secret catalog + injection procedure is
documented; probes confirm no secret/object-key/internal-hostname leaks in
ingress responses.

### AC-04 · Rate and body limits enforce and type correctly
Per-subject and per-IP limits produce 429 + Retry-After at configured
thresholds (test-proven per budget class); oversized bodies produce typed 413
consistently at ingress and app; limit events are audited.

### AC-05 · Cost budgets bind the AI spend
Per-subject and global daily budgets debit real usage, breach as typed 429
`budget_exhausted`, are admin-adjustable via settings, and are audited.

### AC-06 · A slow provider cannot take the app down
Hung provider calls cut at timeout; consecutive failures open the circuit
breaker (typed 503, half-open recovery proven by test); request slots free.

### AC-07 · Queues exert backpressure
Job concurrency caps hold under integration test; over-cap submissions get
typed rejection with retry guidance; no unbounded queue growth.

### AC-08 · Metrics exist and mean something
API + worker expose Prometheus metrics covering the Task-3 list; scrape
config + alert rules are committed and lint-valid (`promtool check rules`
via container); each alert maps to a runbook entry.

### AC-09 · Logs are traceable and leak-free
Request-id propagates ingress → api → worker job in a proven test; the
log-leak probe finds zero secrets/object-keys/bucket-URLs across exercised
error paths.

### AC-10 · Audit export works and is itself audited
Admin-gated bounded export produces checksummed JSONL for a time range;
non-admin denied; the export event is in the audit trail.

### AC-11 · CI gate exists and blocks
`verify.yml` is valid (actionlint via container) and mirrors the local gate;
`scripts/ci-local.sh` executes the full sequence successfully in this
environment; migration gate fails on divergent head or pin mismatch (proven
by injecting a fake head in a scratch checkout).

### AC-12 · Deploy and rollback are drilled
`deploy.sh` deploys a versioned build behind the health gate; `rollback.sh`
returns to the previous version with health green; both drills executed and
timed; schema posture on rollback is documented, never automatic.

### AC-13 · SLOs declared then met
`docs/slo.md` targets committed before the run; k6 scenarios pass the SLO
evaluation script on the hardened local stack with the fake provider; results
artifacts committed; rate-limit/breaker behavior under load verified.

### AC-14 · Recovery is measured
Restore drill and rollback drill produce measured RPO/RTO numbers recorded in
`docs/slo.md`; restore passes through the existing RESTORE PASS gate on the
hardened stack.

### AC-15 · No regression
All TIP-001…011 gates green: backend unit/full (live infra), web unit/build,
Playwright 73/73, axe intact, leak/masquerade probes zero, compose build,
Trivy clean, data-integration PASS.

### AC-16 · Full verification
Zero P0/P1 across every gate above; deviations and deferred items listed with
REQ-IDs.

## OUT OF SCOPE

- Managed-cloud migration, K8s, CDN, WAF products (architecture keeps the
  path open; Blueprint OQ-002 stands).
- External penetration test (TIP-013 go/no-go input; internal probes only).
- Real provider spend measurement (fake provider locally; budgets are real
  code either way).
- File-version-scoped ask retrieval (D-012-09 — deferred, TIP-013 decides).
- Real company data, real OIDC tenant, real certificates (config paths ready).
- Email/chat alert delivery integrations (rules + runbook only).

## BUILDER HANDOFF

Builders 1→2→3→4→5 sequential on branch `tip-012`; each must:

1. implement only inside `v2` (plus `.github/` for Builder 4) and TIP
   completion evidence;
2. keep kernel/KnowledgeBase/GOI/corpora and `phase1_pilot` read-only;
3. write `vibecode_v2/_tip012_builder{1..5}_report.md` mapping ACs to code,
   tests, commands, counts, artifacts, deviations;
4. keep every existing gate green before declaring done; run what infra
   allows and report exactly what ran;
5. leave the working tree uncommitted for Contractor checkpoint.

Environment notes for Builders (cloud sandbox): compose build needs
`EXPERIMENTAL_BUILDKIT_SOURCE_POLICY=/tmp/mirror/source-policy.json` and
`--build-arg VOSK_MODEL_URL=http://172.17.0.1:8123/vosk.zip` (checksum-pinned
mirror; start `python3 -m http.server 8123` in /tmp/mirror if down); Docker
Hub reachable; ClamAV signature freshness stays an environment note; kill
stray `next-server` before browser gates; native Postgres 5432
(rtr_app/rtr_app_pw, rtr_owner/rtr_owner_pw), MinIO :9002, Redis :6380 for
fast integration runs.

Contractor will independently rerun all gates including through-ingress
probes, the SLO evaluation, and both drills, then write
`TIP-012_VERIFY_REPORT.md`. P0/P1 failure returns the TIP to BUILD.
