# VERIFY REPORT — TIP-017 · Keyboard & Theming Completeness

**Date:** 03/08/2026
**Verifier:** Contractor (independent verify — Builder numbers re-run).
**Environment:** Next.js 16.2.11 production build via `next start`; Chromium 1234 (`@playwright/test` 1.62.0); `@axe-core/playwright` 4.12.1.
**Method:** rerun every gate on the final tree; adversarial focus on the help dialog's modal a11y and the `?`-in-composer guard; visual confirmation of the dialog in light.

---

## Verdict

**VERIFIED · READY (cloud scope).**

- Acceptance criteria: **6/6 PASS**. P0/P1 open: **0/0**.
- Gate chính — *discoverable keyboard help (accessible modal) + axe 0 both themes × both locales*: **PASS**.

## Scenario results (independently rerun)

| AC | Verdict | Bằng chứng chính |
|---|---|---|
| AC-01 `?` + topbar button open the help dialog listing all shortcuts | PASS | shell.spec: `?` opens; topbar "Phím tắt" opens; dialog lists ⌘K…Esc |
| AC-02 accessible modal: role, label, Esc + backdrop close, focus managed | PASS | `role=dialog aria-modal`; Esc closes; close-button focused on open; focus returns to opener |
| AC-03 `?` inside the composer does NOT open it | PASS | shell.spec: typing `?` in `.ask-question textarea` leaves the dialog hidden |
| AC-04 axe 0 with the help dialog open | PASS | axe stateful "help dialog open" — 0 critical/serious |
| AC-05 light-axe now covers EN too | PASS | 5 pages × 4 viewports × {vi,en} light = 0 critical/serious; 0 overflow |
| AC-06 no regression; next build | PASS | vitest 148/148; Playwright **87/87**; `next build` EXIT 0; no backend/API/migration |

Failed: **0**.

## Technical health (independent)

`tsc` strict 0; `eslint` 0; `next build` EXIT 0; web vitest **148/19**; Playwright **87/87** on the production build (axe dark + light, both locales; 11 stateful incl. the help dialog; 5 keyboard flows; reduced-motion; dock; shell/ask/files/documents/knowledge-ops). No new runtime dependency.

## Deferred (có chủ đích, không chặn)

1. rgba() overlay token-isation — pixel-polish, axe already green.
2. `prefers-color-scheme` auto-default — test-matrix ripple; deferred with a pre-paint-script plan.

## Critical issues

None.

## Decisions needed from Homeowner

None blocking. TIP-017 merge-eligible on `tip-013b`. Push to the real remote + full-compose re-run remain the Homeowner's steps.

*Không sửa ngược sau khi commit; bổ sung bằng addendum nếu có kết quả mới.*
