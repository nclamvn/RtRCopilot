# TLS ingress, security headers, secret hygiene — operator guide (TIP-012 Task 1)

The hardened profile puts a single Caddy ingress (digest-pinned
`caddy:2.11.4@sha256:844f60b6…`) in front of the whole stack. Web and API are
reachable **only** through HTTPS on the ingress; no other service publishes a
port (AC-01).

## Topology

| Route            | Upstream   | Notes                                                            |
|------------------|-----------|-------------------------------------------------------------------|
| `/api/v1/*`      | `api:8000` | Platform API surface, passthrough path shape                     |
| everything else  | `web:3000` | UI + the web same-origin proxies (`/api/auth`, `/api/files`, `/api/ask`, `/api/governance`, `/api/document-os`, `/api/status`) |

`http://` on port 80 answers only with a 308 redirect to `https://`.
Backend-internal surfaces (`/auth`, `/health`, `/metrics`, `/system`) are not
routed through the ingress; they stay reachable only on the compose network.

## Running the hardened profile

```bash
# once per machine — the ingress hostname must resolve locally:
echo "127.0.0.1 rtr.local" | sudo tee -a /etc/hosts

cd v2
make hardened-up        # infra -> migrate -> app + ingress; waits via ingress
make hardened-probe     # through-ingress probes (headers, redirect, leaks, auth)
make hardened-down
```

The default profile is untouched: `make dev` still binds
127.0.0.1:3000/8000/9001 and every existing gate runs as before. The two
profiles share one compose project — run one at a time.

Configuration knobs (all in `.env`, defaults shown in `.env.example`):
`INGRESS_HOST` (default `rtr.local`), `INGRESS_HTTP_PORT`/`INGRESS_HTTPS_PORT`
(default 80/443), `INGRESS_BIND_ADDRESS` (default `127.0.0.1`; set the reviewed
LAN/VPN/public interface IP for a real VM), `INGRESS_HSTS_MAX_AGE`.
`make hardened-up` also overrides `PUBLIC_BASE_URL` to
`https://$(INGRESS_HOST)` for the app containers so the OIDC callback and the
session-cookie `Secure` derivation follow the ingress origin.

## Certificates

**Local (default):** `INGRESS_TLS_MODE=internal` — Caddy issues a certificate
from its own local CA. To silence browser/curl warnings, trust the root:

```bash
docker compose cp ingress:/data/caddy/pki/authorities/local/root.crt rtr-local-ca.crt
# then import into the OS/browser trust store, or: curl --cacert rtr-local-ca.crt …
```

**Real certificates (no config-file change needed):** place the files in
`infra/ingress/certs/` (or point `INGRESS_CERTS_DIR` at them) and set

```bash
INGRESS_TLS_MODE="/certs/fullchain.pem /certs/privkey.pem"
```

The directory is mounted read-only at `/certs`. Rotate by replacing the files
and `docker compose --profile hardened restart ingress`. (Caddy can also do
ACME automatically once the VM has a public name — set `INGRESS_HOST` to that
name and remove `INGRESS_TLS_MODE` customization only after reviewing egress
policy; out of scope for the VPN/LAN deployment shape.)

## Security headers (AC-02)

Set at the ingress on every response: HSTS (`INGRESS_HSTS_MAX_AGE`, default 7
days locally — raise to ≥1 year with real certificates),
`X-Content-Type-Options: nosniff`, `Referrer-Policy:
strict-origin-when-cross-origin`, minimal `Permissions-Policy`, and CSP.

Two header classes exist: `/api/files/*` (file preview renditions the files
viewer embeds same-origin, e.g. the PDF iframe) gets `X-Frame-Options:
SAMEORIGIN` + `frame-ancestors 'self'`; every other path gets `X-Frame-Options:
DENY` and the full CSP (`default-src 'self'`; inline script/style allowed
because the Next.js runtime bootstraps with inline scripts — verified against
the real build, no console violations).

## Secret hygiene and the production boot guard (AC-03)

Catalog: `POSTGRES_PASSWORD`, `POSTGRES_RUNTIME_PASSWORD` (both also embedded
in `MIGRATION_DSN` / `POSTGRES_DSN`), `S3_ACCESS_KEY`, `S3_SECRET_KEY`,
`OIDC_CLIENT_SECRET`, `SOT_SIGNING_SECRET`, plus any password inside
`REDIS_URL`. Every shipped default is tagged `[MUST-CHANGE]` in
`.env.example`.

With `APP_ENV=production` the backend fails closed at boot
(`ConfigurationError`, logged as `configuration_rejected`, no secret values
echoed) if:

- any catalogued secret still holds a value from `KNOWN_DEFAULT_SECRETS`
  (`apps/backend/src/rtr_copilot/config.py`) — reported as
  `<key>:known_default_forbidden`;
- `PUBLIC_BASE_URL` or `OIDC_ISSUER` is not `https://`;
- `DEV_OIDC_ENABLED=true`, or `SESSION_COOKIE_SECURE=false`;
- OIDC settings are missing, or `SOT_SIGNING_SECRET` is short/reused.

Maintain `KNOWN_DEFAULT_SECRETS` and `.env.example` together when adding a
secret.

### Injecting real secrets

Preferred (works with the stock compose files): a root-owned env file outside
the repo —

```bash
install -m 600 -o root -g root /dev/null /etc/rtr-copilot/production.env
# fill it from .env.example, replacing every [MUST-CHANGE] value
docker compose --env-file /etc/rtr-copilot/production.env \
  -f compose.yaml -f compose.hardened.yaml --profile hardened up -d
```

Alternative: Docker secrets — mount each value under `/run/secrets/…` via a
compose override with a `secrets:` block and point the corresponding
environment variables at the file contents at entrypoint time. The stock files
deliberately stay env-based; a secrets override is additive and does not
require app changes.

Generate values with `openssl rand -base64 48` (≥32 bytes for
`SOT_SIGNING_SECRET`). Session cookies are `Secure + HttpOnly + SameSite=lax`
whenever served through the HTTPS ingress (derived; `SESSION_COOKIE_SECURE`
overrides — production refuses `false`).

## Production configuration closure (TIP-035.18)

The release gate uses a dedicated, fully materialized production profile. It
does not accept the development template, Caddy's local CA, shell expressions,
placeholder domains, a dirty build identity or a group/world-readable secret
file.

```bash
cd v2
make production-config-init
# edit .env.production from the approved secret source; never paste values in logs
chmod 600 .env.production
chmod 600 "$(awk -F= '$1 == "INGRESS_CERTS_DIR" {print $2}' .env.production)/privkey.pem"
make production-config-check
```

Before the check can pass, the operator must provide:

- the exact clean candidate SHA in `RTR_BUILD_SHA`;
- the real `PUBLIC_BASE_URL`, matching `INGRESS_HOST`, DNS and the TLS
  certificate; the OIDC redirect URI is
  `https://<INGRESS_HOST>/api/auth/callback`;
- the real HTTPS OIDC issuer, client ID/secret, corporate email domains and a
  valid JSON group mapping;
- unique database, S3, OIDC, SOT and provider secrets from the approved secret
  source; DSN passwords must match their dedicated owner/runtime passwords;
- the approved external-processing policy reference, credential-source
  reference and `internal` classification allowlist;
- `fullchain.pem` and `privkey.pem` for the production hostname, with at least
  seven days remaining and a mode-600 private key;
- a reviewed ingress bind IP and encrypted `BACKUP_DESTINATION`.

`make production-config-check` performs three fail-closed layers:

1. a content-free deployment check for exact build, OIDC/domain policy,
   separated secrets, connector-off state, TLS hostname/expiry/key match, file
   permissions, HSTS and ingress-origin coherence;
2. `docker compose config --quiet`, so the same materialized profile must form
   a valid stack;
3. application `Settings` construction inside the locked backend image.

The JSON verdict is written only below the ignored `eval/runtime/` boundary
and contains booleans, counts, digests and stable error codes—never environment
values. `.env.production` is ignored explicitly. A real file failing any layer
keeps the `production_configuration` release gate blocked.

## Verification

`make hardened-probe` runs `apps/backend/tests/test_ingress_probe.py` through
the live ingress: HTTP→HTTPS redirect (AC-01), the header set above (AC-02),
dev-OIDC auth flow with `Secure` cookie through the ingress, and a leak probe
asserting no secret value, object key, bucket URL or internal hostname/port
(`postgres:5432`, `redis:6379`, `minio:9000`, `api:8000`, …) appears in any
ingress-served response or error page (AC-03). The suite is skipped unless
`INGRESS_PROBE_ORIGIN` is set, so the normal unit gate is unaffected.
