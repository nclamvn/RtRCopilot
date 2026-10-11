# R12 — Technical stage0 scan

Status: **PASS / HOLD, read-only preflight only.** No tests, imports, SQL, database creation, load, stage execution, fixture replacement, cleanup, or Docker write was performed. Executor remains NOT READY.

## Retained fixture

Only the four exact container IDs and internal network owned by `tip054-4b-full-20261007-r5qa1` were inspected. Selected identity, cached image IDs, owner labels, network memberships, mounts, ports, caps, restart counts and running/OOM state matched the immutable R11 baseline. Raw and normalized mount fields are retained; no private environment or whole Config dump was read.

The runner is idle (only sh/sleep). PostgreSQL has **1,386,756 KiB free**, above the original 512 MiB per-CREATE guard. Runner `/tmp` and `/qa` capacity are recorded in the selected-field packet. The existing profile remains runner 4 CPU / 4 GiB, PostgreSQL 2 CPU / 4 GiB with 3 GiB data tmpfs, and the unchanged Redis/MinIO caps. No new hardening or capacity assumptions were introduced.

## Source and preservation

Whole product remains `56fa5d71fc61efc6dd3dcae8ce0a313a5b0a7f3d410145093f45365c2704e209`.

| Protected scope | Actual result |
|---|---|
| Original source/test/experiment-helper bindings | 400 matched |
| Historical archives / current R9 helpers | 73 / 8 matched |
| Historical raw / analysis | 7,666 / 92 matched; 607,898,179 bytes streamed |
| Protected R10 artifacts | 44 matched |
| Frozen R11 sources | Eight matched |
| Final R11 gate evidence | 284 files / 158,833,394 bytes matched |
| Current R11 metadata and reports | 42 metadata files plus eight reports sealed and rechecked |

R11's failed ON, dropped-record diagnosis, failed source/static/SQL epochs, final closure and current report annotations are preserved. Only NEW R12 outputs and separately authorized Main status/task-graph updates are excluded; no historical R11 report was excluded or rewritten.

## Planned finite stages — not authorized or executed

After the governing TIP/design and author-source freeze: full scoped static health, exact collection and a minimum eight structural plus four SQL controls. SQL must use fresh guarded synthetic domain/engine databases with the unchanged per-CREATE capacity shim. At most one diagnostic ON and one unchanged OFF pair may follow separate explicit approvals; no automatic retry or next-stage launch.

Use the existing read-only source mounts and cached exact public packages (DBOS 3.2.0, SQLAlchemy 2.0.43, asyncpg 0.30.0, psycopg 3.2.9); no new import/pin-admission claim was made in stage0. Keep clean public synthetic `env -i`, pool 5+5/pre-ping, 0.9-second execution-route limit, quota 5,000/60 seconds, original 500/1,000 ms oracle, no-provider/no-worker load, and mypy no-incremental/cache-dir `/dev/null`.

Vibecode Kit v6.2 informed the separate source/evidence seals and explicit approval boundary. The preflight establishes reuse feasibility, not correctness, complete observer measurement, latency acceptance, native recovery, build or release readiness.

## Evidence

[Preflight summary](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r12/preflight_e1/summary.json): SHA-256 `b21165c2bcdc5589e2f13bddedc43f68ecbbd1904747343d1ef0695eaec28da2`.

[Fixture identity/capacity packet](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r12/preflight_e1/fixture-preflight.json): `7628ed848ad8e8378dd6e15c47e4a9752e3ce879ccf0d252a7ee4368a145dc83`.

[Source map](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r12/preflight_e1/source-before.json): `0a65ea547610444bd1df2033e7ab7dc50cc7094f59b5bc799f9d75eb5ee71303`.

[History/current-R11 seal](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r12/preflight_e1/history-before.json): `c9a574c32766bc3e37c0fc5121a9822f5f757e0ed8cd4ee81f81ad0dea04d912`.

## Subsequent source-only design ACK — stage draft, not execution

After the governing R12 TIP's final design decision, Technical authored only NEW [run-stage.sh](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r12/run-stage.sh) and the [freeze schema](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r12/source-freeze-schema.json). No shell stage, syntax/static/import/control/SQL/load was executed. The driver remains a reviewable draft until all owners HOLD and Root approves its exact bytes.

Owners confirmed nine code basenames: minimal_observer.py, run_observed.py, analyze.py, budget.py, four test_minimal_observer_{builder,review}_{unit,integration}.py files, and run-stage.sh. The freeze will bind exact bytes/hashes, twelve actual unparameterized IDs (4+4 structural, 2+2 SQL), the two declared immutable R11 pure imports, and the successful offline budget artifacts. No manifest or actual collection claim is manufactured before those author freezes.

The proposed stages are `pre_sql`, `sql_builder`, `sql_review`, `on`, `off`, each requiring a separate Root ACK and fresh gate ID. Entry guards bind approved manifest/stage/product and exact retained profile/idle state. Begin/end closures preserve old source/history and all R11 metadata42/reports8/raw284, plus frozen budget artifacts. Static checks precede structural execution; SQL uses original guarded per-CREATE paths and 120-second TERM/10-second bounds. ON retains 800,000 records / 128 MiB / 180 seconds with 190-second TERM/10-second supervisor limits.

ON closes original R9 graph verification and the real post-timing audit chain before read-only `run_observed.validate_run(run_dir)` checks the NEW measurement. This API must positively conserve actual samples/phases and all selected finish/serialize/write/flush and audit emit-family cardinalities/order; six zero fault counters alone are insufficient. The actual implementation remains pending owner freeze/source review. OFF uses the original uninstrumented helper only after a subsequent ACK. The paired NEW analyzer is host-only after both valid packets and a further ACK; it is never auto-invoked by the stage.

## Final source-only freeze e1 — actual closure, runtime HOLD

After both owners' final HOLD and independent/Contractor mechanical-delta PASS, [source_freeze_e1/summary.json](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r12/source_freeze_e1/summary.json) closed exit 0, SHA `b58c89a2d9235cf0150e1701457a5ddf5d597dec6246b09211653ac567e60cf1`.

The [manifest](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/r12/source_freeze_e1/manifest.json) SHA is `126beb584aec27efac7643e609cfc7fb2e327d01f0c5b0ae47df27cf5b7cd3ff`; stage SHA is `3987f88691f66ed1a417b46081629315108452b94a0545444fc06a31614bea84`. Nine sources matched before/after. The exact twelve IDs are AST declarations only (eight structural/four SQL); no actual collection or control execution occurred. The immutable R11 pure imports and both accepted budget artifacts are bound. Tested budget c60 source archive/provenance and byte-identical Contractor replay outputs remain explicitly separate from formatted current budget source; no budget retry was performed.

Protected source/history/R11 scope all matched. Exact selected fixture profile remained unchanged and idle, PG free 1,386,756 KiB. Closure packet hashes: source `ef78a7bf05f21e00342bdce767a1ab1814716ba5179d50a066d8561e71d928cb`, history `2c2f964c3ef95ec51fc50ea7a7948b0a99d7353c49c970796dbaac61cda93404`, fixture `8103fddd2715d2b6f774069d9c8444537795360c8422573e16c3d0620f827704`.

The read-only author style preview remains retained: all eight Python files needed formatting and Ruff reported 55 findings (53 E501/two I001). Owners applied only approved mechanics; the preview was not rerun. Stage validation now explicitly requires `SELECTED_POPULATION_PASS_NOT_SLA`; this is not latency acceptance or release readiness.

The exact clean-public-env StageA command was sent to Contractor, using the frozen manifest/stage/product and fresh `r12_pre_sql_e1`. It remains **unexecuted** until a separate ACK. All SQL/ON/OFF/paired-analysis stages remain HOLD, with no automatic next stage.

## Subsequent approved control stages — actual results

The preceding unexecuted plan is historical. Separately approved StageA `r12_pre_sql_e1` actually closed exit 0: all static/import/collection codes zero, strict mypy 174 sources, twelve exact collected IDs, eight structural PASS in 0.18 seconds, no failures/errors/skips. Its seven closure codes were zero; no SQL/CREATE/load ran. Technical idle packet SHA `35e8d42129f8fe7335930567a535389e37a313a057d5d8376eac996e4ce478a8`.

Separately approved `r12_sql_builder_e1` and `r12_sql_review_e1` each executed their exact two SQL controls once in fresh guarded domain/engine pairs. Builder: two PASS in 3.84 seconds; Reviewer: two PASS in 4.58 seconds. Both had zero failures/errors/skips, SQL/JUnit codes zero and all seven closure codes zero. Five existing Swig deprecation warnings per module remain retained; no teardown ERROR/Traceback/different-loop match. Each actual CREATE passed the original 524,288 KiB guard. Twelve unique controls (eight structural/four SQL) are now demonstrated; repeated personal checks are overlap only.

Raw TechnicalSQL summaries contain an ambiguously named `elapsed_seconds` field calculated by summing per-testcase JUnit `time` attributes. It is **not** whole pytest-stage duration or closure-inspection time. Those raw packets remain unchanged; the whole-run durations above use actual stdout/XML suite results. Technical closure hashes: Builder `4befcb5a10453b8745efe81f5965ac451680af19c72ea04f2e8cfa8aab8a27e8`, Reviewer `75ec5f3c5f484b6f8964a786e6b79b8eb3da97a30a856ca3563bd8261a40c852`.

The separately authorized Main personal eight-case slot `r12_root_structural_e1` is prepared, not executed by Technical. Original source boundary begin and fresh source/history/fixture guards passed; exact source9/manifest126beb/stage3987 remained unchanged. Runner idle, PG free 1,354,956 KiB. [Handoff packet](/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1/r12_root_structural_e1/handoff.json) SHA `80324b88b352a43f60572d9ced7927d07b8a49e937b8ec9caf3c3f9041a6c3aa`; exact public command SHA `39af76055bb521904fdbb1c2705bc79d6886af46329d6045938f66698ab4eb8d`. Technical has yielded exclusive runtime ownership and will perform no Docker or runtime action until Main returns it. ON/OFF/paired analysis remain NOT RUN and require further explicit approvals.
