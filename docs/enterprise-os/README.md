# RtR Enterprise OS upgrade · decision packet

Date: 2026-10-06 (Asia/Ho_Chi_Minh)

Application baseline: `0e88f48588dc3228f1ae9eca7a7597d96589af8b`.

Status: **Blueprint approved; TIP-054.1/.2/.3 locally verified; TIP-054.4a
complete with DBOS selected locally; TIP-054.4b next**.
Homeowner replied `approved` on 2026-10-06. Preparation verification remains
distinct from subsequent product implementation and release certification.

## Reading order

1. [Scan and requirements](SCAN_AND_REQUIREMENTS.md): existing code, gaps,
   inherited user decisions, requirements with stable IDs.
2. [Solution decision](SOLUTION_DECISION.md): source-backed comparison and
   the recommended design, with unresolved empirical questions.
3. [Blueprint](BLUEPRINT.md): data boundaries, execution contract, experience,
   performance/cost criteria and the first implementation seam.
4. [Task graph](TASK_GRAPH.md): work packages, dependencies and acceptance.
5. [Research dataset](research/README.md): captures, claims, provenance and
   offline validation. External solution research stays outside company SOT.
6. [Acceptance catalog](acceptance/README.md): synthetic scenarios and
   business-state oracles, all explicitly planned until executed.
7. [Preparation verification](VERIFY_REPORT.md): what this packet actually
   verifies and what remains pending.
8. [Implementation status](IMPLEMENTATION_STATUS.md): executed application
   evidence, open debt and the next approved local milestones.
9. [Runtime selection ADR](RUNTIME_SELECTION.md) and
   [bake-off Verify](../../vibecode_v2/TIP-054.4a_VERIFY_REPORT.md): actual
   synthetic SDK/fault/load evidence and mandatory integration conditions.

## Intended outcome

An employee states a goal in ordinary language; Copilot finds the right company
context, prepares a useful result, executes authorized work and returns the
artifact or business receipt. Source facts, live operating state, research,
proposals and execution results retain their distinct identities.

The first proof is a complete internal draft workflow: ask → context → plan →
draft file → preview → saved artifact, including interruption and recovery.
CRM/MRP/IP/HRM/chat integrations remain ready for connection while their source
applications and owner contracts are completed.

## Method and approval seam

This work uses Vibecode Kit v6.2 and Refinery v1.3. The Contractor prepares the
decision; Builders scan and construct the research/acceptance evidence. The
approved baseline is preserved while preparing this packet.

Vibecode's Blueprint instruction says: “Human approve \"APPROVED\" thì mới đi
tiếp.” Since this introduces durable execution, new action permissions and
governed memory, the checkpoint is retained. One approval of this packet covers
its local implementation sequence; it is not a request to approve every tool,
test or routine implementation choice again.

External LLM use with internal evidence, actual connector activation and
production deployment require their own existing scope authorizations. Public
documentation capture and synthetic offline validation do not export company
evidence.
