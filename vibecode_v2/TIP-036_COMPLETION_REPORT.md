# COMPLETION REPORT — TIP-036

**Date:** 15/08/2026

**Scope:** Ask-to-Artifact Orchestration

**Base source:** `7644563096c91942cb8fe295fa18804099685ccd`

**Status:** `COMPLETE`

## Outcome

RtR Copilot can now recognize a Vietnamese or English request to create an
artifact, classify it into a bounded generic family and propose only an
approved template that the authenticated employee may both view and render.
The grounded Ask answer remains independent: planner failure cannot suppress or
downgrade the answer.

The handoff is deliberately non-executing.  The employee must select a proposal
before Copilot opens Document OS at the immutable template version.  Existing
binding, SOT, render, approval and issuance controls remain authoritative; no
draft, approval, publication or delivery is automatic.

## Root cause closed during live verification

The old runtime snapshot counted eight approved template rows, but four were
integration fixtures and the four canonical TIP-024 templates were still
private-context resources without role ACLs.  This produced a misleading
state: governance reports could count templates while an ordinary staff
session correctly saw an empty registry.

The canonical TIP-024 bootstrap now grants deterministic, audited `view` and
`render` ACLs to the active `staff`, `leader`, `curator` and `admin` role IDs for
the exact four internal-pilot versions.  It remains local-only and idempotent.
No fixture template, official stationery or legal template is exposed.

## Implemented surface

- `POST /api/v1/artifact-plans` with strict request and response contracts.
- Deterministic, accent-insensitive intent recognition without an LLM call.
- Families: document, report, form, presentation and spreadsheet.
- Semantic template compatibility prevents broad DOCX affinity from proposing
  a government letter as a generic report.
- Maximum three current, approved, viewable and renderable candidates.
- Required user fields disclosed without leaking source files or inaccessible
  schema content.
- Compact monochrome proposal below the Ask answer.
- Handoff URL contains only `template=<version UUID>` and `from=ask`; prompt and
  evidence are not placed in URL, localStorage or sessionStorage.
- Existing four-template internal pilot registry restored for company roles:
  Công văn, Fact-sheet, Sales Brief and Slide Card.

## Live acceptance results

| Scenario | Result |
|---|---:|
| `HERA làm gì?` | `not_applicable`; no artifact proposal |
| `Tạo báo cáo hoạt động công ty` | Report-only candidates; no government-letter/slide mismatch |
| `Soạn công văn gửi Bộ Khoa học và Công nghệ` | Exact Công văn template only |
| `Tạo bảng tính ghi nhận buổi gặp khách hàng` | Exact Sales Brief XLSX only |
| Staff template listing | Four canonical approved internal templates |
| Ask handoff | Exact immutable version selected in Document OS |
| Automatic render/approve/issue/publish | None |

## Boundary

- External LLM/embedding calls: 0.
- Corpus, ontology, isolated pilot and connector activation: none.
- Production configuration/deployment: none.
- Primary local DB mutation: 32 deterministic ACL grants on first bootstrap;
  zero grants on the second run.
- Included in the joint TIP-036/TIP-037 milestone publication.
- Unrelated `../_to_delete/` remains untouched and unstaged.

## Next product sequence

1. TIP-037 — Multimodal Composer & Attachment-to-Context.
2. TIP-038 — Proactive Enterprise Intelligence.
3. TIP-039 — Corpus Expansion and Domain-stratified Evaluation.
4. Keep CRM/MRP/IP/HRM, Google Workspace and Slack/native chat as connector-ready
   contracts until those systems are ready to integrate.
