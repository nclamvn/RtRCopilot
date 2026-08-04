# COMPLETION REPORT — TIP-022 · Recovery Gate & Runtime Convergence

**Date:** 2026-08-04
**Builder status:** DONE — Contractor VERIFIED
**Baseline:** `0d8f9e0392dc9dc1eb23e7a8befcb53bda4933da`

## What was built

### WP-A — Reproducible verification

- The no-`uv` fallback now mounts the full repository at `/workspace`, so the
  backend suite resolves both `v2/eval` and frozen `phase1_pilot` parity source.
- Its virtual environment is isolated at `/tmp/rtr-verify-venv`; a dedicated
  Docker volume caches only `uv` artifacts and avoids host `.venv` shebang
  contamination.
- The previously failing collection now reaches all 520 backend tests.

### WP-B — Deterministic UI gates

- The reopened-conversation heading locator now uses an exact accessible name.
- The research-denial unit test waits for its terminal denial message instead
  of passing prematurely on the initially disabled loading control.
- Shell browser tests mock the authorization-sensitive research capability,
  preventing an arbitrary local API session from changing the page under test.

### WP-C — Runtime/build convergence

- Added additive `/health/operational`: existing API dependency readiness plus
  a fresh Redis worker heartbeat and API build SHA.
- `/health/ready` semantics are unchanged.
- Browser `/api/status` consumes only aggregate state + build identity, hides
  dependency topology, and fails closed on API/Web SHA mismatch.
- Compose, Make, local-demo and deploy scripts now propagate `RTR_BUILD_SHA`.

### WP-D — Security and repository hygiene

- Trivy detected `CVE-2026-69247` HIGH in `cryptography 49.0.0`; the dependency
  and lock were upgraded to fixed `50.0.0`. No suppression was introduced.
- `v2/.env.demo` is now ignored and untracked but retained locally, preserving
  the active local signing secret. A secret-free `.env.demo.example` documents
  the generation workflow.
- Removed 902 tracked recovery artifacts (32,899,927 bytes) from `_to_delete/`:
  880 stale Git artifacts, 16 transfer bundles and 6 superseded TIP-011 files.
  They remain recoverable from baseline Git history.

### WP-E — Governance traceability

- Added the 2026-08-04 project X-ray and continuation plan.
- Recovered the missing TIP-020/TIP-021 CI traceability without falsely
  claiming retroactive TIP/Verify documents.
- Corrected task graph truth: TIP-014 is built but not verified; TIP-018 is
  unblocked by Docker and queued behind this recovery gate.

## Builder gate results

| Gate | Result |
|---|---|
| Web ESLint + strict TypeScript | PASS |
| Web Vitest | **149/149**, repeated after race fix |
| Next.js production build | PASS |
| Backend Ruff + Mypy | PASS · 102 source files |
| Backend Pytest (no host `uv`) | **410 passed / 110 skipped / 520 collected** |
| Trivy fixed HIGH/CRITICAL | **0** |
| Data integration | **46 passed**; migrations=9; formats=14; required outputs=31 |
| `make verify` | **VERIFY PASS** |
| Playwright + axe | **88/88**; critical/serious = 0 |
| Tracked `.env.demo` / `_to_delete` | **0 paths** |

## Deviations and issues resolved during build

- **DEV-022-01 (REQ-022-01):** mounting only `v2/` fixed collection but parity
  still could not see `/phase1_pilot`. Resolution: mount repository root.
- **DEV-022-02 (REQ-022-02):** a unit test raced on an initially-disabled
  control. Resolution: await the terminal denial message; 149/149 repeated.
- **DEV-022-03 (REQ-022-02):** one shell E2E inherited auth failure from an
  unmocked local capability endpoint. Resolution: hermetic route mock; isolated
  test 1/1 and full browser suite 88/88.
- **DEV-022-04 (REQ-022-07):** current Trivy DB introduced a fixed HIGH finding.
  Resolution: locked `cryptography 50.0.0`; rescan 0 HIGH/CRITICAL.

## Boundaries respected

- No database migration.
- No auth/RBAC/ABAC or retrieval behavior change.
- No user data reset or volume deletion.
- No runtime secret was printed or committed.
- `/health/ready` contract remains unchanged; operational health is additive.

## Handover to Contractor

Independently verify runtime build identity, worker heartbeat/system ping,
tracked-secret hygiene and GitHub aggregate Verify on the published revision.
