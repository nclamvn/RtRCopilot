# TIP-022: Recovery Gate & Runtime Convergence

## HEADER

- TIP-ID: TIP-022
- Project: RtR Copilot V2
- Module: Delivery integrity, runtime readiness, repository hygiene
- Depends on: TIP-012, TIP-013B, TIP-015, TIP-016, TIP-017, TIP-019
- Priority: P0
- Issued: 2026-08-04
- Baseline commit: `0d8f9e0392dc9dc1eb23e7a8befcb53bda4933da`
- Status: VERIFIED (2026-08-04)

## CONTEXT

- Working directory: `/Users/os/RtR/KnowledgeBase/RtR_Copilot`
- Application root: `v2/`
- Project X-ray: `PROJECT_XRAY.md`
- Continuation plan: `vibecode_v2/04_CONTINUATION_PLAN_2026-08-04.md`
- Existing patterns: typed FastAPI health models, Next.js ingress-safe status route,
  Docker Compose health checks, Vitest, Pytest, Playwright and Vibecode reports.

The 2026-08-04 X-ray found a healthy CI baseline but a locally divergent state:
the running Web image was older than HEAD, the worker was not running, local
`make verify` failed only because its Docker fallback did not mount `v2/eval`,
and one current-source browser test used an ambiguous heading locator. The
repository also tracked a generated demo environment file and a large recovery
directory. No feature TIP may proceed until this recovery gate is independently
verified.

## TASK

Restore a reproducible, evidence-bearing delivery baseline in which source,
tests and running services converge on the same Git revision. This TIP is a
recovery/operability change only; it must not alter product authorization,
database schema, retrieval semantics or user data.

## SPECIFICATIONS

### REQ-022-01 — Reproducible local verification

The no-`uv` Docker fallback in `scripts/verify-scaffold.sh` must mount the full
repository so backend tests can access both the sibling `eval/` fixtures and
the frozen `phase1_pilot/` parity source. The
fallback must remain isolated in a pinned Python image and use the locked Python
environment.

### REQ-022-02 — Deterministic browser suite

Every browser locator must resolve uniquely and asynchronous UI assertions must
wait for the terminal state rather than an initially-disabled loading control.
Shell-only browser tests must mock authorization-sensitive capability probes so
they cannot inherit state from an arbitrary local API. Correct these race and
isolation defects without weakening their semantic intent.

### REQ-022-03 — Operational readiness

Keep `/health/ready` as the API dependency/readiness contract. Add an
operational health endpoint that also requires a fresh worker heartbeat. The
browser-facing `/api/status` must consume only the aggregate operational result
and must not disclose internal service names or topology.

### REQ-022-04 — Build identity convergence

API and Web must receive `RTR_BUILD_SHA` at runtime. The operational endpoint
must report the API build SHA; the Web status route must fail closed with
`version_mismatch` if its own SHA differs. Local Make workflows must derive the
value from Git unless explicitly supplied.

### REQ-022-05 — Repository hygiene

- Stop tracking generated `v2/.env.demo`; preserve a local ignored copy for the
  active demo and provide a safe template instead.
- Remove the tracked `_to_delete/` recovery tree after inventory. History
  remains recoverable from the baseline commit.
- Do not commit real credentials, API keys or runtime secrets.

### REQ-022-06 — Evidence and paper trail

Reconcile the task graph with the current state and document the otherwise
unpackaged CI stabilization work represented by TIP-020 and TIP-021. Produce a
Builder Completion Report and an independent Contractor Verify Report.

### REQ-022-07 — Current vulnerability baseline

Resolve any fixed HIGH/CRITICAL vulnerability detected by the current Trivy DB
through a locked dependency update. Do not suppress a finding with an allowlist
when a compatible fixed release exists.

## ACCEPTANCE CRITERIA

| AC | Given | When | Then |
|---|---|---|---|
| AC-022-01 | Host has Docker and no `uv` executable | `make verify` runs | Full Web, backend, Compose, vulnerability and integration gates pass |
| AC-022-02 | Current source build is served | Playwright suite runs | 88/88 tests pass and axe critical/serious count is zero |
| AC-022-03 | API and worker are started | Operational status is requested | HTTP 200, worker heartbeat is ready and topology remains private at Web ingress |
| AC-022-04 | API and Web are built from one revision | `/` and `/api/status` are queried | Both report the same non-placeholder Git SHA |
| AC-022-05 | Worker is healthy | `POST /system/ping` runs | A correlated `pong` is returned with HTTP 200 |
| AC-022-06 | Repository is scanned | tracked paths and secret patterns are audited | No generated `.env.demo`, runtime secret or `_to_delete/` recovery tree is tracked |
| AC-022-07 | Recovery change is reviewed | migrations and protected product behavior are compared | No schema, auth/policy or retrieval behavior change is introduced |
| AC-022-08 | Resulting commit is published | GitHub aggregate Verify completes | Required workflow is green for the resulting revision |

## CONSTRAINTS

- No database migration.
- No new product feature, dependency or provider.
- Do not change `/health/ready` semantics.
- Do not expose dependency names, hostnames or credentials through Web status.
- Do not rotate the active local SOT signing key inside this TIP; untrack it and
  record that any key reused outside local development must be rotated.
- P0/P1 failure means STOP; TIP-018 remains blocked.

## VERIFY COMMANDS

```bash
cd v2 && make verify
cd v2 && pnpm exec playwright test
curl -fsS http://127.0.0.1:18000/
curl -fsS http://127.0.0.1:18000/health/operational
curl -fsS http://127.0.0.1:3000/api/status
curl -fsS -X POST http://127.0.0.1:18000/system/ping
git ls-files | rg '(^|/)\.env\.demo$|^_to_delete/'
```

## REPORT FORMAT

Create `TIP-022_COMPLETION_REPORT.md` and `TIP-022_VERIFY_REPORT.md` using the
Vibecode standard. Every acceptance criterion must link to command output or a
test assertion. Deviations must carry a REQ-ID and owner.
