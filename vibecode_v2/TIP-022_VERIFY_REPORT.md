# VERIFY REPORT — TIP-022 · Recovery Gate & Runtime Convergence

**Date:** 2026-08-04
**Verifier:** Contractor — independent rerun after Builder completion
**Implementation commit:** `597b2f244e7ac7bc1a0af699d7fb983599a3272d`
**Environment:** macOS host; Docker Desktop 29.4.0; GitHub Actions
Ubuntu 24.04; Next.js 16.2.11; Python 3.12.4; Chromium/Playwright.

## Verdict

**VERIFIED · RECOVERY GATE OPEN.** AC **8/8 PASS**. P0/P1 open: **0/0**.
TIP-018 may begin; TIP-014 remains built but unverified and follows TIP-018 per
the approved continuation sequence.

## Acceptance-criteria evidence

| AC | Verdict | Independent evidence |
|---|---|---|
| AC-022-01 no-host-`uv` verification | PASS | `make verify` used Docker fallback; 520 backend tests collected, `410 passed / 110 skipped`; final `VERIFY PASS` |
| AC-022-02 browser + accessibility | PASS | current-source production server: Playwright **88/88**; complete dark/light, vi/en and stateful axe matrix; critical/serious **0** |
| AC-022-03 operational readiness | PASS | `/health/operational` HTTP 200; PostgreSQL, Redis, object storage and worker all `ready`; Web response contains no topology |
| AC-022-04 build identity | PASS | Git, API `/` and Web `/api/status` all reported `597b2f244e7a`; mismatch unit test fails closed with HTTP 503 |
| AC-022-05 worker execution | PASS | worker container healthy; `POST /system/ping` HTTP 200 and correlated `status=pong` |
| AC-022-06 repository hygiene | PASS | tracked `.env.demo` / `_to_delete` paths = 0; added private-key/API-key pattern matches = 0; active ignored demo file retained locally |
| AC-022-07 protected boundaries | PASS | migration changes=0; auth changes=0; RAG/retrieval changes=0; existing `/health/ready` unchanged |
| AC-022-08 GitHub aggregate Verify | PASS | PR #2 run `30871684714`: migration, image-policy, backend, Web, load-smoke, stack, browser and aggregate verify all success |

## QA results

| Tier | Passed | Failed | Skipped | Status |
|---|---:|---:|---:|---|
| Tier 1 · AC/core health | 8 | 0 | 0 | PASS |
| Tier 2 · robustness/integration | 46 data integration + 88 browser | 0 | 0 | PASS |
| Tier 3 · security/accessibility | Trivy 0 HIGH/CRITICAL; axe 0 critical/serious | 0 | 0 | PASS |

Additional gates:

- Web ESLint and strict TypeScript: PASS.
- Web Vitest: 149/149; race-sensitive suite repeated successfully.
- Next.js production build: PASS.
- Backend Ruff: PASS; Mypy: 102 source files, no issues.
- Current Trivy DB initially found CVE-2026-69247 in cryptography 49.0.0;
  locked 50.0.0 rescan: 0 fixed HIGH/CRITICAL findings.
- Compose migration reversibility: nine revisions exercised.
- Containerized integration: 46 passed, 14 formats, 31 required outputs,
  18 runtime denial probes.

## Adversarial checks

- API healthy but worker absent: operational endpoint returns unavailable.
- API/Web build SHA differs: browser status returns 503 `version_mismatch`.
- Dependency detail present upstream: Web status strips dependency names.
- No host `uv`, host `.venv` contains stale container shebang: isolated verify
  venv prevents contamination.
- Capability request not mocked in shell E2E: reproduced session-loss race;
  hermetic mock closes it and full suite passes.
- Generated demo secret remains usable locally but is absent from Git index.

## Residual risks / deferred work

- The locally generated SOT signing key was deliberately not rotated because it
  signs the active local demo corpus. If it was ever reused outside local
  development, rotate it before any production-like pilot.
- Warning debt (non-blocking): Starlette TestClient/httpx deprecation,
  Alembic legacy path separator and SWIG type warnings. None affects TIP-022 AC;
  track during dependency-maintenance work rather than mixing into retrieval.
- Production HTTPS/OIDC deployment remains a production-like pilot concern,
  not a claim made by this local recovery gate.

## Sign-off

- [x] Tier 1: 100% pass
- [x] Critical issues: 0
- [x] P0/P1 open: 0
- [x] Local runtime converges with Git revision
- [x] Independent GitHub aggregate Verify passes
- [x] TIP paper trail complete

**Contractor disposition:** TIP-022 is complete. Proceed to TIP-018.
