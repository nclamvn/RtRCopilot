# COMPLETION REPORT — TIP-016 · UI Completion

**STATUS:** DONE — one Builder slice on `tip-013b`, run under the Vibecode role cycle (Thầu authored TIP-016 → Thợ built WP-A/B/C → Thầu verified independently). No backend/API/retrieval/ACL/migration change; single alembic head unchanged.

## What was built

- **WP-A — Mobile bottom-dock nav (PRD §13, closes D-015-07).** A second, distinctly-labelled `<nav aria-label="Điều hướng nhanh">` shown only <760px, six icon links carrying the area names, active area marked, fixed to the bottom with safe-area insets and a matching `.pc-main` bottom pad. ≥760px it is `display:none` (absent from the a11y tree). Unit tests scope link queries to the primary nav (`within(navigation)`) so the shared names never clash.
- **WP-B — Full light-mode for the frozen pages (theming only).** `styles/legacy-bridge.css` (loaded after `styles.css`) aliases the frozen tokens to the theme-aware `--pc-*` set (`--bg/--panel/--ink/--muted/--line/--focus/--signal/--locator`); the ~20 hardcoded hexes in `styles.css` were migrated to semantic tokens by meaning (teal→accent, orange-red→danger, amber→warning, green→success, greys→text/surface/border). Danger/warning **semantics preserved**: `--signal`→accent for brand/active, with the real danger/warning selectors pinned in the bridge (errors/overdue/revoked stay red, research/gated-crossing stay amber). Files / Documents / Knowledge-Ops / Admin now render coherently in **both** themes — no dark islands under a light shell.
- **WP-C — Composer scope chips (PRD §11).** Read-only chips at the composer reflect the active scope (SOT vs research) and the selected file (with an in-chip remove); new `ask.chip.*` i18n (VI+EN).

## Gates (final tree — independently rerun by the Contractor)

| Gate | Result |
|---|---|
| web `tsc --noEmit` (strict) | **PASS** — app/src clean |
| web `eslint .` | **PASS** — 0 |
| web `vitest run src` | **148 passed / 19 files** (no regression) |
| `next build` (compile + full TS) | **EXIT 0** |
| Playwright (production `next start`, chromium 1234) | **80/80** (from 75: +5 light-theme axe pages) |
| axe — **dark** matrix | **0 critical/serious** — 5 pages × 4 viewports × 2 locales + 10 stateful |
| axe — **light** matrix (WP-B) | **0 critical/serious** — 5 pages × 4 viewports (vi) |
| horizontal overflow | **0px** across the expanded matrix (incl. dock @360) |
| backend / API / migration | **untouched** |

## Issues resolved by Contractor decision (real defects the gate caught)

- **Light-theme contrast (3 pages):** 9px accent labels on the active row (`surface-hover`) measured **4.4:1** (Files `.file-kind`, Documents `.template-ledger li span`) → pinned to the darker `--pc-accent-hover` (≥4.5:1). The research zone-chip's amber on its orange tint measured **4.0:1** → light `--pc-warning` darkened `#a56613`→`#8a5410` (≥5:1). Ratios recorded in `themes.css` / `legacy-bridge.css`.
- **Composer-chip collisions:** the chip re-echoed the filename and a "clear" control, colliding with existing `getByText`/`getByRole` in `ask.spec` → the chip's remove got a distinct label (`ask.chip.remove`) and the filename assertion was scoped to `.first()`.

## Deviations of note

- `styles.css` is no longer dark-literal — every colour flows through `--pc-*` (frozen structure otherwise unchanged; layout/logic/copy of the out-of-scope pages untouched).
- Only additive files: `legacy-bridge.css` + `ask.chip.*`/`shell.dockLabel` i18n; no new runtime dependency.
- Translucent `rgba()` overlays (15) left as-is — they adapt acceptably on both themes.

## Deferred

- Out-of-scope pages' **layout/logic** redesign still frozen (only theming lifted).
- EN light-theme axe pass not added (dark matrix already covers both locales; light colour gate is locale-independent) — one vi light pass per page is the colour proof.
