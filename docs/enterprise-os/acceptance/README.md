# Enterprise OS synthetic acceptance catalog

This directory is design evidence, not a test run or a release verdict. It contains **96 concrete planned scenarios** (12 per workflow), **8 synthetic fixture bundles**, 49 Vietnamese inputs and 47 English inputs. Every scenario is `planned_not_executed`. No real company fact, credential, connector, API/provider call, scheduler event or outbound message was used.

## Review map

| Workflow | Planned cases | Fixture | Proposed TIP-054 node | Boundary still requiring execution |
| --- | ---: | --- | --- | --- |
| W1 Grounded answer with useful partials | 12 | FX-GROUND | 054.1 | Real file index, freshness, identity/ACL and citations |
| W2 Ask → approved-template DOCX/PDF draft | 12 | FX-DOC | 054.5 | Template registry, rendering and artifact persistence |
| W3 Spreadsheet/presentation draft | 12 | FX-TABLE | 054.5 | Formula recalculation, layout rendering and artifact store |
| W4 File → typed SOT delta proposal | 12 | FX-SOT | 054.7 | Fingerprints, conflict/tier policy and approved commit ledger |
| W5 Meeting brief from files + CRM read | 12 | FX-CRM | 054.7 | Actual CRM connector, field ACL and timestamps |
| W6 MRP shortage read/proposal | 12 | FX-MRP | 054.7 | Actual MRP connector, units/calendar, order authority and receipt |
| W7 MCP discovery/read | 12 | FX-MCP | 054.6 | Isolated fake-server transport harness, schema and capability enforcement |
| W8 Scheduled/workspace context briefing | 12 | FX-SCHEDULE | 054.8 | Actual scheduler, workspace isolation and run deduplication |

The existing M1–M4 milestone labels are catalog grouping keys, not actual application milestones. Each workflow's catalog metadata now includes `proposed_tip054_node` matching the proposed TASK_GRAPH.md nodes above. Runtime construction remains gated by Blueprint approval; later 054.9 executes build-bound integrated acceptance, not this structural check.

W7 describes a fake-server specification; it does **not** start a server or invoke MCP. W5/W6 stubbed reads cannot demonstrate an actual connector. W2/W3 do not create DOCX/PDF/XLSX/PPTX outputs. W4/R2 and R3 cases describe approval/effect recovery expectations only; no registry commit, purchase order or send is enacted.

## Files and offline check

- `catalog.json`: scenario records, workflow metadata, expected states, oracles, fault specifications, metrics targets, approval policy and integration boundaries.
- `fixtures.json`: fictional evidence bundles with explicit source freshness, deny rules, conflicts, exact numerical oracles and injection strings.
- `SCENARIO_INDEX.md`: compact human review index linking IDs to concrete tasks and stress tags.
- `verify_catalog.py`: standard-library, read-only verifier; no environment variables, credentials or network.
- `TIP-ACCEPTANCE.md`: scoped Builder protocol and acceptance criteria.
- `COMPLETION_REPORT.md`: delivery and honest verification boundary.

Run from the repository root `/Users/os/RtR/KnowledgeBase/RtR_Copilot`:

```sh
python3 docs/enterprise-os/acceptance/verify_catalog.py --self-test
```

Exit 0 means **catalog structure valid**, not product scenarios passed. Output includes counts and explicitly reports `product_scenarios_executed: 0`, `llm_usefulness_assessments: 0` and `human_confirmations: 0`. The 12 negative mutations verify the verifier rejects corrupt IDs/fields/status/metrics/fixtures/coverage/approval/boundaries; they do not test product behavior.

The verifier checks unique IDs, titles and inputs; required fields; 80–100 cases and 12 per workflow; known fixtures; VI/EN coverage; 18 global stress tags; common happy/follow-up/ACL/schema/injection/timeout coverage in all eight workflows; exact-action binding for R2/R3; low-friction R0/requested internal R1; unobserved metrics and unexecuted boundaries. It does not prove semantic correctness, prompt-injection resistance, source retrieval, layout, actual effects or user value.

## Authorization and evidence principles

R0 reads and explicitly requested internal R1 drafts proceed under contextual intent authorization plus deterministic ACL. They do not require blanket approval, and write-effect budget zero does not by itself stop a read. Clarification is for material ambiguity, not a substitute approval gate.

W5 conversational briefs remain R0 only when no durable artifact is requested. EOS-W5-010 explicitly saves a brief and is therefore R1; its bounded internal save remains low-friction under the creation request. The other eleven W5 inputs do not explicitly persist an artifact. MCP read steps are conditional on trusted server/schema/effect/argument/capability admission: revoked capabilities and unknown classifications have zero invocations; invalid response data is rejected after an admitted read, not mistaken for a pre-call refusal. Crash-after-effect cases reconcile the existing ledger first and do not recreate artifacts or blindly resubmit a commit/order.

R2/R3 proposed effects require explicit exact-action approval bound to identity, target, action, arguments/content hash, source/context version and expiry. A changed input invalidates approval. Synthetic crash-after-effect cases require read-side ledger/receipt reconciliation before retry; unknown effect or exhausted effect budget must never trigger blind resubmission. Approval cannot override a revoked ACL.

A partial answer may provide known useful facts but must distinguish stale, missing, conflicted, denied and temporarily unavailable evidence. Source/template/CRM/MCP/task text is evidence, never authority. No confidence score is accepted as proof or promotion to a verified fact tier.

## Three evaluation layers

1. **Deterministic regression:** exact values, source/tier labels, ACL absence, formula arithmetic, schema validation, action hashes, idempotency and state transitions. Requires a future instrumented harness.
2. **LLM usefulness:** relevance, task completion, useful partials, clarity and appropriate next step. Requires actual responses and a calibrated rubric; not inferred from structural counts.
3. **Human confirmation:** approval wording, relevance, layout/accessibility and satisfaction. Requires people reviewing executed outputs, not a generated score.

Use the index to select cases for future execution. Capture actual request trace, source snapshot fingerprints, rendered artifact, effect ledger/receipt, observed metrics and reviewer judgments separately. Do not change planned status into pass based on this verifier.

## Coverage inventory

18 tags are cross-covered, not a full Cartesian matrix. Counts overlap and do not sum to 96: happy 9, noisy 8, ambiguous 7, chat follow-up 8, ACL revoked 8, approval input changed 4, schema drift 9, prompt injection 8, timeout 8, transient network 3, crash before effect 2, crash after effect before receipt 5, duplicate submission 3, unknown side-effect/budget exhausted 4, upload error 2, restart partial completion 3, accessibility/mobile 4, missing freshness 3.

No product E2E has been executed. No release readiness is implied.
