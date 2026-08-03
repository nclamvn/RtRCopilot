# TIP-017 · Keyboard & Theming Completeness

**Depends:** TIP-015, TIP-016. **Branch:** `tip-013b`.
**Contractor** authored + runs the Verify slice; **Builder** same agent (Vibecode role cycle). **Homeowner:** no production/secret/kernel action; UI-only, no backend/API/migration change.

---

## 1. Objective

Make the keyboard-first design **discoverable** and tighten the a11y colour gate:
- **WP-A — Keyboard shortcuts help dialog (PRD §14 discoverability).** A `?` key (and a topbar affordance) opens an accessible dialog listing every shortcut the shell already ships (⌘K, ⌘N, ⌘1/2/3, F6/Shift+F6, `[`/`]`, Esc). Closes on Esc/backdrop; focus managed.
- **WP-B — EN light-axe.** Extend the TIP-016 light-theme axe pass to the EN locale so the colour gate covers **both themes × both locales** for all five pages.

## 2. Decisions (D-017-##)

- **D-017-01 — `?` is guarded.** The help hotkey fires only when focus is NOT in a text field (input/textarea/contenteditable), so typing `?` in the composer never opens it. A topbar `?` button gives a mouse/AT-discoverable path.
- **D-017-02 — Reuse the dialog pattern.** The help overlay reuses the command-palette's accessible modal shape (`role="dialog" aria-modal`, backdrop close, Esc, focus in / focus-return) — no new primitive, no new dependency.
- **D-017-03 — Shortcuts are data, copy is i18n.** Key chips (⌘K…) are literal; only the descriptions are translated (VI source + EN twin, parity kept).
- **D-017-04 — Gate widens, default unchanged.** The light-axe pass adds the EN locale; the shipped default theme stays dark (no `prefers-color-scheme` change — that would ripple through the whole test matrix and is out of scope here).

## 3. Acceptance criteria

| AC | Criterion |
|---|---|
| AC-01 | `?` (outside text fields) and the topbar button both open the help dialog; it lists all shell shortcuts. |
| AC-02 | Dialog is an accessible modal: `role=dialog`, labelled, Esc + backdrop close, focus moves in and returns to the opener. |
| AC-03 | `?` typed inside the composer does NOT open the dialog. |
| AC-04 | axe 0 critical/serious with the help dialog open; VI + EN. |
| AC-05 | Light-axe now covers EN too: 5 pages × 4 viewports × {vi,en} = 0 critical/serious; 0 overflow. |
| AC-06 | No regression: vitest + full Playwright green; `next build` EXIT 0; no backend/API/migration change. |

## 4. Gates with teeth

`tsc` 0 · `eslint` 0 · `vitest` green · `next build` EXIT 0 · axe (both themes × both locales) 0 crit/serious · full Playwright 100% (incl. new help-dialog test + EN light pages).

## 5. DRY-RUN

WP-A i18n → HelpDialog component + `?`/button wiring in AppShell + CSS → test. WP-B widen the light loop to LOCALES. Run §4, fix defects, write Completion + Verify.

## 6. Deferrals

- **rgba() overlay token-isation** — axe already passes with the translucent tints; token-ising them is pixel-polish, deferred to a later UI pass.
- `prefers-color-scheme` auto-default — deferred (test-matrix ripple; needs a pre-paint script).
