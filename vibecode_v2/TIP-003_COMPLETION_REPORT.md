# TIP-003 · Builder Completion Report

- **Builder result:** PASS
- **Scope:** `v2/`
- **Reported at:** 2026-07-30
- **Verification status:** VERIFIED · READY after refinement

## Acceptance evidence reported by Builder

| Gate | Result |
|---|---:|
| Backend pytest | 86/86 |
| Policy scenarios | 51 |
| Auth/session/current-authority tests | 16 |
| Production OIDC tests | 9 |
| API tests | 6 |
| Configuration/redaction tests | 2 |
| Worker tests | 2 |
| Ruff | PASS |
| Mypy strict | PASS — 16 source files |
| Web Vitest | 1/1 |
| Playwright | 3/3 |
| ESLint / TypeScript / Next build | PASS |
| `pnpm audit --audit-level high` | 0 known vulnerabilities |
| Docker builds and runtime health | PASS |

## Builder claims handed to Verifier

- Authorization Code flow implements PKCE, state and nonce.
- Verified corporate email/domain and immutable identity use `(issuer, sub)`.
- Redis sessions are opaque, TTL-bound, rotated and revocable.
- Production cookies are `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.
- Client role claims are ignored; group mapping is server-side.
- Policy evaluation is default-deny, explicit-deny wins and admin does not bypass
  classified-content access.
- Privileged decisions emit redacted structured audit events.
- Production startup fails closed for invalid identity configuration and production
  OpenAPI excludes all `/auth/dev/*` routes.
- Login callback query strings do not appear in Uvicorn access logs.
- Browser flow covers signed-out, fake corporate login, signed-in identity,
  classified-resource denial and logout at mobile and desktop widths.

## Declared deviations and boundaries

- Subject persistence remains Redis-backed until TIP-004 supplies PostgreSQL adapters.
- Role-change session rotation exists at the storage boundary; user-management API is
  deliberately outside TIP-003.
- Break-glass is disabled and not implemented.
- No real Google OIDC credential is used in tests.

This report records Builder evidence only. It is not an acceptance certificate;
`TIP-003_VERIFY_REPORT.md` controls READY/NOT READY.

## Refinement after first VERIFY

The first independent verification rejected the build. Builder then:

- replaced authorization snapshots with current-authority lookup and monotonic
  `security_version`;
- added `revoke_all` and immediate invalidation for role/group/scope/entitlement or
  status changes;
- audited restricted/classified `view`, `download` and `render` allow/deny decisions;
- documented typed 401/403 responses in OpenAPI; and
- added nine production OIDC cryptographic/error regression tests.

The refined build passed independent re-verification.
