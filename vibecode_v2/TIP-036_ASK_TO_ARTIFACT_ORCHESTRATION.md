# TIP-036 — Ask-to-Artifact Orchestration

## Header

- Date: 15/08/2026
- Depends on: TIP-035.19 candidate `7644563096c9`
- Module: Ask workspace + Document Operating System
- Priority: P0 local product usefulness
- Release boundary: local only; production configuration and deployment deferred

## Context

RtR Copilot already answers grounded questions and Document OS already governs
approved templates, binding, deterministic rendering, review and issuance. The
missing product bridge is the ability to recognize an employee's request to
create an artifact, recommend an authorized approved template and hand the user
to a controlled draft workflow.

This TIP does not create a second document engine. It composes the existing Ask
and Document OS capabilities while preserving the governance boundary: Copilot
may plan and propose, but a user explicitly starts the draft and existing
Document OS gates remain authoritative.

## Requirements

- REQ-036-01: detect Vietnamese and English artifact-creation intent without an
  external LLM call and without product-, department- or campaign-specific
  branches.
- REQ-036-02: distinguish questions about an artifact from requests to create
  one; ordinary Ask traffic must not receive noisy creation proposals.
- REQ-036-03: classify the requested artifact into a bounded generic family:
  document, report, form, presentation or spreadsheet.
- REQ-036-04: recommend only current approved template versions visible to and
  renderable by the authenticated subject.
- REQ-036-05: rank candidates deterministically from normalized instruction and
  template metadata; return at most three candidates and bounded metadata.
- REQ-036-06: disclose required user-provided fields so the user understands
  what remains before a valid draft can be rendered.
- REQ-036-07: require explicit user confirmation before entering Document OS;
  never render, approve, issue, publish or send automatically.
- REQ-036-08: transfer only immutable template/version identifiers in the URL.
  The user instruction and restricted content must not be placed in URL,
  localStorage or sessionStorage.
- REQ-036-09: planner failure must not block or downgrade the grounded answer.
- REQ-036-10: API and client contracts are strict, bounded and fail closed.
- REQ-036-11: UI is a compact monochrome action strip below the current answer,
  with a clear “proposal, not execution” state and no decorative card stack.
- REQ-036-12: BUILD and VERIFY do not call external LLM/embedding endpoints,
  mutate corpus/ontology or activate any connector.

## Acceptance criteria

1. “Tạo báo cáo …” produces a ready plan when a permitted approved matching
   template exists.
2. “Báo cáo X là gì?” is `not_applicable` and renders no proposal.
3. A creation verb without an artifact type requests clarification rather than
   choosing an arbitrary template.
4. No approved/renderable template returns `no_approved_template`; it never
   falls back to a draft, retired or denied template.
5. Candidate order is deterministic across accents, case and common Vietnamese
   or English wording.
6. Each candidate carries template/version id, display metadata and required
   user-field paths only; no inaccessible schema or source content leaks.
7. Selecting a candidate opens `/documents?template=<version_id>&from=ask` and
   leaves binding, rendering, review and issuance to Document OS.
8. Planner API failure leaves the Ask answer fully usable.
9. Backend unit tests, web contract/component tests, TypeScript, ESLint, Ruff,
   mypy and production build pass locally.

## Explicit non-goals

- Natural-language field extraction or automatic parameter filling.
- Automatic rendering, approval, issuance, publication or delivery.
- New Office/PDF renderer implementation.
- CRM/MRP/IP/HRM, Google Workspace, Slack or native-chat integration.
- Production deployment or release-candidate certification.

## Design decision

The first operational slice stops at a governed proposal and an explicit handoff
to Document OS. This creates immediate employee value without smuggling the
question into browser storage or weakening deterministic document controls.
Natural-language field extraction can be added later as a separate, audited TIP
with explicit evidence and DLP contracts.

## Workflow

SCAN → TIP → BUILD → VERIFY. No architecture checkpoint is required because the
existing Document OS trust boundary and issuance lifecycle remain unchanged.
