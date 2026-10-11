# R22 focused offline scan and next-design recommendation

2026-10-09 · Builder · Vibecode v6.2 · Evidence diagnosis, not a product fix.

## Observations and scope

The source-bound R21 OFF population remains qualification FAIL: 1,440 observed
of 1,600 requested, 1,353 successful, 87 HTTP503 `action_operation_timeout`, 160
missing status/cancel descendants and 10/16 passing cells. No client exception
rows. Exact missing cases descend from 80 failed c50 submits. All 1,440 raw IDs
join uniquely to middleware IDs/statuses; complete stderr also contains three
seed audit events. No absolute per-request start timestamps or internal SQL,
checkout, audit or commit/cleanup phase times exist. Completion line order cannot
recover overlap or pure queue wait. No causal bottleneck is measured.

| Cohort | Client p95 ms | Middleware p95 ms | Observed/errors |
|---|---:|---:|---:|
| c25 admission | 963.140043 | 950.51 | 100/0 |
| c25 cancel | 743.759833 | 730.30 | 100/3 |
| c50 admission | 1840.407626 | 1805.11 | 100/0 |
| c50 submit | 1126.457167 | 1080.73 | 100/80 |
| c50 status | 919.985417 | 872.95 | 20/1 |
| c50 cancel | 997.366709 | 969.22 | 20/3 |

C25 cancel failures are cases70/72/74. C50 submit failure counts in ordinal
bins0–19/20–39/40–59/60–79/80–99 are19/18/19/17/7; these are case identifiers,
not measured time windows or early/late overlap. C50 status fails case31;
cancel fails14/31/33. All failure timings stay in every quantile. C50 status/
cancel p95 describes only the20 observed rows, not the missing population.
Top-five observed rows per cell are deterministic client-time-descending,
case-ID tie-break; selection is not a replacement SLA population.

Client timer surrounds the ASGI client request and stops before JSON parsing/
journal flush (`latency_probe.py:60–65`). Middleware starts before call_next,
logs a rounded duration once response is returned, then returns that response
(`api/main.py:88–113`). Paired differences compare different response boundaries,
not a measured overhead phase. For c50 admission the largest paired difference
is134.595417ms; this does not justify subtracting any latency. Distinct nearest
quantiles are not paired differences. The .9s timeout outcome is not equivalent
to client elapsed>900ms, nor to the1,000ms cell threshold; admission's limit is500ms.

## Source-derived await topology (not R21 phase measurements)

Stack: Python/FastAPI/SQLAlchemy asyncpg/PostgreSQL; scoped original synthetic
subject override, real router/service/policy/UoW and default cached factory.
No new broad health or runtime checks were run. Pertinent source is covered by
the full product/test binding, not an inferred Git/image fingerprint.

| Operation | Nominal source path and awaited boundaries |
|---|---|
| Admission | `actions/api.py:103–113` calls perform without the executor .9s timeout. Eligible R0 path `service.py:546–576,578–699` reads fresh actor/payload/source on initial phase; checks initial phase in; takes a new mutation lease, maintenance/key/input locks, stages rollback-local root, audit fence then NEW checkpoint, append, commit; final metadata TX freshly validates digest/current authority after commit (`716–755`). Two physical checkouts, three fresh logical phases on supported path. Clock/topology fallback may instead use the whole old path; actual R21 branch frequency is unobserved. |
| Submit | `execution_api.py:25–40` times perform AFTER dependencies. `execution.py:160–259` initial plan/current source validation; mutation locks plan/execution, maintenance and fresh post-wait snapshot. New insertion takes audit fence before immutable created_at/deadline (`267–302`); atomic append then commit. Final row/receipt reads use retained free carrier with NEW logical TX. Two nominal physical leases/three logical phases, not one long permission TX. |
| Status comparator | Trusted default origin `execution.py:331–386` uses one RequestConnection read phase with current subject, execution row and receipts: three explicit application SQL calls/one checkout. Fallback keeps original separate reads. `db/engine.py:38–83` and exact method/factory identity gates forbid arbitrary injection/cache repair. Actual phase durations are absent. |
| Cancel | `execution.py:97–113,388–409`: current actor projection, owner-row read, UoW mutation/maintenance, execution FOR UPDATE, receipt existence, update/event, commit then fresh final row/receipt view. Nominal queued case: ten explicit application SQL calls across four lazy factory checkouts, excluding BEGIN/COMMIT/ROLLBACK/pre-ping. No global827004 audit append here. Terminal cases can do less work. It does not use RequestConnection's joined-terminal protocol; standard AsyncSession context behavior must not be silently equated to it. |

Shared input fence: `checkpoints.py:19–62` locks actors then capability/template/
source/evidence witnesses; metadata is separately read at65+; policy checkpoint
projects statement-time authority (`policy.py:122–159`). `_snapshot` orders those
locks, optional rollback-local stage, audit827004, THEN fresh locked checkpoint
(`service.py:318–352`). Audit append repeats827004 and reads anchor/appends
(`repositories/audit.py:107–140`); SQL append function also locks/checks anchor
(`0004_append_only_audit.py`). Same-transaction lock reacquisition is reentrant,
not three independent audit-lock wait episodes. Pool-held mutation serialization
is plausible but unmeasured; cancel's timeouts cannot alone prove audit causality.

Ownership: `request_connection.py:558–635` assigns a new generation/session per
phase; successful mutation retains only a transaction-free physical carrier for
final reads. Initial checks in first; final terminal work closes exact carrier.
`348–381,399–428,473–527` join shielded terminal tasks, preserve cancellation and
poison uncertain cleanup. Commit is separately awaited by transaction exit, not
claimed shielded merely because close is joined. Timeout cancellation waits for
awaited unwind/terminal work before translation to503; elapsed may exceed .9s.
Pre/post-commit uncertainty cannot grant replay/fallback or suppress final denial.

Static regression source witnesses (not fresh R22 runtime tests): two leases/
three TX and lock release `test_action_two_lease_review_integration.py:205–219`;
fresh retained-final concurrent cancel `223–259`; repeated-cancel joined cleanup,
no final/replay `522–596`; timeout waiter cleanup `test_action_execution_unit.py:66–81`.
Source/ACL/role/digest refresh, durable receipt/idempotency and audit chain remain
invariants; no proposed cache or removal of post-wait authorization.

## Options and selected smallest next design

| Option | Benefit/hypothesis | Unproved risk / disposition |
|---|---|---|
| Retain current / diagnosis only | Preserve all semantics; current failure honest. | No attribution or SLA improvement; baseline/fallback remains this source. |
| Scoped cancel owner-read fusion | Reduce nominal4 checkouts/10SQL toward trusted current-owner/read fusion. | Doesn't explain or fix admission500ms tail or submit80 timeouts; must preserve current actor/owner privacy, fresh row lock and final view. Not selected before phase proof. |
| Audit round-trip reduction | Potentially shorten serialized admission/submit section. | No measured audit wait; removing reentrant calls is not removal of separate waits. Chain atomicity, fence-before-fresh-checkpoint and post-wait ACL invariants make speculative tuning unsafe. Not selected. |
| Minimal experiment-only phase attribution | Distinguish acquisition, initial, mutation/fence/append, commit and terminal/final regions while preserving current product. | Observer perturbs scheduling; not OFF qualification or causal speedup. Selected as next DESIGN only. |

Selected design is a separately gated, default-OFF experiment observer, not
implemented or admitted here. Task-local request ID/op plus generation identity,
monotonic entry/exit/outcome only; no content, SQL text, tokens or authority
cache. Sanctioned RequestConnection phase/acquisition/terminal boundaries and
explicit snapshot/audit/transaction boundaries may be observed transparently.
Do NOT wrap `ActionPolicy.current`: its __func__ identity is part of trusted
status admission; changing it silently invokes fallback. Do not change factory
identity/type/options, service overrides, transactions or pool size. Observer
must prove selected path/checkout/SQL-count topology identical to original.

Acquisition span includes queue, pre-ping/connection establishment and scheduling;
cannot be labelled pure pool wait. Snapshot and audit spans overlap/nest; repeated
audit lock acquires inside one TX are labelled reentrant. Report interval unions,
nesting and unobserved residual rather than adding inclusive spans into a fake
critical path. Cancel legacy contexts need explicitly labelled boundaries, not
invented RequestConnection generations. No generic all-callback framework.

Disconfirming predictions: if acquisition is not dominant for failing/tail IDs,
reject pool-queue dominance; if mutation/audit region isn't dominant, reject audit
tail dominance; if terminal/post-commit spans are small, reject cleanup as main
explanation. Overlap does not uniquely attribute SQL versus event-loop/host effects.
Compare request/outcome/cell/missing IDs without adjusted SLA. Preserve actual
unknowns where nested/fallback spans cannot close conservation.

Future proposal ceilings, NOT new authority: original source/driver/oracles and
finite profiles/cases remain fixed if Main admits a diagnostic capture; maximum
one190s child including seed, shared10s ownership cleanup,10MiB retained raw,
<=64 boundary records/request and<=1,600 requested observations; no retry or
observer-OFF certification from observed run. Failure/malformed/missing/cap stops
retain all data. Before any runtime: prove original args/results/errors/cancel
transparency, no extra await/checkout/TX/replay, matching topology, default-OFF
and rollback restoration with the existing exact regression seams. Main and
independent review must approve an exact next TIP and finite allowance first.

## Preservation and limits

New stdlib analyzer (approximately215 lines), five pure controls and compact
JSON only; no application/helper imports, SQL/Docker/signals/load/native/provider,
Git/install/build or project copy. Historical R12/R16/R17 signals were not used as
R21 measurements. Linked bindings preserve full current product204/tests192,
R21source23/seal222 and prior R20/R19/R18 inventories, plus final R21 Verify,
review, closure and publication-check bytes. Current mutable publication is not
recursively frozen by old status hashes. Read/hash declared inventory before
and after, input cap32MiB/output cap128KiB; malformed/ambiguous raw fails loud.

R22 diagnostic completion cannot close EXE-009: OPEN/P1, candidate NOT_READY,
serving executor OFF, TIP-054.5 BLOCKED. A source change or new capture remains
a separate decision. Main/Reviewer independently verify the final packet.
