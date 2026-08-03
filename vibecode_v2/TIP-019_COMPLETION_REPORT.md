# COMPLETION REPORT — TIP-019 · Theming Zero-Debt

**STATUS:** DONE — one Builder slice on `tip-013b` under the Vibecode role cycle (Thầu → Thợ → Thầu-verify). No backend/API/migration change.

## What was built

- **WP-A — rgba overlays token-ised.** Every colored `rgba()` literal in `styles.css` now flows through `color-mix(in srgb, var(--pc-…) N%, transparent)` by meaning (orange→warning/danger tints, teal→accent, green→success); the neutral scrims (`rgba(0,0,0,.6)`) use the theme-aware `var(--pc-scrim)`. Only the intentional dark draft-watermark backdrop stays fixed-dark (contrast over arbitrary previews). No colored literal debt remains.
- **WP-B — prefers-color-scheme default (no flash).** With no `rtr_theme` cookie the server omits `data-theme` (`suppressHydrationWarning`) and CSS resolves the visitor's OS scheme: `:root`=light, `@media(prefers-color-scheme:dark) :root:not([data-theme])`=dark — first paint already matches the OS, no script, no hydration error. Choosing a theme writes the cookie + explicit attribute (overrides the OS). The toggle reads the *applied* theme (attribute → else `matchMedia`) so its icon is correct with no cookie and follows OS changes live until the visitor picks. Playwright `use.colorScheme:'dark'` holds the default matrix on the shipped identity; the light-axe tests set the cookie (explicit wins).

## Gates (final tree — independently rerun by the Contractor)

| Gate | Result |
|---|---|
| web `tsc --noEmit` (strict) | **PASS** — app/src clean |
| web `eslint .` | **PASS** — 0 (no warnings) |
| web `vitest run src` | **148 passed / 19 files** |
| `next build` (compile + full TS) | **EXIT 0** |
| Playwright (production `next start`, chromium 1234) | **88/88** (from 87: +prefers-color-scheme e2e) |
| axe — both themes × both locales | **0 critical/serious** |
| backend / API / migration | **untouched** |

## Issues / escalations

None — the axe matrix (both themes × both locales) stayed green through the overlay migration; the prefers-color-scheme change passed on the first full run.

## Deviations of note

- The dark token block is duplicated once inside the `@media(prefers-color-scheme:dark)` fallback (marked "KEEP IN SYNC") — the only way in plain CSS to serve the no-cookie OS default without a script.
- `readThemeCookie` (null when unset) replaces `resolveTheme` at the layout boundary; `resolveTheme` retained.

## Deferred

Theming is now zero-debt for the in-scope surfaces. No further theming items outstanding.
