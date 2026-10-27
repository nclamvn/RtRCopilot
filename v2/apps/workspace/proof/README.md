# AW-01 dependency and durable harness proof

Evidence date: 2026-10-27 (Asia/Ho_Chi_Minh). This is local integration evidence,
not a real-model evaluation, product benchmark, or release approval.

## Selection and compatibility

- Python 3.12.11; separate `.venv` and `uv.lock` under `v2/apps/workspace`.
- Published wheels resolved: `pydantic-ai-slim[dbos]==2.62.0`, `dbos==3.2.0`,
  `pydantic==2.14.1`, `fastapi==0.162.0`, `uvicorn==0.54.0`, `httpx==0.28.1`.
- Tests: `pytest==9.1.1`, `pytest-asyncio==1.4.1`.
- Stable direct pins and transitive versions/wheel hashes are in `uv.lock`.
  No legacy backend manifest or environment was upgraded.
- The published slim wheel requires `pydantic>=2.12`; its DBOS extra permits
  `dbos>=2.10.0`. The chosen original 3.2.0 pin imports and passes the probes.
- No provider extra was installed. No whole Coder or Pydantic AI Harness package
  was added: scoped typed tools plus slim/native durability cover the selected
  AW-01 proof, and an additional harness has no demonstrated outcome benefit here.
  Shell, external MCP, skills and memory are not made available by this choice.
- `installed-licenses.json` records raw license metadata for 41 third-party
  installed distributions. Direct libraries are MIT/BSD; transitives include
  psycopg and psycopg-binary LGPL-3.0-only and certifi MPL-2.0. DBOS installs
  psycopg even when its configured backend is SQLite. This is an inventory,
  not legal certification or a claim that every transitive license is MIT.

## Native integration contract

Use `Agent(..., name=<stable id>, capabilities=[DBOSDurability(...)])` constructed
before `DBOS.launch()`, and call `agent.run()` inside one new `@DBOS.workflow`.
The deprecated `DBOSAgent` is not used. The primary FunctionModel registered at
agent construction is the durable model default; do not swap an unregistered
model instance at runtime. Workflow and application identities must remain stable
within a version, and unrelated legacy workflow histories must remain separate.

SQLite works natively with `system_database_url='sqlite:////absolute/path.sqlite'`.
No PostgreSQL server or Docker container was needed or touched. DBOS telemetry
is explicitly disabled (`enable_otlp=False`). Product tracing is a separate policy.

Pass live I/O handlers to `DBOSDurability(event_stream_handler=handler)`, with
signature `async def handler(ctx, events)` and an async event iterator. A handler
on `agent.run()` or workflow-side streaming APIs has different buffering behavior.
Direct function tools are **not automatically durable**; the proof explicitly
decorates them with `@DBOS.step(retries_allowed=False)`. Live events and effects
can rerun before a step receipt exists, so durable local unique-key receipts and
atomic effects are required. External effects still need endpoint idempotency or
reconciliation; this local SQL proof does not establish external exactly-once.

The cancellation API is `await DBOS.cancel_workflow_async(workflow_id)`. A native
`CANCELLED` status is control-plane cancellation, not proof that a non-preemptible
model/tool coroutine has physically exited. A product fence must prevent further
publication, and the UI must distinguish request acknowledgement from worker stop.

`Agent.run(timeout=...)` records its original start time in DBOS history. Replaying
with a newly reset full budget must not extend the original absolute product
deadline; the product additionally persists its original limits and checks its
absolute deadline before publication. SDK request usage is reconstructed from
checkpointed responses, as demonstrated in the crash/restart budget probe.

## Execution and observations

Run from `v2/apps/workspace`:

```sh
UV_CACHE_DIR=/Users/os/RtR/KnowledgeBase/RtR_Copilot/.uv-cache uv sync --frozen
.venv/bin/python -m pytest tests/test_harness_proof.py -q --basetemp=.proof-tmp
```

Last full harness-only result: **7 passed in 28.80 seconds**. Each worker globally
denies `socket.socket.connect`; it cannot silently call any provider. FunctionModel
outputs and tool choices are assistant-authored scripted fixtures, not model
intelligence, semantic quality, price, or provider-latency evidence. DBOS workflow
execution, SQLite persistence, process death, restart, and cancellation are real.

Independent combined run of `tests/test_harness_proof.py tests/test_workspace.py`:
**12 passed in 37.75 seconds** after the persisted-limits/context/cancellation
repairs. This count includes the same seven harness cases, not seven additional
independent cases. Production user-flow testing remains separately scoped below.

| Probe | Observed result |
|---|---|
| Live model handler and post-checkpoint process death | Text arrives before model final; SIGKILL and restart use same workflow; two model fixture calls and one tool effect total; one publication |
| Crash after local effect before DBOS tool receipt | Two tool attempts, one effect via local unique SQL receipt; completed model response not rerun |
| Cancellation while model streams | Native terminal CANCELLED; caller cancellation exception; no publication |
| Request budget | Limit of one blocks dispatch of the second model request |
| Original timeout after process death | Resume after original deadline raises RunTimedOut; no further model request or publication |
| Crash during provisional stream | Incomplete model step reruns (three physical fixture calls total); stable step/event key deduplicates observer events; effect remains one |
| Request budget after process death | Recovered checkpointed first response consumes the original one-call budget; second request not dispatched |

These probes isolate upstream primitives. They do not certify every production
adapter path. Product API/browser integration, security tests, source quality,
real provider execution, real-model comparison, and human acceptance are separate
evidence. Approval pause, real MCP effects, provider 429 ambiguity, credential
brokering, and unsupported formats remain outside this local proof.

## Primary sources

- [Pydantic AI DBOS integration](https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/)
- [Published slim metadata](https://pypi.org/pypi/pydantic-ai-slim/2.62.0/json)
- [Published DBOS metadata](https://pypi.org/pypi/dbos/3.2.0/json)

The installed wheel source and successful probes, not a promise from the current
documentation main branch, establish the API contract used above.
