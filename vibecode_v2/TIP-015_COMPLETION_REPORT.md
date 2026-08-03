# COMPLETION REPORT — TIP-015 · Premium UI Rebuild (PRD UI/UX v1.0)

**STATUS:** DONE — one Builder slice on branch `tip-013b`, executed and consolidated under the Vibecode role cycle (Thầu authored TIP-015 → Thợ built → Thầu verified independently). No backend, API, retrieval/grounding, ACL/ABAC, or migration change; single alembic head unchanged.

## What was built

- **Design-token foundation (light + dark).** `src/app/styles/{tokens,themes,typography,motion}.css`: the exact PRD palette (accent `#315efb`/`#6f8cff`, full light + dark), Inter type scale, 4px spacing, 8/11/14/16/999 radii, motion easings. Legacy TIP-011 tokens left frozen (D-015-01), so out-of-scope pages render unchanged.
- **Unified Shell rewrite** (`src/shell/AppShell.tsx` + `styles/shell.css`): workspace switcher, new-question (⌘N), grouped icon navigation with the active area treated (surface + hairline + icon-on-accent + 3px left bar + `aria-current`), recent conversations, system-integrity card (fed by the real `/api/status`, no fabricated %), **user profile pinned to the bottom**, 264/72 collapsible sidebar, and a hand-rolled **⌘K command palette**. Topbar carries the product brand, palette search, VI/EN switch and the Sun/Moon theme switch. Every TIP-011 contract preserved: skip link first, one `<nav>` landmark, F6/Shift+F6 region cycle, cookie-only locale, anonymous sign-in.
- **Dependency-free Lucide icon set** (`src/shell/Icon.tsx`, inline SVG, stroke 1.75) — no new runtime package (D-015-04).
- **Theme/density plumbing** (`src/shell/theme.ts`, root + `(shell)` layouts): `rtr_theme` (default dark) and `rtr_sidebar` resolved SSR from cookies — no flash, no hydration mismatch, no browser storage (D-015-02).
- **Ask Workspace + Evidence Rail premium reskin** (`styles/ask.css`, scoped under `.ask-workspace`, D-015-03): display-scale header, premium composer/scope/answer/honest-null/research/history cards, blue citation-marker pills, confidence caveat, and a rail whose active citation reads as a **2px accent ring on a neutral surface** (PRD "blue border"; chosen over an accent-soft fill that dropped the 9px labels to 4.2:1).
- **Composer = auto-expanding textarea** (D-015-05, PRD §11): 64–180px auto-grow, Enter submits, Shift+Enter newlines — preserving the existing keyboard-submit contract.
- **Citation keyboard nav** (D-015-06, PRD §14): `[` / `]` step the active citation to the previous/next rail entry (wraps) and move focus with it, when focus is inside the rail.
- **i18n:** shell catalog extended with the new premium strings (workspace, groups, new-question, recent, integrity, theme, collapse, palette) — VI source + EN twins, compile- + run-time parity kept.

## Gates (final tree — independently rerun by the Contractor)

| Gate | Result |
|---|---|
| web `tsc --noEmit` (strict) | **PASS** — app/src clean |
| web `eslint .` | **PASS** — 0 |
| web `vitest run src` | **148 passed / 19 files** (no regression) |
| `next build` (compile + full TS incl. tests) | **EXIT 0** |
| Playwright (production `next start`, chromium 1234) | **75/75** (from 74: +1 new `[`/`]` citation-nav proof) |
| axe (`@axe-core/playwright`) matrix | **0 critical/serious** — 5 pages × 4 viewports × 2 locales + 10 stateful surfaces |
| horizontal overflow | **0px** across the matrix |
| reduced-motion | computed **0s** on shell/ask/rail chrome |
| backend / API / migration | **untouched** — no server route, no alembic head change |

## Issues / escalations resolved by Contractor decision

- **axe defect (real, found by the gate, fixed):** the active citation card used an `--pc-accent-soft` fill, dropping the 9px muted `dt` labels to **4.2:1** on dark. Resolved by switching the active treatment to a neutral `--pc-surface-subtle` + 2px accent ring — the PRD "blue border" intent — keeping every rail label ≥4.5:1. Contrast ratio recorded.
- **light-theme token nudge:** `--pc-text-muted` and `--pc-success` were darkened from the raw PRD values so small labels and the grounded-answer note clear AA on the light surfaces (≥5:1); PRD deviation noted in `themes.css`.
- **reduced-motion:** the in-scope kill-rule was aligned to computed `0s` (not `0.001ms`) to match the frozen-chrome gate.

## Deviations of note

- Root/`(shell)` layouts now read `rtr_theme`/`rtr_sidebar` cookies (SSR) alongside the existing locale cookie.
- Two spec assertions retargeted for the new structure (drawer `open` on `#pc-sidebar`; composer `.ask-question textarea`), and the shell's best-effort `/api/ask/conversations` recent-list fetch mocked.
- Only additive CSS + one new client component (`Icon`) + one helper (`theme.ts`); no new runtime dependency.

## Deferred (recorded, not dropped)

- **D-015-07** mobile bottom-dock nav (PRD §13) → next UI TIP (duplicate-name role collision vs. the a11y/e2e gates; the off-canvas drawer already passes axe + 0-overflow at 360px).
- Files/Documents/Admin redesign → out of scope by PRD §19 (unchanged this TIP).
