# R18 frozen qualification ledger

This is an admission plan, not a result report. Product regressions are 46 unique
selections (17 pure, 17 old SQL, 12 added SQL); six stdlib admission controls are
separate. Actual collection must prove all 52 identities. Repeated executions
add no unique cases. No HTTP or native stage is present in the harness.

| Original requirement | Finite R18 contribution | Still unproved on these bytes |
|---|---|---|
| EXE-001 | Default OFF and isolated configuration/output schema | Actual native DBOS admission and old pipelines without engine initialization |
| EXE-002 | Immutable queued submit, duplicate domain metadata and fresh cancel view | Native dispatch interruption, workflow identity and durable restart |
| EXE-003 | Current owner/source authority, post-commit role/freshness/lifecycle fences | Durable wait/restart and all before-effect security gates |
| EXE-004 | No native contribution | Real worker death before/during/after effect and recovery |
| EXE-005 | Same-physical-connection stale handles are inert; fresh generations | Native competing/stale owner effect publication and receipt fencing |
| EXE-006 | Domain cancel, timeout, repeated cancellation and joined lease cleanup | Real completed effect with remaining work and native cancellation |
| EXE-007 | Parent budget idempotency, deadline/usage/foreign ownership immutability | Retry/child/native recovery charging and reconciliation |
| EXE-008 | Contract admission, private/redacted metadata, purpose/unpriced-work denial | Real R0/R1 source effects, rendering/output-policy inheritance |
| EXE-009 | Original finite observer-OFF contract frozen only | Fresh current-source 16-cell HTTP OFF proof; R12 FAIL remains preserved |
| EXE-010 | Fresh empty synthetic DB migration prerequisite, if SQL is admitted | Populated down/up, joint engine/domain restore and native resume |
| EXE-011 | Exact focused regressions and independent admission review | Broad backend regression, lint/types/build/import/package and release gates |

Every contribution above is selected but not yet executed by R18. The machine
manifest keeps these requirements partial/pending even after finite regressions
pass. Main records actual pre/SQL outcomes in a separate Verify Report. The
candidate remains NOT READY, serving executor OFF and TIP-054.5 BLOCKED.

## Source recipe and byte bridge

`source-binding-eN.json` records every regular file recursively under backend
`src`, `migrations` and `tests`, excluding `__pycache__`, `.pytest_cache`,
`.ruff_cache` and `.pyc`. Product additionally includes backend `pyproject.toml`,
`uv.lock`, `alembic.ini` and `v2/.env.example`; tests are a separate inventory.
Symlinks (including parents), noncanonical paths and source-set drift fail.
For each inventory, sort repository-relative POSIX paths, concatenate UTF-8 lines
`SHA256(file bytes) + two spaces + path + newline`, then SHA-256 the concatenation.
No Git metadata, mtimes, environment or historical verdict enters that digest.

Also bind the original latency/baseline helpers, R12 fixture metadata/Verify,
R17 final Verify/closure and all 251 paths in the immutable R17 e5 binding, plus
the R18 TIP/scan/manifest/ledger/three Python files/shell. The binding itself is
not recursively self-hashed; its exact bytes are copied to each fresh evidence
epoch and compared for pre-to-SQL admission. Independent accepted source review
is pinned separately by Main. Source packet cap includes current R18 artifacts
and binding, not referenced historical evidence or preserved source archives.

Historical `4a0bb4921ed0...` is attributed to R17 Main's existing whole-product
recipe. R18 does not assert its newly specified digest algorithm is equal to that
unknown recipe. The unchanged 251 prior pins form a specific byte bridge; R18's
fresh complete product/test inventories attest the explicitly described scope.

## Process and resource boundaries

Each container child gets a new POSIX process group and unique inherited
ownership token. The supervisor reads `/proc` ownership before signaling only
that group. Deadline/cap/interruption means TERM, at most 10 seconds grace, KILL
and drain; failure or unknown ownership stops cleanup admission and retains the
database/evidence. Host interruption signals the in-container supervisor and
joins Docker exec; killing only the host client is never considered drain.
Normal child completion also rejects/drains lingering owned group members.
All stdout/stderr and process records are retained; cap failures never truncate.

The old SQL database's literal name is required by the existing isolation test.
Both databases must be initially absent. Create only after host >= 20 GiB and
PG >= 524,288 KiB checks; own/create/drop sequentially, prove early/final absence,
and never drop an existing foreign database. Fixtures, mounts, image, internal
network and idle runner must remain unchanged. No engine database is created.

Base environment is executor-disabled and provider-offline. The existing domain
fixtures use scoped enabled settings overrides with an uncontacted synthetic
engine URL. This does not launch DBOS/workers or alter serving configuration.
Their service/subject overrides are labelled controls, not native or OIDC proof.

## Separate future HTTP admission

Observer OFF is not R17 minimal mode M and is not the executor-disabled flag.
The future synthetic HTTP process requires an enabled executor flag plus isolated
domain/engine identities merely to queue submissions; no worker/native/provider
launch is permitted. The serving default remains OFF. Normal timers/journal stay;
phase, detailed, PostgreSQL and lag observers do not.

Exactly one pending campaign: concurrency 1/10/25/50, 100 cases/profile,
admission/submit/status/cancel, 16 cells and 1,600 requested observations. Each
cell needs 100 samples, zero errors, nearest-rank p95 <= 500 ms admission and
<= 1,000 ms otherwise. Keep pool 5+5/pre-ping, route timeout 0.9 seconds, quotas
5,000, deadline 190 seconds + 10 seconds kill grace, output cap 10 MiB. Missing
downstream slots stay missing. No subtraction, retries, relaxed limits or load
stage is authorized here. A new reviewed retention/owned-fixture wrapper is
required before Main can admit that separate campaign.
