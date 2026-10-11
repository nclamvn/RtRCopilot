# R23 focused scan and prospective attribution contract

2026-10-09 · Builder · Vibecode v6.2.
Scoped design READY-with-deferred; **complete capture admission HOLD**.
No observer is installed and no application/helper is imported or executed.

## Scope and source witnesses

R22 is closed as offline diagnosis, not a repaired qualification. R21 remains
FAIL/P1: 1,440 observations, 87 timeouts, 160 missing descendants, 10/16 passing
cells. Unchanged source is Python/FastAPI/SQLAlchemy asyncpg/PostgreSQL with
default cached pool 5+5/pre-ping. Existing source/evidence hashes anchor this
report; model counters are not measured R21 SQL/checkouts or future runtime proof.

| Operation/path | Source seam and source-derived topology |
|---|---|
| Admission: standard R0 new plan | `actions/api.py:103–113`; `service.py:546–699,716–755`; two physical leases / three fresh logical phases. No executor .9s route timeout. Initial checks in; mutation commits; final authority/disclosure is freshly read on transaction-free retained carrier. |
| Submit: standard new queued execution | `execution_api.py:25–40`; `execution.py:160–302`; two physical leases / three fresh logical phases. Timeout starts after dependencies and surrounds perform/unwind. No native dispatch. |
| Trusted status comparator | `execution.py:331–386`; three explicit app SQL / one checkout. Exact service/policy/factory origin and `ActionPolicy.current.__func__` must remain untouched. |
| Ordinary queued cancel | `execution.py:97–113,388–409`; ten explicit app SQL / four lazy contexts. No global audit append, no RequestConnection generation. Terminal/legacy/fallback alternatives are not silently admitted to this nominal model. |

`RequestConnection.phase_lease:563–613`, read/mutation contexts614–635 and
joined terminal348–381/399–428/473–527 expose prospective phase/acquisition/
terminal regions. Each new logical phase has fresh generation/session; mutation
retains a free physical carrier only. COMMIT is separately awaited, not claimed
shielded by joined close. Repeated cancellation may extend unwind; .9s timeout
outcome is not a client elapsed threshold or a cleanup-time measurement.

Snapshot `service.py:318–352` orders input locks (`checkpoints.py:19–62`),
optional own-root stage, audit827004, THEN new metadata/checkpoint. Append
`repositories/audit.py:107–140` and migration0004 repeat the same TX audit lock;
reentrant reacquisition is not three independent waits. Fresh actor/ACL/source
authority, chain atomicity, idempotency, deadlines/budgets/cancel/receipt history
and fresh post-commit final disclosure are unchanged invariants.

## Closed prospective event contract

Fixed ASCII frame, no escaping/free text/SQL/content/token/actor identifier:

```text
ssss|o|p|hh|g|c|e|ttttttttt|r|x\n
```

Ten unsigned integer fields, widths4/1/1/2/1/1/1/9/1/1; nine separators plus one
newline: **32 bytes exactly**, including every begin/error/cancel/incomplete
frame. Schema in `model.py`: slot0–1599 encodes fixed profile/case/operation order;
operation/path0–3 must equal slot modulo4; phase0–15 is closed to exact per-path
plans; generation0–3, context0–4; edge0 enter/1 terminal; campaign-relative integer
microseconds0–199,999,999. Clock overflow rejects attribution, not clamped time.
Outcome0 begin/1 okay/2 error/3 cancelled/4 incomplete; error0 none/1 ordinary
error/2 terminal error/3 unknown bounded error class. No traceback is serialized.

For RequestConnection paths, generation1 initial/2 mutation/3 final and context
ordinal match the logical phase, not physical PID/checkout count. Cancel always
uses generation0 and context1 current/2 owner/3 mutation/4 final: context labels,
never fabricated private generations. Phase meanings are operation/context-bound:

- 0 whole service; 1 initial/current/owner read; 2 acquisition composite;
  3 initial/ordinary read terminal; 4 mutation region; 5 input/run-row fences;
  6 first audit fence; 7 fresh checkpoint; 8 append; 9 commit exit;
  10 mutation Session terminal; 11 fresh final read;
  12 final Session terminal/commit exit; 13 final physical terminal.
- Cancel has no phases6/7/8 audit instrumentation. Admission final phase7 is
  fresh authority; submit final row/receipts does not invent that extra checkpoint.
  Phase12 admission can include final read-TX commit; submit/status/cancel context
  close is not mislabelled a COMMIT merely because it is a terminal event.

One entry/terminal pair per admitted semantic span, never per SQL callback,
shield retry or cancellation delivery. Plans have16/15/4/15 spans respectively;
at most32/30/8/30 frames per operation slot. Every observed terminal outcome is
retained. Repeated deliveries use one terminal presence outcome and explicitly
mark partial coverage/fault05 HOLD; delivery count/timing is NOT measured.
Unknown branches, additional span invocation or capacity/clock overflow reject
the whole retained input, not trim/drop/dedupe it. Future runtime failure retention
and stop behavior remain unimplemented and require separate proof/admission.

Framing includes exact JSON manifest/header, fixed1,600-character coverage vector
(C complete/F error or cancelled partial/I incomplete/N unlaunched), one fixed
14-byte fault frame and12-byte count/verdict trailer. Unpaired enter remains
stored with I; no endpoint timestamp is fabricated. Unvisited/error/cancel spans
are explicit F/HOLD, not successful zero time. Missing descendants cannot be
inferred from this phase model alone: original driver IDs/outcomes must later
validate N coverage. Header/trailer/count/coverage mismatch rejects the packet.

Union of child intervals is taken within actual complete service/context bounds;
initial/mutation/final main intervals may not overlap as one TX. Inclusive spans
are nested, not added; residual is unobserved service time, not an invented SQL,
pool or scheduler phase. Complete F/I requests never get fake residual closure.
Acquisition includes queue/pre-ping/connect/scheduling, not pure queue. No p95
sum or subtraction-adjusted SLA; ON diagnostics never certify mandatory OFF.

## Exact observer budget versus unproved total

The32-per-slot capacity allows51,200 records, but closed topology permits only
**40,000 reachable events**:400 slots per operation ×(32+30+8+30). All complete
paths attain this worst case in a memory-only control. Failed/incomplete traces
cannot add new pairs; one reserved fault frame has the same size on every outcome.
Manifest/header177 bytes, slot line1,607 bytes, fault14 and trailer12:
**1,810 framing + 40,000×32 = 1,281,810 observer bytes**. Fixed field widths include
maximum ordinals/timestamps/errors; no smaller normal-case encoding is assumed.

Original journal + final JSON, stderr/stdout, process/owner/supervisor and source/
contract/check/closure output need SEPARATE source-proved maxima. None is proved.
R21 actual size is historical; a2MiB reserve is not a future bound. Immutable
R19 supervisor writes direct files, polls cap every .02s and checks afterward
(`bounded.py:109–169`); overshoot can occur, so post-hoc cap STOP is not ex ante
fit proof. `budget.json` therefore keeps total unavailable and **capture HOLD**,
even when hypothetical caller declarations sum below10MiB. No cap change,
truncation, output trimming or retrospective permission is proposed.

## Transparency model, origin traps and pending proof

Pure synchronous `call_model` forwards exactly one original call with untouched
args/kwargs/result/exception identity. Default OFF does nothing to registry;
ON restores only its own reserved observer key, including pre-existing collision,
and preserves unrelated original effects on success/error/cancel. Synthetic
repeated-cancel bookkeeping and model call traces are tested; this is NOT async
coroutine/context, checkpoint, SQL/TX, physical checkout or cancellation proof.

Prospective seams exclude wrapping policy.current, changing service/factory
type/identity/options, new status instances/options, arbitrary SQL callbacks,
authority caches or permission-result reuse. Exact origin mismatch stays HOLD;
never accept a silent3/1→legacy path switch. Allowed semantic-boundary wrapping
may add syntactic awaits: intended no extra independent I/O/yield/task does not
prove actual suspension behavior. Exact scheduling/cancellation equivalence,
real branch/count topology and restoration require future runtime regression
proof before interpreting any phase observations.

Default remains OFF. Rollback means restore exact captured prospective seams
on success/error/cancel/incomplete exit; no fallback replay after mutation/commit
uncertainty. Acquisition/mutation/audit/terminal dominance predictions remain
falsifiable, not conclusions. Full span overlap can leave causal attribution
unresolved even after a future capture.

## Scoped readiness and next boundary

New artifacts are a small stdlib wire/topology model, six memory-only controls,
read-only linked preservation checker and this report. No product/helper import,
SQL/Docker/HTTP/campaign/signal/native/provider/network/Git/install/build/copy.
Initial model/control feedback is retained; no prior sealed artifact changed.
R22 full input20-entry evidence seal/final Verify/review/closure/publication-check
and complete current product204/tests192 sets are hashed before/after. Historical
published mutable status hashes remain point-in-time metadata.

Scoped design READY-with-deferred: original-output bound, real async/topology/
restore proof, essential terminal/fallback coverage and exact future capture
retention/admission remain pending. Select one narrow next task: prove a lawful
whole-original-output bound (or explicitly retain HOLD), without modifying the
immutable driver or granting a capture. Only Main may scope that work. Current
EXE-009 OPEN/P1, candidate NOT_READY, serving executor OFF, TIP-054.5 BLOCKED.
