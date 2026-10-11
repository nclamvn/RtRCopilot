# R19 focused source scan

2026-10-09 · Builder · Vibecode Kit v6.2 · source inspection only.

## Outcome

Reuse the original `r/run_phase_baseline.py` OFF branch and `latency_probe.py`
unchanged, behind a new finite ownership/retention wrapper. Do not execute the
historical R12 stage: it binds older product bytes, alters a shared role and lacks
the current owned-resource closure. No imports, tests, Docker, SQL, load, provider,
Git, build or original-source modification occurred in this scan.

R18 Main verifies 52 unique tests and 6/6 preparation criteria on the current
204-file product / 192-file test inventories. This is prerequisite correctness,
not HTTP acceptance. EXE-009 remains pending; R12 OFF FAIL remains preserved.
Serving executor OFF, broader candidate NOT READY and TIP-054.5 BLOCKED.

## Stack, path and current factory

Python 3.12 / FastAPI / httpx ASGITransport / PostgreSQL / SQLAlchemy 2.0.43 /
asyncpg 0.30.0. The configured strict mypy/Ruff backend health is separate from
this scan; no fresh health check was executed here.

The original baseline constructs `runtime_engine()` before running the helper
and asserts pool 5+5, pre-ping, 0.9-second timeout and quotas 5,000. The helper's
separate default seeding engine publishes one signed synthetic source and admits
`sot.read` v2. Its injected seed UOW is not a timed HTTP service factory. The
actual Action/Execution API dependencies construct default services, selecting
the canonical cached runtime factory; status uses the current R15 shared-pool
READ COMMITTED view without changing the writer. No extra pool warm-up or reset
should be added.

Only `file_subject` is overridden with the current synthetic subject. Real
middleware, rate limiting, routes, policy/current SQL authority and domain work
remain. This is local synthetic ASGI, not network/UI/OIDC/native-effect latency.

| Label | Actual route | Expected status |
|---|---|---:|
| admission | POST `/api/v1/actions/plans` | 201 |
| submit | POST `/api/v1/actions/plans/{plan_id}/execute` | 202 |
| status | GET `/api/v1/actions/runs/{run_id}` | 200 |
| cancel | POST `/api/v1/actions/runs/{run_id}/cancel` | 202 |

The OFF branch never imports/installs the phase profiler or launches its PG
monitor. No R12/R17 detailed, audit-tail, pool-boundary or lag observer belongs in
R19. Normal application logs/metrics and original HTTP timers/journal stay intact.
The API imports ordinary worker constants, but the helper does not start a worker.

## Retention and interpretation seams

- The HTTP-success timer ends before response JSON decoding and recording.
  Exception-path timing ends at the unchanged catch path. Semaphore waiting is
  excluded; acquired-case-slot contention is included. Do not homogenize these
  boundaries, subtract overhead or infer provider/production performance.
- HTTP status/`okay` is recorded before queued/spend/cancel body assertions. An
  assertion can abort gather after successful-looking records; zero process exit
  and complete original summary are mandatory in addition to raw cell arithmetic.
- Admission or submit error skips later operations. A status error still permits
  cancel. Fixed schedule identity is `(profile, case, operation)`, not seed UUIDs.
- Recording appends to the in-memory list before journal write/flush. A journal
  error can lead to a second record for the same slot; duplicates or JSONL/final
  JSON divergence must be rejected, not de-duplicated. A killed run may lack final
  JSON/summary or contain a partial trailing line; retain it and fail integrity.
- Raw rows do not preserve complete DTOs, `spent_tool_calls` or cancel flags.
  Those are enforced by unchanged helper assertions, not independently recreated
  from timestamps. Missing rows are unobserved, not zero-latency or proven rollback.

## Reusable proof and safe setup

Keep R18 source gate, fixture metadata/profile and repaired process ownership
patterns byte-bound. R18's supervisor fixes are relevant, but its hardcoded 120 s,
R18 paths and stop identity make direct unadapted execution inappropriate. A narrow
R19 adapter/copy is preferable to mutating imported R18 globals or adding hooks.

Proposed exact absent databases: `rtr_tip054_r19_local_e1` (domain) and
`rtr_tip054_r19_engine_e1` (engine), using existing `rtr_app` and
`rtr_tip054_engine` identities. The separate engine DB is an isolated settings
identity only; no system-schema initialization, SDK launch or engine connection.
No ALTER ROLE, Redis FLUSH, foreign DB deletion or fixture replacement. Main must
validate existing role/fixture premises and capacity before each CREATE.

Personally read hashes:

| Input | SHA-256 |
|---|---|
| Original latency helper | `e94a79a6b0f1695a23db07bfb5f12d5e5746f898893de9cf11cbb6527d6d4ad2` |
| Original baseline runner | `7e4a6136d6a21c2212d2971880644c65fb24472dc51276683b182becfe7711f7` |
| R18 qualification manifest | `bfd8104c2c35ee8832afa8cbc91f5f6a7c9bcf416afc8ba14ff18998851c158d` |
| R18 e3 source binding | `5bb847ef6bee176454cc14ae4bd35024b847aef8f969d7f12f0c877a87f7b0f5` |
| R18 Main final closure | `523e8b4d8bd329e3655f60cb69850de0efa2a0cc707b8e49d9c318d3f70c1822` |

Current product/test digests are attributed to R18 Main's fresh closure:
`b28e70d1905930fd517576b7df73edc6710cf4bae273f137da5e75ffd155c641` /
`5039c2a6a47fa1566f84b1acf766c5d212f731e6c9127aeec08576c7663fadc1`.
Future admission must validate the same explicit inventories before/after, plus
R18's 665 source and 385 raw pins. No historical serving-build attestation is
inherited. See the accompanying finite design proposal; no scratch was created.
