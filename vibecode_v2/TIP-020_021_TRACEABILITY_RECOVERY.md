# TIP-020 / TIP-021 — Traceability Recovery Record

**Recorded:** 2026-08-04
**Purpose:** restore the missing Vibecode paper trail for two already-merged CI
stabilization commits discovered by the project X-ray. This record does not
retroactively claim that a formal pre-build TIP or independent Verify Report
existed.

## TIP-020 — Pytest async-loop isolation

- Commit: `356f9aca83d65f6e06f95db6415c81dbb7ac0552`
- Change class: CI/test-harness fix
- Intent: prevent a session-level `asyncio.run()` from poisoning the
  function-scoped event loop used by `pytest-asyncio` tests.
- Evidence: the commit is included in baseline `0d8f9e0`; GitHub aggregate
  Verify run `30795005597` passed the backend gate at that baseline.
- Product/schema impact: none identified by the 2026-08-04 X-ray.

## TIP-021 — Compose stack readiness

- Commit: `f816dca322b3a5179de4acf0d69a1f7949309c2d`
- Change class: CI/orchestration fix
- Intent: wait for Compose service health before integration probes and make
  cleanup tolerant of partially created stacks.
- Evidence: the commit is included in baseline `0d8f9e0`; GitHub aggregate
  Verify run `30795005597` passed stack and browser gates at that baseline.
- Product/schema impact: none identified by the 2026-08-04 X-ray.

## Governance disposition

These numbers remain reserved and must not be reused. They are classified as
`RECOVERED / MERGED / BASELINE-VERIFIED`, not as fully documented feature TIPs.
TIP-022 introduces the missing source/runtime convergence and local fallback
checks so this documentation gap does not recur.
