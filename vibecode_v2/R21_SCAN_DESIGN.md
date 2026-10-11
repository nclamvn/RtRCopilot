# R21 focused scan and proposed adapter design

2026-10-09 · Builder · Vibecode Kit v6.2 · DESIGN ONLY / awaiting Main TIP.

## Scope and observed source

One newly admitted mandatory observer-OFF HTTP qualification, on unchanged
product and original tests/helpers. No tuning, worker, native/provider effect,
external call, Git/build/install or serving activation. This scan used source
and retained evidence only; it ran no tests, product imports, Docker or SQL.

R20 Main Verify and independent final review report eight passing bootstrap
identities, twelve completed/drained groups and owned DB closure. This proves
the explicit integration-DSN bootstrap prerequisite, not driver equivalence or
HTTP performance. R19 remains FAILED_BOOTSTRAP, 0/1,600 observations, with its
old marker consumed. Neither result is rewritten or inherited as R21 latency.

The unchanged `run_phase_baseline.py` OFF branch invokes the original
`latency_probe.py` with runpy, without importing phase profiler or starting PG
monitor. Its canonical runtime factory asserts pool 5+5/pre-ping, timeout .9s
and synthetic quotas 5,000. The helper itself seeds two principals, one signed
SOT reference and one capability admission through a separate seed engine,
then measures admission/submit/status/cancel through ASGI. The only authority
override is the existing synthetic current-subject dependency; this is not OIDC
or network/UI latency. No service/factory override, warm-up or pre-seed is proposed.

Three reuse boundaries require small new R21 code, not old-file edits:

- R19 `bounded.py` directly supports both new `/evidence/r19/` roots. Its
  script-directory import resolves the original qualification/CAPS unchanged.
  Only stage `http`, label `load`, gets 190s; other children get 120s. Its persisted
  first cleanup deadline is shared across normal/finally/external-stop paths.
- R19 `packet`, `mark`, `contract` and `prior` hardcode old epoch/contract/paths.
  Do not call them as R21 gates or mutate globals. Reuse only immutable
  `expected`, `row_key`, `reconstruct`, `quantile`, strict JSON parsing and
  R18 owner/process, fixture, collection/XML helpers; a small R21 adapter owns
  its new contract, marker, pre-stage identity and raw packet checks.
- R20 domain/environment functions hardcode its single DB and absent workflow.
  Reuse linked preservation seals, not those functions with altered constants.
  R21 validates its own exact caller envelope before any effects.

## Finite envelope and admission

Exact new DBs: `rtr_tip054_r21_local_e1` owned by `rtr_tip054_local`, and
`rtr_tip054_r21_engine_e1` owned by `rtr_tip054_engine`. Caller must explicitly
provide both equal domain DSNs:
`postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r21_local_e1`,
and separate workflow DSN:
`postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r21_engine_e1`.
Missing, empty, mismatched, foreign role/path/host/query/fragment DSNs reject
before mkdir, Docker, CREATE, child spawn or allowance marker. No fallback or
credential/role ALTER. Validate both derived envelopes before effects:

- Ordinary PRE: clean env, domain+integration equal, executor false, workflow
  key absent, offline/local providers, empty API keys, defaults 30 writes and
  120 reads per 60s, timeout .9s.
- Intended load: same domain capture, executor true, exact isolated workflow,
  quotas 5,000 per 60s, timeout .9s. This enables synthetic queueing routes only;
  serving executor remains OFF. No worker/dispatcher/DBOS runtime is launched.

PRE runs one fresh no-SQL probe under the intended load envelope: actual Settings,
captured DSNs in the unchanged test-helper dependency chain, canonical factory
pool settings, empty external keys and workflow equality. Factory construction
does not connect; disposal is guaranteed. It must not import/invoke the load
driver, seed, call an API, contact the engine or allocate performance samples.
The ordinary false/workflow-absent PRE envelope is independently guarded.

Fresh roots are fixed `/evidence/r19/r21_pre_e1` and
`/evidence/r19/r21_http_e1`; no `r21_http_e2`. HTTP requires passing same-binding
PRE and separately pinned Main/source-review admission. A fresh R21-only marker
is created exclusively immediately before the original load spawn. Existing or
unknown launch means allowance consumed; known preflight failure remains unlaunched.
The old R19 marker is neither reused nor reset.

## Proposed smallest new packet

New R21 only: one stdlib qualification adapter, one six-method offline test file,
one no-SQL probe file, one shell wrapper and one finite contract/binding. No new
supervisor, generic framework or copied legacy inventories. Read-only Ruff
check/format via retained runner may prepare source before freezing; Main owns
container PRE/SQL/load after independent acceptance.

Fixed proposed controls in `test_r21_offline.py::R21Controls`:

1. `test_exact_caller_and_derived_envelopes_before_effects`
2. `test_linked_source_history_and_one_use_admission`
3. `test_original_rows_order_missing_and_quantile_conservation`
4. `test_packet_summary_controls_oracle_and_corruption`
5. `test_supervisor_dispatch_and_shell_ownership_failclosed`
6. `test_fixture_db_closure_and_readiness_scope`

Fresh probe: `test_r21_envelope.py::test_captured_load_envelope_without_sql`.
Exactly seven unique collected/executed identities; shared explicit backend
pytest config/root and exact XML mapping, not count-only or name guessing.
Controls use finite fabricated packets and fake shell effect seams, not runtime
signals, SQL or a rerun of R19's expensive process-fault tests.

## Measurement and retention gates

Freeze expected 1,600 `(profile, case, operation)` keys independently from raw:
profiles 1/10/25/50, 100 cases each, four operations, 16 cells. Each cell requires
100 samples, zero errors and nearest-rank p95 <=500ms admission / <=1,000ms others.
Reuse original reconstruction unchanged, including typed IDs (no bool), finite
timers, successful states, per-case chronology, profile blocks and predecessor
checks. Do not require global completion order or treat UUID payloads as keys.

New adapter checks R21 marker/binding/contract, exact parsed JSONL-to-final-JSON
list equality, original summary cells/verdict and profile metadata, original OFF
controls, matching owner/process and completed original exit (0 PASS, 1 legitimate
SLA FAIL). Oracle abort, missing summary, malformed/partial/duplicate raw or an
inconsistent exit is integrity FAIL, even when observed HTTP outcomes look okay.
Retain failed rows, missing identities and conservation, with no salvage/retry.
Successful request timing ends before JSON parsing/journal flush; exception timing
differs; acquired-slot service time includes pool contention but excludes semaphore
queue. No new diagnostic observer or reinterpretation of latency.

## Ownership, budgets and closure

Reuse four retained containers/internal network, original images/mounts/IDs and
seven declared resource/security caps, idle runner and fresh capacity checks.
Immediately before each CREATE require absence, host >=20GiB, PG >=512MiB,
role LOGIN and exact target/role. Record uncertain CREATE before execution; only
acknowledged owned DBs may drop, reverse engine then domain, after matched drain.
Do not DROP on unknown ownership or force-kill foreign tasks. Direct admin psql
uses connect5s/statement10s/lock5s; checked children use 120s, sole entire load
190s including imports/seed, shared cleanup10s. Each evidence root <=10MiB,
source packet <=1MiB. Cap failure retains all bytes and stops; no truncation.

After load timer and matched drain, before DROP, retain post-load SQL even on
load FAIL: engine DB has zero non-system user tables; domain executions have
zero spent tool calls/owner tokens/active leases/running-waiting states; attempts,
execution receipts, source-linked render effects and charged events are zero.
Queued/cancelled rows and cancellation acknowledgement events are legitimate
and are not incorrectly required absent. Record these proof values separately
from latency. Retain fixture idle, both final catalog absences, fresh capacities,
source gates before/after, owner/process records, all stdout/stderr/codes and marker.

Link, rehash and preserve R20's 39 direct pins, 202 evidence pins, final reports
and closure, then transitive R19/R18 seals. R20 source binding SHA256 is
`9ee11e8257402c9038abcc8d07d5b4e3d9a09efa146a1e62b2f52702a65333ae`;
R20 evidence seal `f8c3f11790ec4c624845e8151c0ee9beebb709b26d00acdef2f732ca011fb1af`;
R20 final closure `f038f87412551bb6cf228dc8dcf0bfd2b365eca33fecfa3784bf9331c7ea7cff`.
Its published status/task-graph hashes remain historical metadata, not an
instruction to freeze the current mutable status/task graph during R21 publication.
Retain explicit product204/tests192 digests from their documented recipe; no
invented historical 4a0b equality or summing overlapping pin/test inventories.

Await Main TIP and independent design acknowledgement before authoring. Even a
later HTTP PASS closes this mandatory local OFF gate only: candidate NOT_READY,
serving executor OFF and TIP-054.5 blocked. Main may close EXE-009 only when
all six R21 criteria pass; broader whole-candidate requirements remain separate.
