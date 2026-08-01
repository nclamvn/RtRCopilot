# TIP-011 · Builder D Completion Report — i18n completion, pickers UI, axe + keyboard gates

## STATUS

**DONE — all gates green.** Frontend + Playwright/axe only; backend proven
untouched (`git status -- v2/apps/backend` empty; backend unit suite re-run:
220 passed / 75 skipped, byte-identical to baseline). Working tree left
uncommitted for Contractor checkpoint.

Slice delivered: full AC-09 i18n sweep (catalog 176 → **395 keys per locale**,
tsc + runtime parity; `toLocaleString("vi-VN")` fully replaced by
`formatDateTime`/`formatNumber`; no mixed-language screen in vi OR en),
typeahead **subject + record pickers** wired into the Knowledge Ops assign and
gap-answer forms (WAI-ARIA combobox over `/api/governance/governance/pickers/*`),
the **axe gate** (`tests/browser/a11y.spec.ts`: 5 pages × 4 viewports × 2
locales + 10 stateful surfaces — **zero violations at EVERY impact level**,
not just critical/serious), **keyboard-only critical flows**
(`tests/browser/keyboard.spec.ts`) incl. new shell **route-change focus
management**, and the reduced-motion + overflow sweep. All 47 pre-existing
browser tests preserved (2 specs adjusted for documented markup changes only).

## FILES CHANGED

New:
- `v2/apps/web/src/governance/Picker.tsx` — `PickerCombobox` (Task 4 picker
  UI): WAI-ARIA combobox/listbox (role=combobox input, `aria-expanded`,
  `aria-controls`, `aria-activedescendant`; ArrowUp/Down/Enter/Escape), 200 ms
  debounced bounded search (`limit=8`) against
  `/api/governance/governance/pickers/{subjects|records}`, typed
  loading/denied/error/empty states (`code · request_id` via the shared
  surface semantics), 401 → `onSessionLost`. Record options render the SOT
  chip from the **literal server `zone_label`**; a UUID-shaped query offers a
  "Dùng UUID này trực tiếp" raw-fallback option (kept for records only — a
  curator can carry a version id straight from the publish gate; judged
  valuable per the task's latitude).
- `v2/apps/web/src/governance/Picker.test.tsx` — 6 vitest tests: debounced
  bounded fetch + keyboard select, selected/clear affordance, typed
  denied/error/empty, 401 session drop, SOT chip + raw-UUID fallback, forged
  `zone_label` rejects the page as `contract_violation`.
- `v2/apps/web/tests/browser/a11y.spec.ts` — 21 tests (AC-10/12): axe matrix
  (5 primary pages × 4 viewports × 2 locales — 40 scans — each also asserting
  zero horizontal overflow and locale-correct H1/nav/surface anchors), 10
  stateful scans (grounded answer vi+en, honest-null, ask file picker open,
  ask/files/knowledge-ops rail sheets at 360×800, documents rendered +
  approval footer in the rail (desktop + 360 sheet), gap detail with subject
  picker open, ledger drawer, gated crossing, shell nav drawer), and the
  reduced-motion test (computed `transitionDuration === "0s"` for shell nav,
  ops ledger, evidence rail, template ledger, files catalog and crossing
  marker under `prefers-reduced-motion`, plus a whole-page zero-running-
  animations assertion and the crossing's text equivalent).
- `v2/apps/web/tests/browser/keyboard.spec.ts` — 5 tests (AC-11): file open →
  deep locator (pager to P2, URL `page=2`), documents template → bind →
  render → **submit → approve inside the rail** (proves "Lý do" → "Gửi duyệt"
  adjacency, i.e. rail focus order), ops triage → assign → answer **through
  the new pickers**, language switch (EN and back), route change → focus
  lands on `#main`. Visible focus (outline ≥ 3px) asserted at key stops;
  flows use ONLY Tab/Shift+Tab/Enter/Arrow keys/F6.
- `v2/apps/web/tests/browser/support/mocks.ts` — shared route-mock helpers
  for the two new specs (house conventions; per C's inventory: knowledge-ops
  dashboards carry the conflict + owner-review tiles, ask mocks carry
  `/api/governance/research/scope` + `/api/ask/conversations`, plus the new
  picker endpoints and a stateful documents approve path). Existing specs
  keep their own local mocks untouched.

Modified:
- `v2/apps/web/src/i18n/messages.ts` — 176 → 395 keys/locale: full `files.*`
  (viewer families, upload, filters, checksum/locator labels), `documents.*`
  (registry/desk arias, bind/errors, watermark, rail footer), `ops.*`
  (status/tiles/queues/gaps/research/graduation/crossing/notices/forms),
  `picker.*`, `shell.closePanels`, `ask.surfaceAria`, `ops.actionBlocked`.
  vi values byte-identical to the previous literals wherever any test or
  screen asserted them; en complete (tsc-enforced + runtime guard).
- `v2/apps/web/src/files/viewers.tsx` — whole TIP-008 module migrated to the
  catalog (PDF/image/sheet/media viewers, search panel, partial states);
  async errors are stored as **catalog keys** and translated at render, so a
  locale switch never leaves stale-language errors.
- `v2/apps/web/src/app/(shell)/files/page.tsx` — type filters, viewer
  empty/loading/errors (key-typed state), upload secondary strings, scrim
  aria, rail-note dt labels.
- `v2/apps/web/src/app/(shell)/documents/page.tsx` — assembly/registry arias
  + eyebrows, bind valid/invalid composition, all action errors (key-typed
  state), watermark, approval-footer strings, `formatDateTime` for both
  `toLocaleString("vi-VN")` calls, default reason via catalog.
- `v2/apps/web/src/app/(shell)/knowledge-ops/page.tsx` — complete i18n
  (STATUS map → `statusText()`, headings, arias, tiles, forms, notices as
  typed `MessageKey` state, badges, rail notes, `when(value, locale)`);
  **picker wiring**: gap assign/answer and queue assign now use
  `PickerCombobox` (`assigneePick`/`resolvingPick` selections replace the raw
  `assignee`/`resolvingVersion` strings; assign/answer buttons enable on
  selection); `tabIndex={0}` on the scrollable work surface (axe fix below).
- `v2/apps/web/src/app/(shell)/knowledge-ops/zone.tsx` — `GatedCrossing`
  PHASE_TEXT + gate label via catalog (`ops.crossing.*`).
- `v2/apps/web/src/app/(shell)/ask/page.tsx` — work-surface landmark renamed
  to `ask.surfaceAria` (axe `landmark-unique` fix; the grounded-answer region
  keeps "Câu trả lời").
- `v2/apps/web/src/governance/contracts.ts` — `parseSubjectPickerPage` /
  `parseRecordPickerPage` (+types): record rows REQUIRE the literal
  `zone_label:"sot"`; any other value throws `zone_label_forged`
  (client-edge gate, AC-02/06 style).
- `v2/apps/web/src/governance/contracts.test.ts` — +2 tests for the picker
  parsers incl. forged-label loop (`research`/`private`/`"SOT"`/absent).
- `v2/apps/web/src/shell/AppShell.tsx` — route-change focus management
  (AC-11): on pathname change focus moves to `#main` (holds the single H1);
  initial load untouched (skip link stays the first tab stop); query-only
  updates (locator params, knowledge-ops views) deliberately do NOT steal
  focus.
- `v2/apps/web/src/app/styles.css` — append-only `/* TIP-011 Builder D */`
  sections: picker styles (in-flow popup, active-option highlight) and the
  two axe-driven fixes documented in DEVIATIONS 4–5. Tokens untouched.
- `v2/apps/web/package.json` + `v2/pnpm-lock.yaml` — devDependency
  `@axe-core/playwright` **4.12.1** (exact pin; the ONLY new dependency,
  dev-only, per the TIP allowance).
- `v2/apps/web/tests/browser/knowledge-ops.spec.ts` — picker mocks added;
  triage→assign→answer flow and the freshness-queue test now drive the
  comboboxes (assign/answer buttons stay disabled until a pick — behavior
  assertions preserved and extended with the SOT-chip-in-option check).
- `v2/apps/web/tests/browser/documents.spec.ts` — registry drawer accessible
  name "Template registry" → "Sổ mẫu" (2 lines; the string was itself a
  C-flagged i18n leftover).
- `v2/README.md` — TIP-011 section extended with the Task 4 paragraph
  (pickers UI, axe/keyboard gates, run command).

## TEST RESULTS (before → after)

| Gate | Before (C's baseline) | After |
|---|---|---|
| web eslint | PASS | PASS |
| web tsc --noEmit | PASS | PASS |
| web vitest (`pnpm --filter @rtr/web test`) | 135 passed / 17 files | **143 passed / 18 files** (+6 Picker, +2 picker parsers; all 135 originals unchanged and green) |
| web `next build` | PASS | PASS (same route set) |
| Playwright (prod build, `next start`, `PLAYWRIGHT_BASE_URL=http://localhost:3000`, `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, `--workers=2`) | 47/47 | **73/73** (47 existing preserved + 21 a11y + 5 keyboard; full-suite single run 1.8 m) |
| i18n missing-key guard (vitest `i18n.test.ts`) | PASS | PASS (395 = 395 keys, all non-empty) |
| backend pytest (unit, no infra) | 220 passed / 75 skipped | **220 passed / 75 skipped** (re-run; zero backend file changed) |
| backend ruff/mypy | PASS | untouched (no file changed) |

**axe violation counts, found → fixed (per page, across the full matrix +
stateful states):**

| Page | Found | Fixed | Residual |
|---|---|---|---|
| /ask | 1 moderate (`landmark-unique` ×3 states: work-surface and answer regions shared the name "Câu trả lời") | landmark renamed `ask.surfaceAria` ("Bàn hỏi đáp"/"Ask desk") | **0 any impact** |
| /files | 1 serious (`color-contrast` ×2 nodes: rail-note copy buttons rendered on the browser default buttonface background) | restyled to house underline buttons — muted `#92999f` on panel `#15191c` = **6.1:1** | **0 any impact** |
| /documents | 1 serious (`color-contrast` ×1: `.draft-watermark` text) | own chip background (DEVIATIONS 5; ≥ **6.2:1** worst case) | **0 any impact** |
| /knowledge-ops | 1 serious (`scrollable-region-focusable` ×1: `.ops-surface`) | `tabIndex={0}` on the scrollable work surface | **0 any impact** |
| /admin | 0 | — | **0 any impact** |

Final verified state: **0 critical, 0 serious, 0 moderate, 0 minor** across
all 50+ scans (the moderate/minor reporting hook is wired as test annotations
and currently reports an empty list). Overflow sweep: 0 px horizontal
overflow at 360×800, 768×1024, 1440×900, 1920×1080 in both locales on all
five pages plus every open-drawer/sheet state.

What the new tests prove (AC mapping):
- **AC-09**: every matrix scan asserts `html[lang]`, the locale-correct H1,
  a nav label and one work-surface string per page (anchors in
  `a11y.spec.ts`); ask.spec's existing EN no-mixed-chrome test still green;
  vitest guards catalog parity at runtime, tsc at compile time; fixture/
  corpus text (answers, template display names, gap questions) is server
  data and exempt per B's handoff.
- **AC-10**: zero critical/serious (in fact zero at all impacts) on
  /ask · /files · /documents · /knowledge-ops · /admin at all four viewports
  in vi AND en, plus grounded/honest-null/picker/rail-sheet/drawer/watermark
  /crossing states.
- **AC-11**: keyboard-only E2E for all five critical flows (ask→citation→
  rail→viewer already in ask.spec — verified still green post-C in the same
  run); focus lands on `#main` after route change; visible focus outline
  ≥ 3px asserted along the way; F6 region cycle reused.
- **AC-12**: reduced-motion computed-style proofs for every animated element
  family (drawers: shell nav, ops ledger, template ledger, files catalog;
  sheets: evidence rail; gated-crossing marker) + zero running CSS
  animations page-wide + the crossing's text equivalent; overflow sweep as
  above.
- **AC-06 (consumer side)**: picker UI renders only disclosed rows; typed
  denied state shows `code · request_id`; forged `zone_label` on a record
  row rejects the entire page before anything renders (vitest + parser
  tests).
- **AC-13**: 47 pre-existing browser tests + 135 pre-existing vitest tests
  pass; backend suite untouched-green.

## ISSUES

1. **None blocking.** One infra trap worth recording for the Contractor: a
   stale `next start` (spawned ~12:35 by session tooling, serving Builder
   C's in-memory build manifest whose CSS chunk no longer existed on disk
   after my rebuild) was holding :3000 — my first browser run executed
   against a CSS-less app and "found" 21 failures incl. a 4 px overflow on
   /admin. After killing the stale server and serving the fresh build, that
   overflow and all phantom findings disappeared; the four findings listed
   in the table above were the only real ones. **Verify runs should
   `pkill -f next-server` (and stop `rtr-copilot-v2-web-1`) before
   `next start`.**
2. Subject picker search is prefix-only server-side (C's design note);
   record search is substring on key/title. The UI hint text stays neutral
   ("Nhập để tìm…"). Test data exercises prefix for subjects.
3. `metadata.description` in the root layout remains a static Vietnamese
   string (Next static metadata, not screen content; localizing it needs
   `generateMetadata` — left as polish, see SUGGESTIONS).

## DEVIATIONS

1. **devDependency `@axe-core/playwright` 4.12.1** (exact pin) — the one
   allowed dependency, recorded per spec.
2. **vi copy changes while completing AC-09** (English strings that had been
   shipping on Vietnamese screens are now Vietnamese; en keeps the English
   originals): "Safe rendition surface" → "Bề mặt bản xem an toàn";
   "Structured assembly (desk)" → "Bàn lắp ráp có cấu trúc"/"Lắp ráp có cấu
   trúc"; "Governed registry" → "Sổ đăng ký có kiểm soát"; "TIP-008 safe
   viewer" → "Trình xem an toàn TIP-008"; "Template registry" (aria) → "Sổ
   mẫu"; "Reviewer" fallback → "Người duyệt"; `files.preview` vi "Preview" →
   "Xem trước"; `ops.eyebrow` vi "Queue ledger" → "Sổ hàng đợi vận hành".
   "Document Operating System", "RT ROBOTICS / COPILOT", "Tier", "rev",
   "DLP", "RESEARCH/SOT" zone glyphs stay as product terms in both locales.
   Documents scrim aria "Đóng bảng" harmonized to the shared
   `shell.closePanels` ("Đóng bảng điều khiển").
3. **Assign/answer form markup replaced** (planned by the task): the three
   raw-UUID inputs ("Giao cho (subject ID)", "Bản ghi SOT đã kích hoạt
   (version ID)", queue "Giao cho (subject ID)") are now `PickerCombobox`
   instances labeled "Người phụ trách"/"Bản ghi SOT trả lời"; assign/answer
   buttons are disabled until a selection exists (previously enabled by any
   nonempty text). `knowledge-ops.spec.ts` flow + freshness tests updated
   accordingly — behavior assertions (state transitions, POST bodies via the
   stateful mock, disabled→enabled) preserved and strengthened.
4. **a11y-driven CSS (append-only, no token value touched):**
   `.evidence-rail .rail-note dd button` restyled from browser-default
   buttonface to the house underline button — contrast before ≈ **1.9:1**
   (light ink on Chrome's dark-scheme buttonface), after **6.1:1**
   (`#92999f` on `#15191c`).
5. **`.draft-watermark` override (a11y):** before — text
   `rgba(229,107,70,.55)` directly over arbitrary preview pixels ≈ **2.5:1**
   on the dark sheet stage and indeterminate over white PDF pages (axe
   serious); after — `#f5a184` on its own `rgba(13,15,17,.85)` chip =
   **6.2:1** over a worst-case white page and ≈ **9:1** over the dark stage
   (passes 4.5:1 normal-text, well past the 3:1 large-text requirement).
   Visual character (rotated, translucent, signal-orange border) kept.
6. **`.ops-surface` gains `tabIndex={0}`** — it is a scrollable region and
   must be keyboard-scrollable (axe serious). Adds one tab stop on
   /knowledge-ops; keyboard tests account for it.
7. **`/ask` work-surface landmark renamed** (`ask.surfaceAria`) so the
   grounded-answer region's "Câu trả lời" name is unique among landmarks.
8. **Route-change focus management added to AppShell** (task-authorized:
   "implement focus management in the shell if missing"): pathname change →
   `#main.focus()`. Deliberately pathname-only, so locator/view query
   updates via `history.*State` never steal focus. All 7 pre-existing shell
   browser tests pass unchanged.
9. **Async error states are stored as catalog keys** (files viewer +
   documents actions), translated at render — switching locale re-translates
   even already-displayed errors. Default audit reasons sent to the server
   ("Xử lý qua Knowledge Ops", …) now come from the catalog, so the audit
   text follows the UI locale (payload content, no test asserted them).
10. **Test-only adjustments** (all documented above): knowledge-ops.spec
    (pickers), documents.spec ("Sổ mẫu" ×2). Every other pre-existing
    spec/test byte-identical. New shared mocks live in
    `tests/browser/support/` (not matched as a spec).

## SUGGESTIONS — for the Contractor's final verify

1. **Kill stray web servers before the browser gate** (Issue 1): a stale
   `next start` on :3000 silently serves a dead build and produces phantom
   axe/overflow failures. `docker stop rtr-copilot-v2-web-1` +
   `pkill -f next-server`, then `pnpm --filter @rtr/web build && pnpm
   --filter @rtr/web start`.
2. Compose rerun rebuilds the web image with C's + D's changes; the compose
   web container was already stopped in this container.
3. Adversarial probes to keep: forged `zone_label` on picker records (vitest
   covers `research`/`private`/`"SOT"`/absent → `zone_label_forged`); the
   picker never issues a request before a non-empty query (unit-asserted) —
   worth confirming zero requests in the live leak probes too.
4. Live-infra picker check: the browser suite mocks the picker endpoints; the
   backend integration tests (C's `test_tip011_integration.py`) prove the
   zero-leak behavior server-side. A quick manual compose run of the gap
   assign flow end-to-end (real curator + real subject directory) would close
   the loop between the two.
5. Polish candidates (out of my slice): localize `metadata.description` via
   `generateMetadata`; shared identity context so a page-level 401 clears the
   topbar identity (C's deviation 6); proxy 503 envelope `message` fields are
   Vietnamese-only server strings (never rendered — UI shows only
   `code · request_id`), could be dropped or localized server-side later.
6. The moderate/minor axe reporting hook (`axe-moderate-minor` annotations in
   `a11y.spec.ts`) currently reports an empty list — if future changes
   reintroduce lesser findings they surface in the JSON report without
   failing the gate; tighten to fail-on-moderate if the Homeowner wants.
