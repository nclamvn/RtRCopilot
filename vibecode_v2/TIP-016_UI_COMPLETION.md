# TIP-016 · UI Completion (bottom-dock nav · full light-mode · composer chips)

**Depends:** TIP-015 (Premium UI Rebuild). **Branch:** `tip-013b`.
**Contractor:** authored + will run the independent Verify slice. **Builder:** same agent, Vibecode role cycle.
**Homeowner:** no production/secret/kernel action; UI-only, no backend/API/migration change.

---

## 1. Objective

Close the three UI items carried out of TIP-015 so the product is complete to PRD:
- **WP-A — Mobile bottom-dock nav (PRD §13):** icon dock at <760px (resolves deferral D-015-07).
- **WP-B — Full light-mode (lift PRD §19 for theming only):** Files / Documents / Knowledge-Ops / Admin render correctly in **both** themes, so the theme toggle is coherent app-wide (no dark islands under a light shell).
- **WP-C — Composer scope chips (PRD §11):** surface the active Ask scope (SOT vs research, selected file) as premium chips at the composer.

**WP-B lifts only the *theming* freeze** — layout, logic, copy, and the API of those pages stay frozen; only colour tokens change.

## 2. Decisions (D-016-##)

- **D-016-01 — Legacy tokens become theme-aware by alias, not by rewrite.** A `styles/legacy-bridge.css` (imported **after** `styles.css`) redefines the frozen tokens as `--bg:var(--pc-bg-app)`, `--panel:var(--pc-surface)`, `--ink:var(--pc-text-primary)`, `--muted:var(--pc-text-secondary)`, `--line:var(--pc-border)`, `--focus:var(--pc-focus)`, `--signal:var(--pc-accent)`, `--locator:var(--pc-accent)`. One `:root` alias set suffices (the `--pc-*` values already switch per `data-theme`).
- **D-016-02 — Hardcoded hues migrate to semantic tokens.** The ~20 literal hexes in `styles.css` are replaced by `--pc-*` refs by meaning (teal→accent, orange-red→danger, green→success, greys→text/surface/border). Danger/warning **semantics are preserved**: `--signal` aliases to accent for brand/active use, and the true danger/warning selectors are pinned to `--pc-danger`/`--pc-warning` in the bridge.
- **D-016-03 — Dock is a distinct nav landmark.** The bottom dock is a second `<nav aria-label="Điều hướng nhanh">`, visible only <760px (CSS), icon links carrying the six area names. Unit tests scope link queries to the primary nav (`within(navigation)`) so shared names never collide; axe sees two **distinctly-labelled** landmarks.
- **D-016-04 — Composer chips are read-only reflections.** Chips render current scope state (SOT/research + file), each with the existing "clear/switch" affordance; no new state, no backend touch.
- **D-016-05 — Gate expands to both themes.** The axe matrix adds a **light-theme** pass for the four migrated pages; dark stays the shipped default.

## 3. Acceptance criteria

| AC | Criterion |
|---|---|
| AC-01 | Bottom dock appears only <760px, navigates all six areas, marks the active one, 0 overflow, axe clean; ≥760px it is absent from the a11y tree. |
| AC-02 | Files/Documents/Knowledge-Ops/Admin render correctly in **light and dark**; danger stays red, success green, research amber. |
| AC-03 | axe **0 critical/serious** for all five pages in **both** themes × 4 viewports × 2 locales. |
| AC-04 | Composer shows the active scope as chips; clearing/switching still works; axe clean. |
| AC-05 | No layout break, 0 horizontal overflow across the expanded matrix. |
| AC-06 | No regression: vitest + full Playwright green; `next build` EXIT 0. |
| AC-07 | No backend/API/migration change; single alembic head unchanged. |

## 4. Gates with teeth

`tsc` 0 · `eslint` 0 · `vitest` green · `next build` EXIT 0 · axe matrix **both themes** 0 crit/serious · full Playwright 100% (incl. new dock + light-theme runs). Un-runnable gates recorded, never green-by-assertion.

## 5. DRY-RUN

WP-C (chips, Ask-only, smallest) → WP-A (dock + scope test queries) → WP-B (bridge alias + hex migration + danger/warning pins) → expand axe to light theme → run §4 → fix gate-surfaced defects (record ratios) → Completion + Verify.

## 6. Risks

- **R1 WP-B contrast regressions** on frozen pages under light — mitigated by the expanded axe gate (the gate is the safety net; fix what it flags).
- **R2 dock role collisions** — mitigated by D-016-03 (scoped queries + distinct landmark label).
- **R3 overloaded `--signal`** — mitigated by D-016-02 danger/warning pins.

## 7. Deferrals

Files/Documents/Admin **layout/logic** redesign remains out of scope (only theming lifted). Attachment upload in Ask (not a PRD ask feature) not introduced.
