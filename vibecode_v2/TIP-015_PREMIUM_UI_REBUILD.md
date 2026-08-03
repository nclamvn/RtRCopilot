# TIP-015 · Premium UI Rebuild (PRD UI/UX v1.0)

**Depends:** TIP-011 (Unified UX), TIP-014 (query understanding — unaffected).
**Branch:** `tip-013b` (active integration branch).
**Contractor:** authored this packet; the same agent executes the Builder slice and the independent Verify slice per the Vibecode role cycle (Thầu → Thợ → Thầu-verify).
**Homeowner:** no production `--apply`, secret, or kernel action in this TIP (UI-only, no backend/API/migration changes).

---

## 1. Objective

Rebuild the front-of-house interface to the **PRD UI/UX v1.0 "RtR Copilot V2 Premium Interface"** — a deeptech-grade, evidence-first product identity — replacing the frozen dark-graphite editorial chrome on the in-scope surfaces, **without touching the backend, the API contract, retrieval/grounding, ACL/ABAC, or any migration**. The product must remain a single shell with one Evidence Rail, keyboard-first, WCAG 2.2 AA, VI/EN at parity — i.e. every guarantee TIP-011 earned must survive the reskin, proven by the same gates, not by assertion.

## 2. Scope

**In scope (PRD §"Phạm vi"):** Unified Shell (topbar + sidebar), Ask Workspace, Evidence Rail; the design-token system (light + dark), typography (Inter), iconography (Lucide), motion, and the command palette.

**Out of scope (PRD §19 — frozen this TIP):** full Admin page, backend changes, API-contract changes, auto-graduation, File Viewer redesign, full Document OS redesign, RBAC/ABAC changes, grounding-rule changes. Files / Documents / Knowledge-Ops keep their frozen styling; they inherit only the new shell chrome that wraps them.

## 3. Decisions (D-015-##)

- **D-015-01 — Additive token layer, legacy frozen.** New `--pc-*` tokens live in `src/app/styles/{tokens,themes,typography,motion,shell,ask}.css`, imported after the frozen `styles.css`. The frozen TIP-011 tokens (`--bg/--panel/--ink/--signal/--locator/…`) are **not** renamed or deleted, so out-of-scope pages render byte-for-byte as before. New surfaces consume only `--pc-*`.
- **D-015-02 — Theme + density are cookie-only, resolved SSR.** `rtr_theme` (default **dark** = shipped identity; light is first-class) and `rtr_sidebar` follow the `rtr_locale` precedent: cookie only, never browser storage (D-011-05), resolved in the server layout so first paint carries the preference with no flash / no hydration mismatch.
- **D-015-03 — Ask/Rail reskin is CSS-scoped under `.ask-workspace`.** The same class names shared with the frozen pages (`.evidence-rail`, `.zone-chip`, `.page-head`, `.surface-*`) are restyled only when nested under `.ask-workspace`; the shared rail on Files/Documents/Knowledge-Ops is untouched. No markup/logic change to the frozen TIP-007 answer flow.
- **D-015-04 — No new runtime dependency.** Lucide icons are inlined as SVG path data (`src/shell/Icon.tsx`, stroke 1.75); the command palette and theme/locale switches are hand-rolled accessible React (no Radix). The offline Docker build stays deterministic.
- **D-015-05 — Composer becomes a textarea (PRD §11).** The single-line question input is replaced by an auto-expanding textarea (64–180px), Enter=submit / Shift+Enter=newline. This preserves the existing keyboard-submit contract (ask.spec expects Enter to submit) and adds multiline capability.
- **D-015-06 — Citation keyboard nav (PRD §14).** `[` / `]` move the active citation to the previous/next Evidence Rail entry when focus is inside the rail.
- **D-015-07 (deferral) — Mobile bottom-dock nav (PRD §13) is deferred to a follow-up UI TIP.** Rationale: a second nav duplicating the six links with identical accessible names collides with the role-uniqueness the a11y/e2e gates rely on, and the off-canvas drawer already delivers full mobile navigation that passes axe and 0-overflow at 360px. Recorded here, not silently dropped.
- **D-015-08 (deferral) — `output: standalone`** in `next.config` means local browser gates run against `next start` (fallback) or `next dev`; the CI runbook is a TIP-012 concern, unchanged.

## 4. Acceptance criteria (mapped to PRD DoD §21)

| AC | Criterion |
|---|---|
| AC-01 | Light **and** dark themes both render correctly across shell/ask/rail; toggle persists via cookie, no flash. |
| AC-02 | Sidebar density fixed: scroll region flexes, **user profile pinned to the bottom**; 264/72 collapse works. |
| AC-03 | Reading text ≥16px (answer 16px/1.72); no body copy <12px. |
| AC-04 | VI ⇄ EN with **no layout break**, cookie-only, `<html lang>` flips; catalog parity compile- + run-time. |
| AC-05 | Citation marker opens the exact Evidence Rail entry; rail operable by **mouse and keyboard** (incl. `[`/`]`). |
| AC-06 | Honest-null presented as a **first-class state** (not an error), with gap id/state + owner link. |
| AC-07 | **axe 0 critical/serious** across 5 pages × 4 viewports × 2 locales + stateful surfaces. |
| AC-08 | **No horizontal overflow** across the full matrix; reduced-motion freezes the chrome (0s). |
| AC-09 | **No backend / API / migration change** (single alembic head unchanged; no server route touched). |
| AC-10 | Composer is an auto-expanding textarea; Enter submits, Shift+Enter newlines. |
| AC-11 | Identity = "deeptech premium, not a chatbot template"; command palette (⌘K), ⌘N, ⌘1/2/3, F6, skip link all live. |
| AC-12 | **No regression:** web vitest + full Playwright suite green on the final tree. |

## 5. Gates with teeth (must run, not be asserted)

1. `tsc --noEmit` (strict) — 0 errors on app/src.
2. `eslint .` — 0 errors.
3. `vitest run src` — all green (no count regression vs pre-TIP).
4. `next build` — EXIT 0 (compiles + full typecheck).
5. `@axe-core/playwright` matrix — **0 critical/serious** everywhere; 0px overflow; reduced-motion 0s.
6. Full Playwright suite (`next start`, chromium) — **100% pass**, including keyboard-only flows and the F6 cycle.

A gate that cannot be run in the sandbox is recorded as such in the Verify Report, never green-by-assertion.

## 6. DRY-RUN (plan before touching the tree)

Phase 1 Foundation → tokens/themes/typography/motion + Icon + theme.ts + layout wiring.
Phase 2 Shell → AppShell rewrite (workspace switcher, new-question, grouped nav, recent, integrity, pinned profile, collapse, topbar, ⌘K palette).
Phase 3 Ask → scoped premium reskin + composer textarea.
Phase 4 Rail → scoped premium reskin + `[`/`]` nav.
Phase 5 Quality gate → run §5, fix defects the gates surface (record contrast ratios), write Completion + Verify.

## 7. Deferrals (carried forward)

- D-015-07 bottom-dock mobile nav → next UI TIP.
- PRD §11 secondary composer affordances (attachment chips) not requested → out of scope.
- File/Document/Admin redesign → out of scope by PRD §19 (unchanged).
