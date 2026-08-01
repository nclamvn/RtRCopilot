# TIP-012 · Builder 1 Report — TLS ingress, security headers, secret hygiene (AC-01, AC-02, AC-03)

## STATUS

**DONE.** Hardened profile live-tested in this environment: Caddy ingress
(digest-pinned) terminates TLS for one hostname, only the ingress publishes
ports, all security headers assert through it, HTTP→HTTPS redirects, dev-OIDC
auth completes through the ingress with a `Secure+HttpOnly+SameSite` cookie,
leak probes are clean, and the production boot guard fail-closes on every
catalogued default secret. All baseline gates stay green; dev profile
byte-compatible (re-booted and smoke-tested after the hardened run).

## FILES CHANGED

New:
- `v2/infra/ingress/Caddyfile` — ingress config: one hostname (`INGRESS_HOST`,
  default `rtr.local`), `tls {$INGRESS_TLS_MODE}` (internal CA default, real
  certs by env only — both modes `caddy validate`d), 308 HTTP→HTTPS, security
  headers (two classes, see DEVIATIONS), routes `/api/v1/*`→api:8000, rest→web:3000.
- `v2/infra/ingress/certs/README.md` — mount point for real certificates.
- `v2/compose.hardened.yaml` — hardened override: `ports: !reset []` for
  minio/api/web (the only base services that publish; postgres/redis/clamav/worker already publish nothing).
- `v2/scripts/wait-ready-hardened.sh` — readiness judged through the ingress
  only (curl `--resolve`, `--noproxy`), plus worker/ClamAV health.
- `v2/apps/backend/tests/test_ingress_probe.py` — 15 through-ingress probes
  (AC-01/02/03), env-gated by `INGRESS_PROBE_ORIGIN` (skipped in unit runs).
- `v2/apps/web/src/app/api/status/route.test.ts` — 3 vitest tests for the
  status endpoint leak fix.
- `v2/docs/ingress-hardening.md` — operator guide: hostname/cert config,
  hardened usage, header classes, secret catalog + injection procedure.

Modified:
- `v2/compose.yaml` — added `ingress` service under `profiles: ["hardened"]`
  (image `caddy:2.11.4@sha256:844f60b64e4724a5aa8245e019dace0d3f199f7433ce6c57676cb30a920dbad9`,
  read_only, cap_drop ALL + NET_BIND_SERVICE, ports `127.0.0.1:80/443`,
  healthcheck via Caddy admin endpoint) + `caddy-data`/`caddy-config` volumes;
  `SESSION_COOKIE_SECURE` passthrough (default empty) on api/worker; ClamAV
  `MALWARE_SIGNATURE_MAX_AGE_SECONDS` now `${…:-172800}` (default unchanged;
  sandbox note below). Default-profile behavior unchanged (`docker compose
  config` verified: dev publishes 3000/8000/9001 exactly as before).
- `v2/apps/backend/src/rtr_copilot/config.py` — `KNOWN_DEFAULT_SECRETS`
  catalog; `session_cookie_secure: bool | None` (+""→None validator) and
  `session_cookie_secure_effective` property (production always secure; other
  envs follow `PUBLIC_BASE_URL` scheme); production guard additions: refuses
  any catalogued secret value in POSTGRES_DSN/MIGRATION_DSN password,
  REDIS_URL password, S3 access/secret key, OIDC client secret, SOT signing
  secret (`<key>:known_default_forbidden`, all offenders listed at once);
  refuses `session_cookie_secure=false` and non-https `OIDC_ISSUER`; refusal
  logged as `configuration_rejected` JSON (no secret values echoed).
- `v2/apps/backend/src/rtr_copilot/auth/api.py` — session cookie
  `secure=settings.session_cookie_secure_effective` (was `app_env=="production"`).
- `v2/apps/web/src/app/api/status/route.ts` — browser-facing status now
  returns only `{ok, status, request_id}` (see DEVIATIONS #3).
- `v2/Makefile` — additive targets `hardened-up`, `hardened-down`,
  `hardened-probe` (existing targets and `verify` untouched).
- `v2/.env.example` — secret-catalog banner, every shipped default tagged
  `[MUST-CHANGE]`, new `INGRESS_*` + `SESSION_COOKIE_SECURE` variables.
- `v2/README.md` — hardened-profile section linking `docs/ingress-hardening.md`.
- `v2/apps/backend/tests/test_config.py` (+16 tests),
  `v2/apps/backend/tests/test_auth.py` (+1 test).

## TEST RESULTS

Before → after:
- backend ruff: PASS → PASS; mypy: 83 files PASS → 83 files PASS (strict)
- backend pytest: **220 passed / 75 skipped → 237 passed / 90 skipped**
  (+16 config boot-guard, +1 auth secure-cookie; +15 ingress probes skipped
  without a live ingress)
- web: eslint PASS, tsc PASS, vitest **143 → 146 passed**, `next build` PASS
- `docker compose config --quiet`: PASS (dev) and PASS
  (`-f compose.yaml -f compose.hardened.yaml --profile hardened`)

Hardened stack brought up for real (`make hardened-up`, this environment):
- `docker compose ps`: **only ingress publishes ports** —
  `127.0.0.1:80->80, 127.0.0.1:443->443`; api/web/minio publish nothing.
- `make hardened-probe`: **15/15 PASSED** —
  - AC-01: `http://rtr.local/` → `308 Location: https://rtr.local/`;
    TLS verifies cleanly against the exported Caddy root CA
    (`curl --cacert root.crt` → 200, `ssl_verify_result 0`).
  - AC-02 headers on pages (evidence, `/files`): HSTS
    `max-age=604800; includeSubDomains`; CSP `default-src 'self'; script-src
    'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'
    data: blob:; font-src 'self' data:; connect-src 'self'; media-src 'self'
    blob:; frame-src 'self'; worker-src 'self' blob:; object-src 'none';
    base-uri 'self'; form-action 'self'; frame-ancestors 'none'`;
    `X-Frame-Options: DENY`; `X-Content-Type-Options: nosniff`;
    `Referrer-Policy: strict-origin-when-cross-origin`; minimal
    `Permissions-Policy`; `Server`/`Via` stripped. `/api/files/*` class:
    `X-Frame-Options: SAMEORIGIN` + `frame-ancestors 'self'`.
  - Browser smoke (Playwright chromium through the ingress, after dev-OIDC
    login): /files /documents /ask /knowledge-ops /admin —
    **0 CSP violations, 0 console/page errors**.
  - Auth through ingress: login → dev authorize → callback all on
    `https://rtr.local`; `set-cookie: rtr_session=…; HttpOnly; Max-Age=3600;
    Path=/; SameSite=lax; Secure`; `/api/auth/me` → 200 staff identity.
  - AC-03 leak probe over 10 surfaces (pages, 404s, API errors, traversal
    attempts, status, auth errors): zero hits for dev secrets, DSN/URL shapes,
    bucket/object forms, internal host:port (`postgres:5432`, `redis:6379`,
    `minio:9000`, `api:8000`…) and bare internal hostnames.
- Boot guard proven by test: production + all `.env.example` defaults refuses
  with every offender listed (`postgres_dsn/migration_dsn/s3_access_key/
  s3_secret_key/oidc_client_secret/sot_signing_secret:known_default_forbidden`),
  logged `configuration_rejected`, zero secret values echoed; green
  production config boots (`test_green_production_configuration_boots`).
- Dev profile re-booted afterwards: `wait-ready.sh` READY; `/files` 200;
  `/api/status` `{"ok":true,"status":"ready",…}`; dev auth flow over plain
  HTTP issues cookie **without** `Secure` (behavior preserved). Left running.

## ISSUES

- ClamAV signatures in this sandbox are stale (Jul 27; `database.clamav.net`
  unreachable, freshclam fails) → the stock 2-day freshness healthcheck can
  never pass here. Made the max-age env-tunable (default unchanged) and ran
  with `MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600` per the TIP's standing
  environment note. Contractor: export the same when (re)creating worker here.
- This environment routes all HTTPS through an agent proxy; local ingress
  probes must bypass it. Handled in committed code (`--noproxy` in
  wait-ready-hardened.sh, `trust_env=False` in the probe tests); anyone
  probing by hand needs `curl --noproxy '*'`.

## DEVIATIONS

1. **Ingress routing**: `/api/v1/*` → api; **everything else → web**,
   including `/api/auth|files|ask|governance|document-os|status`. Routing all
   of `/api/*` to api (one literal reading of the task) is impossible: the
   backend serves `/auth/*` and `/api/v1/*`, not `/api/auth/*` etc. — those
   are Next same-origin proxies with their own validation, which the TIP
   requires to keep working. Matches the TIP's "(and `/api/v1/*` passthrough
   shape as the web proxy expects)". Backend-internal `/auth`, `/health`,
   `/metrics`, `/system` are unreachable through the ingress by design.
2. **X-Frame-Options DENY is path-scoped**: `/api/files/*` gets `SAMEORIGIN`
   + `frame-ancestors 'self'` because the files viewer embeds PDF renditions
   in a same-origin `<iframe>` (`src/files/viewers.tsx`); blanket DENY breaks
   that viewer (tested, not guessed). Every other path gets DENY +
   `frame-ancestors 'none'`.
3. **One web change beyond the ingress**: `/api/status` previously forwarded
   `/health/ready`'s dependency map whose keys are internal hostnames
   (`postgres`, `redis`) — a direct AC-03 violation through the ingress. The
   route now returns aggregate `{ok, status, request_id}` only. UI consumes
   only `ok`/`status`; Playwright mocks supply their own bodies; docker
   healthcheck/wait-ready use status codes. Covered by 3 new vitest tests.
   Detailed dependency status remains on the API's internal `/health/ready`.
4. **App images rebuilt** (api/worker/web) although the handoff predicted no
   rebuild: the cookie-Secure and status-route changes live in the images.
   Used the documented mirror workaround
   (`EXPERIMENTAL_BUILDKIT_SOURCE_POLICY=/tmp/mirror/source-policy.json`,
   `--build-arg VOSK_MODEL_URL=http://172.17.0.1:8123/vosk.zip`; mirror HTTP
   server restarted).
5. `APP_ENV` values remain `development|test|production` (the codebase has no
   `local` literal; handoff's "APP_ENV=local" read as "the dev default").
6. HSTS default is 7 days (`INGRESS_HSTS_MAX_AGE=604800`) for local sanity;
   docs instruct ≥1 year with real certificates.

## SUGGESTIONS (Builders 2–5, Contractor)

- **Names/ports**: hostname `rtr.local` (needs `127.0.0.1 rtr.local` in
  /etc/hosts — already added in this sandbox); ingress binds
  `127.0.0.1:${INGRESS_HTTP_PORT:-80}` / `:${INGRESS_HTTPS_PORT:-443}`;
  profile name `hardened`; always run it as
  `docker compose -f compose.yaml -f compose.hardened.yaml --profile hardened …`
  (or `make hardened-up|down|probe`). Dev and hardened share one compose
  project — run one shape at a time.
- `make hardened-up` overrides `PUBLIC_BASE_URL=https://rtr.local` for the
  app containers; that single override drives both the OIDC callback origin
  and the derived `Secure` cookie. If you bring services up by hand under the
  hardened files, export it yourself or cookies won't be Secure.
- **Boot guard contract**: `KNOWN_DEFAULT_SECRETS` +
  `session_cookie_secure_effective` live in
  `v2/apps/backend/src/rtr_copilot/config.py`. Any Builder adding a secret
  must extend the catalog AND tag it `[MUST-CHANGE]` in `.env.example`.
  Refusal codes: `<key>:known_default_forbidden`,
  `session_cookie_secure:required_in_production`, `oidc_issuer:https_required`
  (plus pre-existing ones); all logged as `configuration_rejected`.
- **Builder 2**: ingress-side body limit hook is `request_body max_size` in
  the Caddyfile `handle` blocks (deliberately not set in my slice — keep
  ingress and app 413 consistent when you add it).
- **Builder 3**: `/metrics` and `/health/*` are internal-only (not routed
  through the ingress) — scrape on the compose network; that posture is
  intentional, don't route them.
- **Builder 4**: third-party digest to assert:
  `caddy:2.11.4@sha256:844f60b64e4724a5aa8245e019dace0d3f199f7433ce6c57676cb30a920dbad9`.
  Ingress runs read_only, cap_drop ALL + NET_BIND_SERVICE, no-new-privileges.
- **Builder 5**: run k6 against `https://rtr.local` with the container flags
  `--add-host rtr.local:host-gateway` (or on the compose network) and either
  `--insecure-skip-tls-verify` or the exported CA
  (`docker compose --profile hardened cp ingress:/data/caddy/pki/authorities/local/root.crt …`).
- **CSP**: `script-src/style-src` include `'unsafe-inline'` because the Next
  runtime bootstraps with inline scripts (verified 0 console violations on
  the real build). Tightening to nonces requires app-level changes — a
  possible TIP-013 item, not a config tweak.
- **Sandbox quirks** (also in ISSUES): `MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600`
  for ClamAV health; mirror server must be running for any image rebuild;
  `--noproxy '*'` for hand-run curl probes. Environment left in dev shape,
  stack READY.
