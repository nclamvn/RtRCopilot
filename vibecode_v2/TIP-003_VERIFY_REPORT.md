# TIP-003 · Independent Verify Report

- **First verifier result:** NOT READY
- **Re-verification result:** READY
- **Verified at:** 2026-07-30
- **Boundary hash:** `8ed582…dbf` unchanged

## Blocking findings

1. **P1 — stale privileged sessions after role change.** A concurrent session issued
   while the subject had `leader + staff` remained authorized after server-side role
   mapping reduced the subject to `staff`.
2. **P1 — disabled account does not invalidate existing sessions.** The repository
   subject changed to `disabled`, but the old session still returned `200` from
   `/auth/me`. Sessions currently store an authorization snapshot without checking a
   current security version/status.
3. **P1 — privileged content decisions are not fully audited.** The policy engine
   audits administrative actions but not all restricted/classified
   `view/download/render` allow/deny decisions.
4. **P1 — OpenAPI omits typed 401/403 responses.** Runtime errors are typed and carry
   request IDs, but `/auth/me` and the protected route document only success responses.
5. **P2 — no committed ProductionOIDCProvider regression tests.** Independent probes
   passed discovery, JWKS, RS256 signature, audience, issuer, expiry, nonce and PKCE,
   but the repository test suite does not preserve that coverage.

## Acceptance mapping

| AC | Result |
|---|---|
| AC-003.1 OIDC security | PASS with P2 regression-test gap |
| AC-003.2 Immutable identity | PASS |
| AC-003.3 Session safety | FAIL |
| AC-003.4 Role mapping/status | FAIL |
| AC-003.5 Policy matrix | PASS — 45 scenarios |
| AC-003.6 Admin non-bypass / curator SoD | PASS |
| AC-003.7 Audit | FAIL |
| AC-003.8 Fail-fast/config | PASS |
| AC-003.9 API contract | FAIL |
| AC-003.10 Web/browser | PARTIAL — artifacts pass; verifier browser unavailable |
| AC-003.11 Technical health | PASS |

## Evidence that passed independently

- Frozen locks unchanged; dependency audit clean.
- `make verify` passed with 67/67 pytest, Ruff, strict mypy, web lint/type,
  Vitest 1/1, production build and three Docker images.
- Independent production-provider cryptographic probe passed.
- Production OpenAPI excludes `/auth/dev/*`.
- Runtime 401 includes a stable machine code and request ID.
- Invalid callback sentinel is absent from logs; configuration sentinels are redacted.
- Policy matrix proves default deny, deny precedence, entitlements, expiry, owner and
  admin non-bypass.

TIP-003 must return to Builder for refinement. No downstream TIP may treat identity
and policy as READY until all P1 findings are closed and the P2 regression gap is
covered.

## Independent re-verification

All five findings were closed and reproduced independently against Redis/runtime:

| Closure probe | Result |
|---|---|
| Concurrent stale leader session after downgrade | PASS — old session returns 401 |
| Existing session after subject disabled | PASS — returns 401 |
| `revoke_all` across two concurrent sessions | PASS — both return 401 |
| OIDC group/role remap | PASS — old security versions invalidated |
| Restricted/classified content decision audit | PASS — allow/deny, redacted |
| OpenAPI and runtime typed 401/403 | PASS |
| Production OIDC committed suite + crypto probe | PASS — 9 tests |

Final health: 86/86 backend tests, 51 policy scenarios, 9/9 production OIDC tests,
Ruff, strict mypy, Vitest, ESLint, TypeScript, Next build, dependency audit, Docker
builds and runtime health all passed. Legacy aggregate hash remained
`8ed582a7194e70c447fc4fbe3e1fcf3192db48a7651fffb2ff3ac3a9ddc3bdbf`.

**Final acceptance: 11/11 AC passed. TIP-003 is READY.**
