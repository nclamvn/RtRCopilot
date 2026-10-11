# TIP-054.4a isolated durable-runtime experiment

This is a synthetic source/runtime comparison, **not** the serving Action Kernel,
PolicyEngine, company evidence, LLM/provider, production deployment, or product
acceptance test. Do not admit these dependencies into application requirements.

## Reproduce

From this directory, with Docker Desktop stable and the two images already cached:

```sh
TIP054_BKO_RUN_ID=tip054-bko-fresh TIP054_BKO_KEEP_FIXTURES=1 bash run-bakeoff.sh
```

The runner uses cached `rtr-tip054-local-qa:20261006` and `postgres:18-alpine`,
`--pull=never`, labelled fixtures, no published ports, bounded memory/CPU/tmpfs,
and an experiment-only read-only source mount plus writable raw-output mount.
No company directory, private env file, Docker socket, or application source is
mounted. Public package/CLI setup is detached before the internal-only network
is attached. Live databases and SDK/server files are in `/bakeoff` tmpfs; each
quiescent source SQLite snapshot is copied immediately to raw output. Raw
stdout/stderr/attempt records are host-backed to survive daemon interruption.

The shared manifest freezes 17 source scenarios, 100 samples at each concurrency
1/10/25/50, provider delay 10 ms, maximum three finite synthetic-call units per
parent and 90-second adapter invocation deadlines. Pins and every downloaded
wheel SHA256, CLI release checksum, actual runtime and licence metadata are
retained. OSV public package checks are point-in-time, not CLI/OS/image security
certification. Transitives are separately locked; serving SQLAlchemy/psycopg
pin compatibility remains a dependency-admission gate.

`driver.py run` retains every attempt including failure. Crash faults use actual
process SIGKILL once per persisted source fault marker, then restart the same
durable identity. Unknown-effect replay uses a separately committed intent and
an append-only fake unsupported provider with no idempotency/status API. Recovery
refuses a blind second write and reports `needs_review`.

`driver.py validate --out <results>` recomputes snapshots, outcome/budget/effect
oracles and nearest-rank quantiles, rejects missing trials/samples, source code or
manifest drift and digests. It never declares selection eligible: native proofs
and independent fresh rerun are additional gates. Hashes detect changes against
the recorded bundle; they are not an external signature or trusted timestamp.

## Native proof and final source fencing commands

Run serially inside the existing owned fixture after SDK setup; do not create
concurrent fixture sets:

```sh
python /work/dbos_adapter.py --mode native-proofs --state-dir /bakeoff/native/dbos-r1 --requests /dev/null --output /evidence/dbos-r1/summary.json --evidence-dir /evidence/dbos-r1
python /work/temporal_adapter.py --mode native-proofs --state-dir /evidence/temporal-r1 --native-runtime-root /bakeoff/native --requests /dev/null --output /evidence/temporal-r1-summary.json
python /work/fencing_proofs.py --engine dbos --out /bakeoff/fencing-dbos
python /work/fencing_proofs.py --engine temporal --out /bakeoff/fencing-temporal
```

Native suites preserve engine wait checkpoints, supervisor PID/-9 boundaries,
dynamic approval/input/schema/ACL mutations, compatible/incompatible code proofs,
timeout and cancellation after a separately committed first effect. Source
scenario enums alone do not certify those native behaviours. Backup/restore and
service idle footprints remain uncertified unless separately executed and saved.
Temporal CLI's SQLite dev server is deliberately **not production Temporal**.

Service-time percentiles start after the shared concurrency slot is acquired;
queue and engine startup/recovery are separate. Matched overhead is the paired
per-case engine-minus-direct service time, not subtraction of unrelated
percentiles. Common source/provider time is included in both. Local PostgreSQL
DBOS vs embedded SQLite Temporal profiles are not production cost equivalents.
Logical rows/database bytes are not physical write amplification, money or
company-scale estimates. A failed hard oracle can never be waived for speed.

Cleanup is restricted to the exact run ID label. Keep fixtures for the
Contractor's independent rerun with `TIP054_BKO_KEEP_FIXTURES=1`; never use broad
Docker prune or stop existing services. An interrupted run is retained as an
environmental failure, not an engine score. No commit/push/rebuild/deploy occurs.
