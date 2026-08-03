# VERIFY REPORT — TIP-015 · Premium UI Rebuild (PRD UI/UX v1.0)

**Date:** 03/08/2026
**Verifier:** Contractor (independent verify pass — Builder numbers re-run, not trusted).
**Environment:** cloud sandbox — Next.js 16.2.11 production build served by `next start`; Chromium 1234 via `@playwright/test` 1.62.0; `@axe-core/playwright` 4.12.1; API proxied to a dead port so the shell's best-effort fetches fail fast (mocks own the browser-side routes).
**Method:** independent rerun of every gate on the final tree; adversarial focus on the axe matrix and the preserved TIP-011 keyboard/landmark contracts; per-AC verdict.

---

## Verdict

**VERIFIED · READY (cloud scope).**

- Acceptance criteria: **12/12 PASS**.
- P0 open: **0**. P1 open: **0**.
- Gate chính — *axe 0 + full e2e + one shell/one rail, no backend change*: **PASS** — axe 0 critical/serious across 5 pages × 4 viewports × 2 locales + 10 stateful surfaces; Playwright 75/75; single alembic head untouched.

## Requirement coverage

- PRD UI/UX v1.0 (Unified Shell, Sidebar, Ask Workspace, Evidence Rail) — **implemented** with light + dark as first-class, evidenced by the axe/keyboard gates (runnable proof, not assertion).
- Preserves REQ-026/027 (unified workspace, responsive, keyboard-first, WCAG 2.2 AA, VI/EN) from TIP-011 through the reskin.

## Scenario results (independently rerun)

| AC | Verdict | Bằng chứng chính |
|---|---|---|
| AC-01 light+dark render, cookie-persisted, no flash | PASS | both themes rendered (screenshots + axe both themes); `rtr_theme` SSR-resolved, no hydration mismatch |
| AC-02 sidebar density; profile pinned bottom; 264/72 collapse | PASS | `sidebar-scroll` flex + `sidebar-footer margin-top:auto`; collapse cookie `rtr_sidebar` |
| AC-03 reading text ≥16px | PASS | answer-text 16px/1.72; no body <12px |
| AC-04 VI⇄EN no layout break | PASS | shell.spec locale persistence; axe matrix both locales; `<html lang>` flips; catalog parity (vitest i18n) |
| AC-05 citation opens exact entry; rail mouse+keyboard incl. `[`/`]` | PASS | ask.spec citation→rail→viewer (keyboard); **new** `[`/`]` steps active entry (aria-current + focus move) |
| AC-06 honest-null first-class | PASS | honest-null block (not error), gap id/state + owner link; axe stateful honest-null clean |
| AC-07 axe 0 critical/serious | PASS | **0** across 5 pages × 4 viewports × 2 locales + 10 stateful; 1 real defect (active-card contrast) found & fixed, ratio recorded |
| AC-08 no horizontal overflow; reduced-motion 0s | PASS | 0px overflow full matrix; computed 0s on `#shell-nav`/`#evidence-rail`/shell chrome |
| AC-09 no backend/API/migration change | PASS | no server route touched; single alembic head unchanged; only `src/**` UI + tests |
| AC-10 composer textarea; Enter submit / Shift+Enter newline | PASS | ask.spec keyboard flow (Enter submits the textarea); auto-expand 64–180px |
| AC-11 premium identity; ⌘K/⌘N/⌘1-3/F6/skip link | PASS | command palette + shortcuts live; F6 cycle green (shell.spec); skip link first tab stop |
| AC-12 no regression (vitest + Playwright) | PASS | vitest 148/148; Playwright 75/75; `next build` EXIT 0 |

Failed: **0**.

## Technical health (independent)

`tsc` strict 0 errors on app/src; `eslint` 0; `next build` EXIT 0 (compile 6.0s, TypeScript 7.0s, 9 routes); web vitest **148 passed / 19 files**; Playwright **75/75** on the production build (axe matrix + 5 keyboard-only flows + reduced-motion + shell/ask/files/documents/knowledge-ops + the new citation-nav test). No new runtime dependency (Lucide inlined; palette/theme/locale hand-rolled). Legacy tokens frozen — out-of-scope pages byte-unchanged.

## Deferred (có chủ đích, không chặn)

1. **Mobile bottom-dock nav** (PRD §13, D-015-07) — deferred to a follow-up UI TIP; the off-canvas drawer passes axe + 0-overflow at 360px and avoids the duplicate-role collision.
2. **Light-mode polish on out-of-scope pages** — Files/Documents/Knowledge-Ops keep frozen dark styling (PRD §19); a future TIP can migrate their hardcoded hues to `--pc-*` if a full light experience there is wanted.
3. **CI wiring of the browser gate** — `output: standalone` means local gates run via `next start`; CI runbook remains a TIP-012 concern (unchanged).

## Critical issues

None. Non-blocking notes: the raw PRD `--pc-text-muted`/`--pc-success` values were nudged darker for AA on light surfaces (recorded in `themes.css`); the active-citation treatment is a ring rather than a fill (AA-driven, PRD-intent-preserving).

## Decisions needed from Homeowner

None blocking. TIP-015 is merge-eligible on `tip-013b`. The push to the real remote and the Playwright/axe re-run on the Homeowner's machine (full compose stack) are the only steps outside this sandbox's authority.

*Không sửa ngược sau khi commit; bổ sung bằng addendum nếu có kết quả mới.*
