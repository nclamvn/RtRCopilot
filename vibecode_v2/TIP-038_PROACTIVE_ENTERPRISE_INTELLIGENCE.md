# TIP-038 — Proactive Enterprise Intelligence

## Header

- Date: 15/08/2026
- Depends on: TIP-036 + TIP-037 milestone `b249a20`
- Module: governed intelligence briefing
- Priority: P0 local product usefulness
- Release boundary: local only; no connector activation or production operation
- Status: `COMPLETE_LOCAL` — see Completion and Verify reports

## Context

RtR Copilot can answer questions, inspect governed files and hand an employee
to an approved artifact workflow. It still waits for the employee to know what
to ask. The next useful step is a briefing surface that reveals recent company
changes, facts needing attention and promising research signals before a
question is written.

The briefing is not an autonomous analyst and does not create a second truth
plane. It is a policy-scoped projection over current SOT and the separately
labeled Research zone. Every disclosed content unit must remain evidence-bound.

## Decisions log

| ID | Decision | Rationale |
|---|---|---|
| D-038-01 | Compute the briefing live; do not persist a hand-authored snapshot | Stale dashboards contradict the SOT method |
| D-038-02 | Authorize metadata first, then load content only for allowed records, then recheck | Prevent restricted existence/content leakage |
| D-038-03 | SOT and Research remain structurally distinct in API and UI | External research must never masquerade as company truth |
| D-038-04 | No LLM is required to create the feed | Zero marginal cost, deterministic latency and no external processing |
| D-038-05 | A signal suggests an Ask follow-up but cannot trigger an action, publication or delivery | Human remains the action boundary |
| D-038-06 | Reuse the existing shell, evidence language and monochrome tokens | Avoid another dashboard visual dialect |
| D-038-07 | Skip a separate Blueprint checkpoint | This is the next approved roadmap node and does not alter core architecture |
| D-038-08 | Exclude packages identified as test/integration producers before policy or content loading | Synthetic certification data must never appear as employee intelligence |

## Requirements

| ID | Requirement | Priority |
|---|---|---:|
| REQ-038-01 | An authenticated employee can open a live personal briefing | P0 |
| REQ-038-02 | The server returns only records visible under current RBAC/ABAC/ACL | P0 |
| REQ-038-03 | Metadata authorization precedes content loading and is rechecked before disclosure | P0 |
| REQ-038-04 | Current approved/verified SOT changes carry deep evidence metadata | P0 |
| REQ-038-05 | Stale or expired records disclose an attention state, not stale content as current truth | P0 |
| REQ-038-06 | Research signals are separately labeled and never cited as SOT | P0 |
| REQ-038-07 | DLP-blocked content is omitted without leaking its existence | P0 |
| REQ-038-08 | Results are bounded, deterministic and diversified by source | P0 |
| REQ-038-09 | Each useful signal offers a safe Ask follow-up; no automatic mutation occurs | P0 |
| REQ-038-10 | Empty, denied and unavailable states are explicit in VI/EN | P1 |
| REQ-038-11 | Desktop, narrow screen, keyboard and reduced-motion remain usable | P0 |
| REQ-038-12 | Viewing a briefing leaves a content-free audit event | P0 |
| REQ-038-13 | Synthetic test/integration packages are excluded before authorization and content access | P0 |

## Product contract

`GET /api/v1/intelligence/briefing?limit=12`

- `items`: at most 20 policy-filtered signals.
- `zone_label`: literal `sot` or `research`.
- `kind`: `update`, `attention` or `research`.
- `priority`: `high` or `normal`.
- `summary`: DLP-inspected text; stale/expired SOT items receive metadata-only
  wording instead of their value.
- `evidence`: immutable version/checksum/source locator appropriate to its
  trust zone.
- `ask_query`: bounded follow-up text only; it does not execute automatically.

## Acceptance criteria

- **AC-01:** anonymous calls receive 401 with no item counts.
- **AC-02:** a denied record never enters the content query or response.
- **AC-03:** an authorization revoked between metadata and disclosure removes
  the item.
- **AC-04:** current verified SOT content returns with `zone_label=sot` and an
  immutable evidence reference.
- **AC-05:** expired/stale SOT content returns only an attention explanation.
- **AC-06:** visible Research returns only as `kind=research`,
  `zone_label=research` with its package/evidence identity.
- **AC-07:** DLP rejection removes the item and records only rule IDs/counts.
- **AC-08:** the API is bounded, source-diversified and stable for equal input.
- **AC-09:** selecting “Hỏi tiếp” opens Ask with a prefilled editable question.
- **AC-10:** unit, integration, lint, type, build, accessibility and browser
  checks pass without LLM, embedding, crawler or connector calls.
- **AC-11:** a package produced by a test/integration fixture never reaches
  authorization, content loading or the employee briefing.

## Design direction

**Subject:** a quiet internal signal desk for RtR employees.

**Single job:** show what changed, what needs verification and what external
evidence may matter next.

The signature is one continuous **evidence spine**: a thin vertical rule joins
signals in time while zone labels and source provenance carry meaning. There
are no decorative KPI cards. The palette, Inter typography and spacing inherit
the current black/grey/white system. Motion is limited to one loading sweep and
is disabled by `prefers-reduced-motion`.

## Out of scope

- Scheduled email/chat notifications.
- CRM/MRP/HRM/IP/Google Workspace/Slack connector activation.
- Forecast claims generated without governed evidence.
- Automatic proposals, policies, reports, publication or outreach.
- Production deployment and production secrets.

## Closure evidence

- [TIP-038 Completion Report](TIP-038_COMPLETION_REPORT.md)
- [TIP-038 Verify Report](TIP-038_VERIFY_REPORT.md)
