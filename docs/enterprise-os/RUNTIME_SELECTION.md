# ADR · TIP-054.4a durable runtime selection

Date: 2026-10-06. Status: **DBOS SELECTED for local TIP-054.4b integration;
READY-with-deferred, not application admission or production certification.**
Authority: approved TIP-054 Blueprint and
[bake-off instructions](../../vibecode_v2/TIP-054.4a_DURABLE_RUNTIME_BAKEOFF.md).

## Boundary

The experiment uses Python 3.12.4/Linux ARM64, actual `dbos==3.2.0`, actual
`temporalio==1.34.0` and Temporal CLI 1.9.1 / embedded Server 1.32.0. DBOS
stores engine state in a disposable PostgreSQL database; Temporal uses the
actual persistent SQLite CLI development-server profile. Both use the same
synthetic source, provider delay, finite parent budget and effect/receipt
oracles. This is not a production deployment comparison or a benchmark of
LLM/business-answer quality. Neither SDK is installed into the application.

The current application baseline is `0e88f48588dc3228f1ae9eca7a7597d96589af8b`
plus preserved uncommitted .1/.2/.3 changes, schema 0018. The experiment is
separate. No candidate SHA is invented for dirty source.

## Decision

Use DBOS 3.2.0 as the single durable owner of the **new** Action Kernel workflow
slice, conditional on serving dependency admission and the integration proofs
below. Keep existing pipelines unchanged. Temporal remains an alternative, not
a second concurrent owner. This selects a runtime, not Pydantic AI, MCP, a model
provider, production topology or a company-wide release.

Both candidates passed the finite source/native integrity tests. DBOS met the
agreed extra-p95 envelope at all four local loads in both retained orders;
Temporal missed at concurrency 50 in both. DBOS also fits the existing
PostgreSQL operating model without a separate orchestration-server component.
Component observations support that local choice, not a quantified total-cost
or production performance ranking. No correctness failure is waived for speed.

## Verified correctness

- DBOS native final r2: 9/9 pass. r1 has one retained failing test: a caller
  waiting on a synchronous workflow future did not return within 25 seconds,
  despite the engine persisting cancellation and the source having no effect.
  r2 observes the actual cancellation and source state before killing its
  owned waiter; it does not certify prompt synchronous caller termination.
- Temporal native r3: 9/9 pass, including real history replay, a materially
  distinct compatible implementation and rejection of an incompatible first
  command. Initial interrupted trials are not counted as results.
- Both recheck four distinct current approval/input/schema/ACL bindings after
  a durable wait and process death. Actual partial cancellation preserves the
  first effect/receipt and produces no second effect or false final success.
- Joint finite restore passed: DBOS logical PostgreSQL dump/restore preserves
  engine row fingerprints plus source snapshot; Temporal stops and restarts
  the actual CLI server after byte-identical engine/source SQLite restoration.
  The same pending workflow resumes with one effect, one receipt, spent=1.
  This is not live-safe upgrade, whole-cluster/roles restore or production DR.
- A two-process source fence test passed for each SDK: the obsolete worker
  cannot return the newer owner's receipt or publish a stale effect.

- Two complete matched matrices each pass **63/63 source-oracle profiles**:
  17 scenario profiles per branch and four loads per branch. Each matrix has
  1,200 timed load samples, 100 per engine/load cell. These repeat the same
  coverage; 2,400 samples are not 2,400 unique product tests.
- Real process kills cover before dispatch, during work and after known effect
  before receipt. Known effects reconcile; an unsupported after-effect/ack gap
  keeps one effect/one charged attempt and returns `needs_review`, not a retry.
- Contractor independently validated both raw matrices, reran DBOS's nine
  native proofs in a fresh namespace and ran all 14 unit/oracle cases. Source
  digests, negative tampering/false-success tests and paired quantiles pass.
  Independent full-matrix order is Temporal → DBOS → direct, reversing the
  first matrix's direct → DBOS → Temporal. Neither overwrites the other.

## Measured local performance and burden

Paired per-case engine-minus-direct **service-slot** extra p95, milliseconds:

| Concurrency | DBOS first | DBOS reverse | Temporal first | Temporal reverse |
|---|---:|---:|---:|---:|
| 1 | 7.734 | 7.908 | 139.572 | 140.714 |
| 10 | 232.374 | 194.113 | 241.201 | 231.134 |
| 25 | 751.272 | 644.246 | 594.564 | 494.497 |
| 50 | 829.803 | 816.565 | **1,178.849 FAIL** | **1,065.760 FAIL** |

Target ≤1,000 ms; each cell has 100 retained samples and nearest-rank
quantiles. Queue delay and cold startup/recovery are excluded from this metric
and retained separately. Common synthetic source/10 ms provider work occurs
in both paired branches. p50/p99 and absolute service times remain in raw data.
One local ARM64 four-CPU runner/two-CPU PostgreSQL fixture and Temporal's CLI
development SQLite profile are **not production-equivalent storage topologies**.

Five one-second native-wait idle observations: DBOS SDK parent 76,756–76,868
KiB/9 threads; Temporal SDK parent 74,688 KiB/10 threads; separate Temporal CLI
server 305,412–307,480 KiB/10 threads. PostgreSQL process-RSS sum 103,612 KiB
double-counts shared pages. Co-resident container working sets include tmpfs
packages/history and cannot be attributed as candidate totals. Sampled RSS
is not true peak/unique memory; short idle observations are not sustained CPU
or steady-state cost guarantees. Logical rows/database sizes and lagging PG
tuple counters are not physical writes/WAL amplification, dollars or LLM cost.

## Required integration follow-through

Application integration (.4b) must test the serving dependency pins rather
than assume compatibility with the separately resolved experimental stack.
Experimental SQLAlchemy 2.1.3/psycopg 3.3.6 differ from serving 2.0.43/3.2.9.
Use current Action Kernel authorization and receipts, not this synthetic
source as a product implementation. The application response path must not
block on a synchronous workflow future; cancellation acknowledgement,
actual terminal status and already-completed effects are distinct states.
The retained DBOS native-r1 timeout caller failure is **not fixed by changing
the observer**: cancellation state persisted, but its synchronous future did
not return within 25 seconds. Native r2 and the independent rerun establish
cancelled state/no effect before supervisor kill, not prompt caller termination.
Bounded async status delivery, waiter cleanup and accurate partial-cancel UX
are mandatory .4b gates before integrating the runtime with the response path.
Multi-host failover, queue recovery ownership, active-workflow migration,
real adapter effects and operational recovery remain separate proof gates.

Public SDK license/package hashes and the point-in-time OSV package query are
retained. An empty advisory response is not a security certificate for the
CLI binary, container OS, serving dependencies or enterprise deployment.

## Evidence

[Retained local evidence](../../v2/experiments/durable_runtime/raw/dev2/)
contains actual command/PID/exit records, SDK states, exported Temporal
histories, source snapshots, pins and the failed DBOS timeout trial.
Environment interruption is recorded separately: Homeowner confirmed Docker
was being restarted. Lost tmpfs trials are explicitly unavailable and are
never promoted as reproducible successes.

[Combined gates](../../v2/experiments/durable_runtime/raw/dev2/combined-gates.json)
bind the native, restore, fencing, resource and both measurement artifacts.
Historical per-matrix source-only indexes intentionally do not certify native
proofs or selection; final selection lives here and in
[Contractor Verify](../../vibecode_v2/TIP-054.4a_VERIFY_REPORT.md).
Digest links detect bundle changes, not an external signature/trusted timestamp.
