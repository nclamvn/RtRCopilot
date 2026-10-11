# R18 focused scan — whole-candidate local qualification planning

2026-10-09 · Builder · Vibecode Kit v6.2 · source inspection only.

## Outcome and scope

Prepare a frozen, finite admission packet before any further runtime work. No
Docker, SQL, tests, collection, load, providers, Git commands or product edits
were performed in this scan. This report is a proposal, not admission or proof
of passing tests. Preserve every prior source epoch and failed packet.

The current candidate remains NOT READY; the shipped executor default remains
OFF and TIP-054.5 remains blocked. R17's 44 passing correctness tests and one
domain-level status campaign do not close the broader HTTP gate. R12's mandatory
observer-OFF run still records 10/16 passing cells, 84 errors and 144 missing
downstream observations; its different-source failure remains unresolved, not
replaced by R17's minimal-observer results.

## Source and reusable structure

- Backend: Python 3.12, FastAPI, PostgreSQL, SQLAlchemy 2.0.43, asyncpg 0.30.0,
  DBOS 3.2.0, Redis and synthetic object storage. Pytest 8.4.1, strict mypy and
  Ruff 0.12.9 are configured; whole-application health was not checked here.
- `v2/apps/backend/src/rtr_copilot/actions/`: create/admission in `service.py`,
  submit/status/cancel in `execution.py`, bounded HTTP routes in
  `execution_api.py`, generation/cleanup ownership in `request_connection.py`.
- `db/engine.py`: canonical pool size 5, overflow 5, pre-ping; the R15 private
  status factory is a cached READ COMMITTED engine view sharing the original
  pool. Origin/configuration rejection remains explicit; the writer is unchanged.
- `v2/experiments/action_executor/`: unchanged `latency_probe.py`, original
  `r/run_phase_baseline.py`, historical R12 stages and the guarded R17 fixture
  harness. Tests are under `v2/apps/backend/tests`; R12's retained control is
  selected externally through `/work/r12`.

Main's final R17 whole-product content fingerprint is
`4a0bb4921ed0e310e6064070d945aab16837ab3de5ac525eb14bc15f8fc88708`.
This scan does not independently recompute the whole-product fingerprint or
attest a serving build. Fresh admission must recompute it using the same scope.
Focused source hashes personally read in this scan:

| File | SHA-256 |
|---|---|
| `actions/service.py` | `9dc555f120d6377b37cd50f1358d778b17de9c69df9cc4064b18f8d9a0cda0bf` |
| `actions/execution.py` | `fc4387e402115e4aa6278e8a3ecae43601212a473ffd3c382e097d664b3e8d55` |
| `actions/request_connection.py` | `c56d7b09a9845cfe23e4f580849f355c32a40366fd6abc22260f8e85210b93d0` |
| `db/engine.py` | `53a7a8d09513f913b4d05fbeb691184078966d61db94f495096308f69540e2dd` |
| `config.py` | `22baea3da59116804cfd5349c42b78f5b859bc9ef52add4620c956420d50d5e6` |
| `actions/execution_api.py` | `9fc9f64ff43a9f49a0b3abe4e9ab7b12c9623ce2712877efa7fed485cfdaae84` |
| `latency_probe.py` | `e94a79a6b0f1695a23db07bfb5f12d5e5746f898893de9cf11cbb6527d6d4ad2` |
| `r/run_phase_baseline.py` | `7e4a6136d6a21c2212d2971880644c65fb24472dc51276683b182becfe7711f7` |

## Exact proposed regression selection

Retain the exact 33 node IDs from
`v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1/r15/pre_e1/collection.stdout.txt`
(SHA-256 `3e1690f7fd8cf81a0c219223bea94e46b5e575e65bee764563cbf3d5bd250f70`).
That inventory is 16 pure and 17 SQL controls, not a wildcard over historical
backend suites. Use its literal parameter IDs and the explicit external R12
file selector from R17's harness; do not infer external identity from a basename.

Append these 13 non-parametrized selectors, relative to the backend root:

```text
tests/test_action_execution_unit.py::test_isolated_configuration_and_output_schema
tests/test_action_two_lease_review_integration.py::test_old_connection_same_physical_final_inert_same_and_child
tests/test_action_two_lease_review_integration.py::test_old_sessions_started_unstarted_tx_same_physical_final_inert
tests/test_action_two_lease_review_integration.py::test_source_revision_after_commit_denies_fresh_final_disclosure
tests/test_action_two_lease_review_integration.py::test_final_source_fence_role_expiry_denies_after_actual_wait
tests/test_action_two_lease_review_integration.py::test_postcommit_evidence_lifecycle_change_denies_final
tests/test_action_two_lease_review_integration.py::test_repeated_cancel_transition_joins_cleanup_no_final
tests/test_action_contracts_integration.py::test_real_http_read_domain_and_no_public_effect_accounting
tests/test_action_contracts_integration.py::test_parent_budget_reservation_is_atomic_and_idempotent
tests/test_action_contracts_integration.py::test_private_reads_and_redacted_receipts_do_not_leak_payload
tests/test_action_contracts_integration.py::test_denied_purpose_unknown_scope_and_unpriced_work_fail_admission
tests/test_action_contracts_integration.py::test_small_pool_concurrent_duplicate_plan_does_not_nest_checkout
tests/test_action_contracts_integration.py::test_maintenance_and_admin_drift_block_mutations
```

Provisional total: 46 unique regressions = 17 pure + 29 SQL. Actual collection must
confirm the set, groups and duplicate-free counts before execution. This finite
suite addresses candidate regression risk, not every backend/native release gate.

The six added two-lease controls exercise inert old handles on the same physical
connection, fresh post-commit authority, lifecycle denial and joined cancellation.
Older transaction-scoped names say "three generations", but their current proof
expects two checkout pairs; names alone are not evidence of obsolete assertions.
The contract HTTP control injects a service and subject: it proves that surface,
not canonical runtime-pool HTTP latency or OIDC/browser behavior. Its small-pool
control is test-local pool 2/overflow 0, not a runtime tuning proposal. Role and
maintenance changes are confined to the stage-owned synthetic database, with
scoped monkeypatch/reset cleanup. No new product test methods are proposed.

## Minimal admission preparation

Propose only three R18 artifacts: a manifest, a small stdlib gate/control file and
a finite stage script. Reuse the R17 fixture identity, capacity, ownership and
cleanup patterns; do not modify or directly rerun `run-full-gates.sh`,
`run-latency-gate.sh` or the historical R12 stage. The first two lack R17's owned
database/capacity closure; R12 also binds a historical product fingerprint.

At most six fixed stdlib acceptance controls should cover: malformed/oversized
manifest rejection; source/path/hash mismatch; duplicate/extra/missing selector
rejection; exact collection and executed XML identity/zero-skip conservation;
stage/DB ownership and fresh epoch admission; explicit pending HTTP/native ledger
and immutable HTTP thresholds. These are manifest controls, not new load cases.
If authored, count them separately: 46 regressions plus at most 6 gate controls,
never inflate counts with repeated Main verification.

Use the same explicit `-c /workspace/v2/apps/backend/pyproject.toml` for every
pytest invocation. Retain actual collection/root metadata and bind XML identities
to that collection. Reject unexpected relative external IDs, guessed XML modules,
extra IDs, skips and count-only passes. Initially expose collection/static stages
only; runtime correctness and HTTP each require a separate Main admission.

Proposed maximum budgets: manifest 64 KiB; admission/source packet 1 MiB excluding
referenced preserved history; pre/collection/pure stage 120 seconds plus 10 seconds
kill grace, evidence 10 MiB; each separately admitted SQL group 120 seconds plus
10 seconds, evidence 20 MiB. Cap exceedance is STOP with retained raw evidence,
not silent truncation or a pass. No automatic retry or additional campaign stage.

SQL admission, if later selected, must verify the unchanged four fixture IDs,
fixed image/internal network, idle runner, no restart/OOM and source pins before
and after. Require host free space at least 20 GiB and PostgreSQL free space at
least 524,288 KiB before each CREATE. The unchanged old 17 SQL require the exact
`rtr_tip054_r15_local_e1` database: the factory isolation test explicitly asserts
and alters that name. Require absence before creation; drop only if this stage
created it, and prove absence before the additional 12 SQL use a separately owned
`rtr_tip054_r18_local_e1`. Migrate each to `0019_action_executor`. No engine DB is
needed for these domain controls: their enabled settings fixture does not contact
its synthetic engine URL. Use scoped test environment/cache isolation; no shared
role alteration, Redis FLUSHDB, rebuild, install or blanket historical suite.

## Mandatory observer-OFF HTTP gate: separate future admission

Three distinct facts must stay explicit:

1. The product default is `ACTION_EXECUTOR_ENABLED=false`; no serving/native
   executor activation is proposed.
2. The local HTTP fixture must set `ACTION_EXECUTOR_ENABLED=true` and a separated
   workflow database/identity so submit can durably queue. It launches no worker,
   DBOS native process or provider. This is a synthetic fixture setting, not `.5`.
3. Observer OFF uses the original baseline's `off` branch: no phase profiler,
   PostgreSQL monitor, R12 detailed observer or R17 observer/lag hooks. Original
   HTTP timers and durable sample journal remain. R17 mode M is not this OFF gate.

Freeze a separate reviewed design before admitting even one OFF run. Preserve the
original load: concurrency 1/10/25/50, 100 cases per profile, admission/submit/
status/cancel = 16 cells and 1,600 requested observations; pool 5+5/pre-ping,
0.9-second route timeout, rate quotas 5,000 and original nearest-rank p95. Each
cell needs exactly 100 samples, zero errors, admission p95 <= 500 ms and other
operations p95 <= 1,000 ms. Upstream failure leaves explicit missing downstream
samples; do not invent timings or correct/subtract observer overhead.

Propose at most one future OFF run, 190 seconds plus 10 seconds kill grace and
10 MiB raw evidence, fresh owned domain/engine databases with exact identity and
absence/cleanup checks. The new frozen design must specify those names and
retention/timeout closure before admission. Original helper remains unchanged;
put its temporary seed files under approved evidence TMPDIR and clean only those
owned files. No ON comparison is required merely to assess the mandatory OFF
gate. This scan neither creates that load stage nor consumes an allowance.

## Unclosed ledger and next decision

Main should next freeze the manifest, source binding and independent design
review, then optionally admit read-only collection. Passing a later finite
correctness suite still leaves current-source mandatory HTTP OFF, full backend
build/type/regression, native durable runtime/process-death/restore/migration,
browser/OIDC and release/activation gates unproved. Missing gates stay explicit;
historical passing packets do not become current-source proof.

Only this report was added. No scratch copy, install, runtime artifact or resource
was created; no cleanup/prune was applicable. Vibecode influenced this work by
requiring source-grounded finite selections and independent admission before
execution, not by broadening the task into another campaign.
