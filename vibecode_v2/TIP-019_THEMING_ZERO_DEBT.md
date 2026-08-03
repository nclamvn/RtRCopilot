# TIP-019 · Theming Zero-Debt (rgba token-isation + prefers-color-scheme)

**Depends:** TIP-016, TIP-017. **Branch:** `tip-013b`. **Contractor** authored + verifies; **Builder** same agent. **Homeowner:** no backend/API/migration; UI-only.

## 1. Objective

Remove the last theming debt: (WP-A) token-ise the colored `rgba()` overlays in `styles.css` so tints follow the palette in both themes; (WP-B) default the theme from the visitor's OS `prefers-color-scheme` when no `rtr_theme` cookie is set — no flash, cookie still wins once the user chooses.

## 2. Decisions (D-019-##)

- **D-019-01** colored overlays → `color-mix(in srgb, var(--pc-…) N%, transparent)` by meaning (orange→warning/danger, teal→accent, green→success); neutral scrims `rgba(0,0,0,.6)`→`var(--pc-scrim)` (theme-aware). The dark draft-watermark backdrop stays fixed-dark (intentional contrast over arbitrary previews).
- **D-019-02** no-cookie default via **CSS media fallback** (no inline script): `:root`=light; `@media(prefers-color-scheme:dark) :root:not([data-theme])`=dark. Server omits `data-theme` when no cookie (`suppressHydrationWarning`), so first paint already matches the OS with zero flash and no hydration error.
- **D-019-03** the theme toggle reads the *applied* theme (`data-theme` attr, else `matchMedia`) so its icon is correct even with no cookie; clicking sets an explicit cookie + attribute (overrides the media default).
- **D-019-04** test matrix held stable: Playwright `use.colorScheme: 'dark'` so no-cookie tests render dark (the shipped default when OS is dark); the light-axe tests set the `rtr_theme` cookie (explicit wins).

## 3. Acceptance criteria

| AC | Criterion |
|---|---|
| AC-01 | No colored `rgba()` literals left in `styles.css`; overlays render correctly in light + dark. |
| AC-02 | No-cookie visitor with a light OS sees the light UI (and dark OS → dark), with no flash and no hydration error. |
| AC-03 | Setting a theme writes the cookie and overrides the OS default; reload persists via cookie only (no storage). |
| AC-04 | Theme toggle icon reflects the actually-applied theme with no cookie. |
| AC-05 | No regression: vitest + full Playwright green (axe both themes × both locales); `next build` EXIT 0. |
| AC-06 | No backend/API/migration change. |

## 4. Gates

`tsc` 0 · `eslint` 0 · `vitest` green · `next build` EXIT 0 · axe both themes × both locales 0 crit/serious · full Playwright 100% (incl. a new prefers-color-scheme test).

## 5. DRY-RUN

WP-A token-ise overlays → WP-B theme.ts `readThemeCookie` + root/(shell) layout omit-when-unset + `suppressHydrationWarning` + themes.css media fallback + AppShell applied-theme read + playwright colorScheme → new e2e (colorScheme light/dark, no cookie) → run §4 → Completion + Verify.
