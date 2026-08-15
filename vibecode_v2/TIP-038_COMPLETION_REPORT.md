# TIP-038 Completion Report — Proactive Enterprise Intelligence

**Date:** 15/08/2026
**Status:** `COMPLETE_LOCAL`
**Base commit:** `b249a20`
**Runtime:** rebuilt primary local API/Web; 7/7 primary services healthy
**External processing:** 0 LLM calls; 0 embedding calls; 0 connector calls

## Outcome

RtR Copilot now has a proactive, read-only intelligence surface at
`/intelligence`. It presents approved company changes, governed records that
need freshness review and separately labeled Research signals before an
employee knows what question to ask.

This is not a second truth plane. The briefing is computed live from current
SOT and Research metadata, remains policy scoped per employee and preserves
the existing Ask workflow as the only synthesis boundary.

## Delivered

- Authenticated `GET /api/v1/intelligence/briefing` with bounded response and
  strict SOT/Research evidence contracts.
- Metadata-first authorization, content loading only for permitted identities
  and a second authorization check before disclosure.
- Stale/expired SOT records shown as metadata-only review tasks; stale values
  are never loaded or presented as current fact.
- Separate Research identity, package fingerprint, trust tier and
  corroboration state; Research never masquerades as SOT.
- Local DLP inspection, deterministic ranking and per-source diversity quota.
- Synthetic test/integration packages filtered before authorization or content
  access, preventing certification fixtures from entering employee UI.
- Content-free append-only audit event for every successful briefing view.
- Compact monochrome evidence-spine UI, evidence rail, VI/EN copy and safe
  “Hỏi tiếp” handoff to an editable Ask question.
- Staff navigation, anonymous gate, loading/error/empty states, keyboard,
  mobile, reduced-motion and accessibility coverage.

## Acceptance result

| AC | Result | Evidence |
|---|---|---|
| 01 anonymous denial | PASS | API unit and UI gate tests |
| 02 denied content never loads | PASS | metadata/content query-order unit test |
| 03 authorization recheck | PASS | SOT and Research revocation tests |
| 04 current SOT evidence | PASS | contract tests and rebuilt live runtime |
| 05 stale metadata-only disclosure | PASS | content-load assertion and localized UI |
| 06 Research remains separate | PASS | API contract, UI and browser E2E |
| 07 local DLP omission | PASS | service guard and audit rule-id boundary |
| 08 bounded/diversified result | PASS | service limits and live 9 SOT + 3 Research |
| 09 safe Ask handoff | PASS | component and browser E2E |
| 10 engineering/a11y gates | PASS | backend, web, browser and integration gates |
| 11 fixture exclusion | PASS | pre-policy unit test and live corpus inspection |

## Scope boundary

TIP-038 is complete for local product use. It does not schedule notifications,
activate CRM/MRP/HRM/IP/Google Workspace/Slack connectors, publish reports,
perform autonomous actions or change production configuration. The existing
untracked `../_to_delete/` directory was not touched.
