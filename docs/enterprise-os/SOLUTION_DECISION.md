# Solution decision · RtR Enterprise OS

Date: 2026-10-06. Decision status: **approved direction; DBOS selected from
local TIP-054.4a measurements, application integration still pending**.
Homeowner approved the TIP-054 Blueprint on 2026-10-06. The leading runtime
candidate has now been tested in isolation; this does not turn experimental
success into serving compatibility or production certification.

## Decision

Keep the current FastAPI/Next.js/PostgreSQL platform and its SOT, policy,
Documents, Files and evidence services. Add a narrow Action Kernel that owns
business authorization, immutable plans, receipts and recovery. Put model
planning and durable execution behind separate interfaces.

**Selected durable runtime for the new local workflow slice: DBOS 3.2.0**.
Two frozen matched load/fault matrices, native checks and an independent
reverse-order rerun support this scope-bound selection over Temporal's CLI
development profile. [Runtime ADR](RUNTIME_SELECTION.md) records raw results,
failures and limits. Serving dependency compatibility and bounded async
waiter/drain handling are gates before application admission. Existing Ask and
Documents keep their current pipelines. Pydantic AI remains a planner candidate;
official MCP Python SDK remains a planned protocol adapter. Neither was selected
or benchmarked by the durable-runtime experiment.

The target is a useful company operating interface whose actions can be traced
and recovered. It does not require replacing all source business applications.

## What the primary sources establish

| Evidence | Documented fact | Design consequence |
|---|---|---|
| [Pydantic durable execution](https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/) | Durable runs support restarts and integrations including DBOS and Temporal; conversation persistence is a separate concern | Separate agent history, company memory and durable jobs |
| [Pydantic deferred tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/) | Tools can defer to approval or external execution | A model can propose a call while our gateway decides execution |
| [DBOS workflows](https://docs.dbos.dev/python/tutorials/workflow-tutorial) | Completed steps are checkpointed; interrupted steps can run again; database transactions have a separate exactly-once guarantee | Every external mutation still needs source idempotency or reconciliation |
| [DBOS architecture](https://docs.dbos.dev/architecture) | Workflow state is backed by PostgreSQL | Evaluate a separate workflow database/schema with our existing stack |
| [Temporal activities](https://docs.temporal.io/activities) | Activities carry side effects and should support retries/idempotency | Temporal is a strong alternative for broader cross-service orchestration |
| [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | Resuming an interrupted node restarts the node; earlier side effects need idempotency | Checkpoints alone cannot substitute for business receipts |
| [MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) | HTTP authorization has audience/resource binding requirements; protocol authorization itself is optional | Admit only authenticated configured servers and recheck the caller's rights |
| [MCP tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) | Tools have structured schemas and annotations | Validate schemas locally; vendor hints never grant company authority |
| [Microsoft functional workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/functional) | Functional workflow API is explicitly experimental | Avoid selecting that API as our stable business contract |
| [Anthropic agent patterns](https://www.anthropic.com/engineering/building-effective-agents) | Workflow and agent patterns have different control and complexity trade-offs | Start with a small planner and deterministic business workflows |
| [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Context is finite and needs selection/management | Retrieve task-specific context instead of injecting the whole company |
| [Anthropic evaluations](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Tasks, outcomes, trials and graders should be distinguished; repeated success matters | Grade saved artifacts/business state and repeated stability, not prose alone |
| [W3C PROV](https://www.w3.org/TR/prov-overview/) | Provenance describes entities, activities, agents and derivations | Align action receipts with existing evidence lineage |

These sources demonstrate documented capability, not independent benchmarks
of vendor reliability, security, cost or suitability for RtR. The frozen
research claims and snapshots are the reproducible backing; product decisions
below are our own analysis. Mirror domains from one vendor count as one source
family, not independent corroboration.

## Options considered

| Option | Fit to current code | Main benefit | Main cost/uncertainty | Disposition |
|---|---|---|---|---|
| Extend our PostgreSQL outbox/Redis runner into a full workflow engine | Very close | Minimum new dependency initially | We would own replay, signals, deployment versioning and recovery correctness | Retain for existing pipelines; avoid expanding into a custom general engine |
| Pydantic AI + DBOS | Close to Python/Pydantic/PostgreSQL | Typed plans, provider adapters and durable workflow library | Serving-pin compatibility and bounded synchronous-wait avoidance remain .4b gates | DBOS selected locally; planner component remains candidate |
| Pydantic AI + Temporal | Close at application layer | Separate durable orchestration service suitable for cross-service operations | Additional service/operations footprint; workflow determinism and deployment discipline | Actual local comparison completed; 50-load extra-p95 misses twice, not selected for this profile |
| LangGraph + persistent checkpointer | Viable Python integration | Graph state, interrupts and branching agent flows | Need a separate strategy for external effects and business receipts | Reserve for genuinely complex reasoning graphs; not the first business executor |
| Restate + typed agent planner | Viable through adapter | Durable service calls and keyed service state | New service model and operations integration | Reserve alternative if bake-off candidates fail required criteria |
| Microsoft Agent Framework + durable extension | Viable | Agent/workflow and durable hosting integration | Azure/tooling fit and experimental API boundaries need evaluation | Revisit for an explicit Microsoft platform requirement |

The selection is based on fit, verifiable recovery, maintainability and total
cost. Documentation popularity or a larger feature list does not establish
the winner. No fabricated numeric ranking or unmeasured latency comparison is
used.

## Runtime selection gate

Run DBOS and Temporal against the same synthetic workflow contracts and fault
schedule. Neither branch uses an actual LLM, source application or company
data. Retain reports for every trial, including failures.

Required observations:

- Crash before dispatch, within a step, and after the source effect but before
  receipt; restart restores an accurate state without duplicate effects.
- Two workers claim the same request; fencing prevents an obsolete worker
  from committing a result after ownership has changed.
- Approval waiting survives restart; changed input/schema/permissions causes
  reevaluation instead of executing the old approval.
- Long wait, timeout, cancellation, deployment version change and partial
  failure remain observable and recoverable.
- Current SOT/Files policy and request identity propagate through resumed work.
- SDK license, pinned stable version, Python compatibility, restore procedure
  and vulnerability checks are recorded before dependency admission.
- Measure p50/p95/p99 orchestration overhead, memory, database writes, idle
  service footprint and configuration burden on the same machine/load profile.

Hard correctness gates precede cost comparison. Among candidates passing all
gates, choose the one with the lowest measured operating burden at the agreed
load while meeting the latency envelope. Record an ADR with raw measurements.
If DBOS wins, it becomes the only durable owner of new workflows; if Temporal
wins, the same Action Kernel contracts use the Temporal adapter. Do not run
two durable engines for the same workflow or move existing pipelines casually.

Gate outcome: both engines passed finite native/source/restore/fencing proof;
DBOS passed all extra-p95 profiles in both orders. Temporal exceeded 1,000 ms
at concurrency 50 in both. Component footprint/config observations support
DBOS's local fit with PostgreSQL, not a universal or dollar-valued cost ranking.
The retained DBOS synchronous waiter failure must be addressed at the integration
boundary rather than concealed by its correct persisted cancellation state.
See [.4a Verify](../../vibecode_v2/TIP-054.4a_VERIFY_REPORT.md).

## Knowledge and memory choice

Start with PostgreSQL relations/JSONB and existing search indexes for entity
identity, relation, revision, owner and temporal validity. Introduce a graph
database only if measured traversals justify it. A larger language model
context does not prove the company is understood more completely.

Separate four data lifecycles: canonical SOT; fresh source operating state;
personal/workspace memory with ownership and retention; ephemeral task
context. A generated proposal never becomes SOT simply because the assistant
remembered it. Source changes, deletions and revoked permissions propagate to
retrieval and cached context.

## Deferred choices

Model/provider selection, pricing, a fixed monthly budget, production
deployment and source-specific write privileges are not decided from this
research. Existing provider policy remains authoritative. First implementation
uses synthetic/offline model stubs; a later finite external evaluation needs
an approved dataset and spend cap. No fine-tuning or bulk embedding of these
research documents is required to select the architecture.
