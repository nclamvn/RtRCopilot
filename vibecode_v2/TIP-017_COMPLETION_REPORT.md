# COMPLETION REPORT — TIP-017 · Keyboard & Theming Completeness

**STATUS:** DONE — one Builder slice on `tip-013b` under the Vibecode role cycle (Thầu authored → Thợ built WP-A/B → Thầu verified). No backend/API/retrieval/ACL/migration change; single alembic head unchanged.

## What was built

- **WP-A — Keyboard shortcuts help dialog (PRD §14 discoverability).** A `?` key (guarded — inert inside inputs/textareas/contenteditable) and a topbar `?` button open an accessible modal (`role="dialog" aria-modal`, labelled, Esc + backdrop close, focus in / focus-return to the opener) listing every shell shortcut: ⌘K, ⌘N, ⌘1/2/3, F6/⇧F6, `[`/`]`, Esc. Reuses the command-palette dialog shape — no new primitive, no new dependency. New `shell.help.*` i18n (VI+EN, parity).
- **WP-B — EN light-axe.** The TIP-016 light-theme axe pass now iterates both locales, so the colour gate covers **both themes × both locales** for all five pages.

## Gates (final tree — independently rerun by the Contractor)

| Gate | Result |
|---|---|
| web `tsc --noEmit` (strict) | **PASS** — app/src clean |
| web `eslint .` | **PASS** — 0 |
| web `vitest run src` | **148 passed / 19 files** |
| `next build` (compile + full TS) | **EXIT 0** |
| Playwright (production `next start`, chromium 1234) | **87/87** (from 80: +help e2e, +help-dialog axe, +5 EN light pages) |
| axe — dark + **light**, **both locales** | **0 critical/serious** — 5 pages × 4 viewports × 2 locales × 2 themes + 11 stateful (incl. help dialog) |
| horizontal overflow | **0px** across the matrix |
| backend / API / migration | **untouched** |

## Issues / escalations

None — no defect surfaced by the gate this TIP (the help dialog reused the already-AA palette shape; the EN light pages passed on the first run, confirming the TIP-016 token migration is locale-independent).

## Deviations of note

- Topbar gains a `?` affordance next to the theme switch; the `?` hotkey is guarded so it never fires while composing.
- Only additive: `shell.help.*` i18n + a `HelpDialog` component + CSS; no new runtime dependency.

## Deferred

- **rgba() overlay token-isation** — axe passes with the translucent tints; pixel-polish deferred.
- **`prefers-color-scheme` auto-default** — deferred (would ripple through the whole test matrix; needs a pre-paint script). Shipped default stays dark.
