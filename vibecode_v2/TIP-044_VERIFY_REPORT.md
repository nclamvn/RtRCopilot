# TIP-044 — Verify Report

**Date:** 31/08/2026  
**Candidate:** `d81c1e5c3570`  
**Verdict:** `NOT READY`

## Evidence observed in the real browser

- Primary and pilot both reported all services ready; the tested candidate was
  `d81c1e5c3570` and the prior runtime check reported seven healthy containers.
- Browser development logs were empty on both active tabs after the campaign.
- Primary Files exposed 25 authorized internal files; isolated pilot exposed
  zero files and zero upload targets with explicit, honest empty states.
- PDF rendered 18 pages and advanced from page 1 to page 2; image, DOCX, PPTX
  (9 slides) and XLSX safe viewers rendered without console errors.
- Direct navigation with restricted version
  `f8c867de-2fcc-494f-831a-962da74784c7` did not expose restricted content and
  was normalized to the ordinary authorized catalog.
- An unknown knowledge-gap UUID returned typed `gap_not_found` with recovery
  affordance instead of a blank application state.
- At mobile width, Ask stayed within 390px with 44px controls. Knowledge Ops did
  not: its hidden ledger occupied 704px of vertical flow and pushed the surface
  to `y=831`.

## Why existing browser coverage did not catch the P1s

- `knowledge-ops.spec.ts` checks `toBeVisible()` and horizontal overflow at
  360×800, but it does not assert that the work surface intersects the initial
  viewport. Playwright considers an off-screen element visible when it is
  rendered and not hidden, so a heading below `y=800` satisfies that assertion.
- Governance browser fixtures authenticate only a curator for detail/action
  flows. There is no staff-role projection assertion requiring the mutation
  form to be absent.
- The CSS collision is deterministic: the early mobile rule makes
  `.ops-ledger` fixed, but the later and more specific
  `.ops-layout > .ops-ledger` rule restores `position: sticky`; the translated
  ledger is therefore visually hidden while still consuming grid height.

## Gate assessment

| Gate | Result | Reason |
|---|---|---|
| Authentication and fail-closed authorization | PASS | Protected data remained gated; restricted locator disclosed nothing |
| Core shell and ordinary Ask composition | PASS | Navigation, locale, theme, keyboard and composer guards worked |
| File safety and format coverage | PASS | Search/filter/view/provenance worked across available formats |
| Document invalid-input safety | PASS with UX debt | No invalid artifact issued; guidance/action state is weak |
| Governance least-privilege UX | FAIL | Curator mutation controls visible to staff |
| Responsive operational workspaces | FAIL | Knowledge Ops initially blank at 390×844 |
| Live grounded answer quality | PENDING | External-processing action-time approval not yet received |
| Runtime interruption recovery | NOT RUN | Would disturb shared candidate and needs a separate drill |

## Required remediation before GO

1. Gate mutation controls on the same capability used by the backend and add a
   browser regression proving staff cannot see or invoke them.
2. Remove the hidden mobile ledger from document flow (or render it as an
   overlay) and add a 390×844 Knowledge Ops regression with visible first paint.
3. Disable invalid document build or surface field-level requirements before
   submission.
4. Run the approved eight-case Ask sample sequentially, verify citations,
   false-grounded zero, prompt-injection refusal and composer/stream recovery.
5. Re-run the P1 cases on the exact rebuilt SHA before changing this verdict.
