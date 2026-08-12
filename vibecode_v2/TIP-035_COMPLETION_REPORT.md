# COMPLETION REPORT — TIP-035

**STATUS:** IMPLEMENTED LOCALLY / RELEASE NOT READY
**Date:** 12/08/2026
**Pre-commit QA build:** dirty candidate derived from `bbb671f9a0fe`

## Outcome

TIP-035 now provides one fail-loud release contract from the local candidate to
the company rollout. It does not claim production readiness: three of ten
preflight gates pass and seven remain explicitly blocked.

The local Ask runtime is again exact and operational. During browser QA, a real
regression was found in the previous claim renderer: keeping the quoted phrase
“Invent. Build. Prove.” atomic had accidentally merged every adjacent statement
sharing one citation. The logic now coalesces only while a quotation is still
open; independent claims remain separate and scannable.

## Files changed

- Created `vibecode_v2/TIP-035_ENTERPRISE_PILOT_CERTIFICATION_AND_PRODUCTION_CUTOVER.md`.
- Created `v2/scripts/verify-tip035-release.sh`: content-free, exact-build,
  ten-gate release preflight.
- Modified `v2/Makefile`: added `make tip035-preflight`.
- Modified `v2/scripts/local-demo.sh`: added a purpose-bound external corpus
  export guard before any pilot infrastructure or semantic reindex is created.
- Modified `v2/apps/web/src/app/(shell)/ask/page.tsx`: narrowed repeated-citation
  coalescing to an unclosed quotation instead of all same-source claims.

## Verified results

- Answer runtime: PASS — external provider, OpenAI embedding 1536, routine
  reasoning low, policy/credential loaded, grounded answering ready and exact
  pre-commit build identity. The post-commit SHA must be rebuilt and verified
  before external certification.
- Enterprise inventory: PASS — digest
  `e14d045079a40f22003a1348358c1c81abdb0d403d2b48a5322309c46bc86274`.
- TIP-034 definition: PASS — immutable 27-case campaign; truthful result
  `not_started`, sample 0.
- External guards: PASS SAFE — TIP-033 and TIP-034 both exit 2 before network
  without their independent approvals.
- Pilot corpus export guard: PASS SAFE — exits 2 before infrastructure when an
  OpenAI embedding profile lacks `PILOT_APPROVE_EXTERNAL_CORPUS=1`.
- Backend: Ruff PASS; mypy PASS on 141 source files; 635 passed, 128 conditional
  skipped.
- Web: ESLint PASS; TypeScript PASS; 191/191 unit tests PASS; production build
  PASS.
- Browser/accessibility/responsive: 126/126 PASS after the claim-boundary root
  fix and runtime rebuild.
- Migration graph and image/runtime policy: PASS.
- `git diff --check`: PASS.

## Current preflight

| Gate | Result |
|---|---|
| Migration graph | PASS |
| Exact running runtime | PASS |
| Connector boundary — zero active | PASS |
| Clean committed candidate | BLOCKED — current changes are uncommitted |
| Isolated canonical pilot database | BLOCKED — `.env.pilot` absent |
| TIP-033 five-case latency recertification | BLOCKED — no fresh report |
| TIP-034 27-case usefulness GO | BLOCKED — `not_started`, 0/27 |
| Production configuration | BLOCKED — `.env.production` absent |
| Target hardened/load/restore/rollback drills | BLOCKED — not attested |
| Homeowner GO | BLOCKED — not recorded |

The machine-readable local report is generated at
`/tmp/tip035-release-preflight.json` and contains no question, answer, evidence
or secret value.

## Deviations and constraints

- No isolated quality pilot was created because semantic reindexing would send
  the governed corpus to the configured embedding endpoint. The general TIP-035
  implementation approval was not widened into that disclosure permission.
- No TIP-033 or TIP-034 live campaign was run. Their scopes remain separately
  approval-bound.
- No production env was fabricated. Corporate OIDC values, TLS origin and real
  separated secrets must be supplied by the deployment owner.
- Initial Playwright launch inside the macOS sandbox was denied by the OS. The
  same suite was rerun with approved browser execution and completed 126/126.
- `../_to_delete/` is user-owned and untouched.

## Next operator actions

1. Commit the TIP-035 implementation and rebuild so the candidate identity is a
   clean immutable SHA.
2. Approve and create the isolated quality pilot corpus/index, or provide an
   already approved equivalent pilot snapshot.
3. Run TIP-033, then only if it passes run TIP-034 and collect human ledgers.
4. Provide `.env.production` through the approved secret channel and run target
   hardened/load/restore/rollback drills.
5. Record Homeowner GO only after every prior gate passes.
