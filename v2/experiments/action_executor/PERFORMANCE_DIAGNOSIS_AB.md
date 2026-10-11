# TIP-054.4b admission performance: A/B refinement

Product r2 (`237b0a82b5769e402de7b26c2b17b8050f9b0f89aea94abada46b3321a4d8b68`)
failed the actual EXE-009 load gate. Neither failure is waived.

## Evidence

Original recorder rewrote its complete growing JSON array after each request on
the same event loop. Admission retained its actual isolated-runner benchmark:
139.65 MB cumulative rewrite, rewrite p95 9.82 ms versus bounded JSONL append
p95 0.152 ms. This observation is not a product latency exemption.

The identically profiled corrected-recorder run `latency_frozen_r3` still failed:
c10 admission/submit p95 488.1/626.8 ms passed; c25/c50 admission p95
1284.5/2547.2 ms failed, with all 100 submits at each high load timing out and
therefore no following status/cancel samples. Original and corrected observations
remain retained separately.

Root-approved finite SELECT-only diagnostic ran the real ActionService.read_plan
against retained synthetic r3 data, with PostgreSQL
`default_transaction_read_only=on`, equivalent serving pool size 5/overflow 5,
100 requests at each concurrency, no provider/worker and no source text or query
parameter output. Every request executed 64 SQL statements and 16 checkouts.

| Concurrency | elapsed p95 ms | cumulative pool acquisition p95 ms | cumulative SQL p95 ms |
| --- | ---: | ---: | ---: |
| 1 | 25.5 | 0.04 | 10.3 |
| 10 | 315.8 | 149.0 | 152.4 |
| 25 | 484.9 | 326.0 | 87.7 |
| 50 | 835.4 | 698.9 | 73.0 |

Columns are separately ranked distributions, not an additive decomposition.
Pool acquisition includes checkout/creation time. Read-only measurements do not
quantify write-lock attribution. They demonstrate repeated projection and pool
contention independent of audit/actor write locks. Top repeated statement families
were current identity, roles/groups/scopes/entitlements and inherited resource
attributes. The verification-only probe is `read_plan_probe.py`.

Source inspection identified an actor-wide transaction advisory fence for every
independent plan and a submit path calling validate_ready (two read_plan loops,
extra revalidation, contract-history mutations and audit), then another current
projection/final execution snapshot. Both amplify serving pool contention.

## Authorized repair A/B

A: universal actor/idempotency-key fence for every contract version; acquire it
before the existing actor-wide fence. Keep actor-wide serialization for legacy or
mixed contract plans and every supersedes ordinal. Independent v2 roots have no
actor-wide fence. Existing SQL uniqueness and idempotency-digest conflicts remain.

B: immutable plan metadata load, pre-bind executable/owner/expected-digest/build/
host-contract/schema/arguments checks, one complete current deterministic
revalidation, then locked contract-ready/current authority snapshot inside the
actual execution INSERT transaction. Audit actual admission only when INSERT
RETURNING succeeds. Do not mutate/reset contract history, cancelled execution,
deadline or charged budget. Explicit validate-ready behavior is unchanged.

Root did not authorize C (optimized v2 admission response), pool changes, general
ResourceRepository changes, caching/removal of authority, wider engine changes or
weaker 0.9-second API budgets. New source needs fresh correctness/performance
proof; r2 native/restore/load evidence cannot certify changed bytes.

## Candidate evidence (not acceptance)

Product candidate `fc011290b2522bf373944d8f6054ad22196f2ad19ded5bee868b3f9d00bde2d1`
passed the fresh separately owned admission suite 16/16 (27.99 seconds), all-app
Ruff 0/mypy 169 sources 0/exact imports and source/helper unchanged checks.
Existing 22+8 source tests were not edited.

Identical corrected-recorder `latency_ab_discovery_r1` still FAILS: c25/c50
admission p95 1027.7/2391.5 ms; c25 submit all100 passes at 518.6 ms, but c50
has36 submit timeout responses and only64 downstream status/cancel samples.
c1 submit p95 improves from105.5 to29.2 ms. All1528 append-only observations
match final JSON; source/helper unchanged. No load threshold/profile/budget was
relaxed. Next refinement requires Contractor authorization; broad/native/restore
campaigns remain withheld. C alone is not predicted to guarantee the target.

## Narrow C result and milestone stop

Contractor later authorized strict builtin v2 metadata-response C only: fresh
persisted view after insertion checkout closes, explicit immutable/host/schema/
input/build checks and complete same-session current metadata fence. Legacy and
mixed/unknown paths retain the existing read_plan. Product candidate is
`4c4463d2a35a035c1111189000bcaa131a6b1d43d56acae599a0795154b0f5f1`.
Fresh separate C18 passes18/18 (28.04 s); earlier14pass/4 draft-fixture failures
are retained and only the explicit draft-request fixture flag was repaired.

Identical observed C load still FAILS: c25/c50 admission p95 768.3/1511.3 ms,
c50 has67 submit timeout responses and only33 status/cancel samples. All1/10
operations pass; at25 submit/status/cancel all100 pass. All1466 JSONL observations
match JSON; source/helper unchanged. Thresholds, profile and finite API budgets
are unchanged. Contractor stopped product performance edits for this milestone.

Next proposed work is finite phase-correlated SQL/pool/lock measurements and
explicit query budgets before a separately approved request-local batching/
same-session-reuse design. No cross-request permission cache, loss of current
revocation/expiry/deny/lineage/purpose/build/fence rules, larger limits or general
repository/pool rewrite is authorized. Current candidate stays PARTIAL/NOT READY
with EXE-009 open; correctness/native/build campaigns do not waive performance.
