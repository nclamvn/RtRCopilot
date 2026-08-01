# TIP-011 · Builder B Completion Report — Shared Evidence Rail + Ask workspace

## STATUS

**DONE — all gates green.** Frontend plus the same-origin `/api/ask` proxy;
backend proven untouched (`git status -- v2/apps/backend` empty). Working
tree left uncommitted for Contractor checkpoint.

Slice delivered: ONE shared Evidence Rail module (`src/rail/`) with a typed
evidence contract and client-edge forged-zone gates (AC-02); full Ask
workspace replacing the placeholder at `/ask` — grounded answers with
citation markers wired to the rail and to TIP-008 deep locators (AC-03),
first-class honest-null with recorded gap id + state (AC-04), research scope
with typed-403 denial and server-labeled results, ACL-scoped file-scope
picker with typed denied states (AC-05), conversation reopen via the TIP-007
API with URL-restorable id, full vi/en i18n, keyboard operable end-to-end.

## FILES CHANGED

New:
- `v2/apps/web/src/rail/contracts.ts` — the D-011-02 evidence contract:
  `EvidenceEntry` (zone `sot|research|private` **server-provided only**,
  grounding, tier, source+revision, record/document version, evidence
  checksums, freshness/verification/corroboration, policy/redaction state,
  `rtr.locator.v1` locator union, snippet); adapters
  `evidenceFromAskCitation` (a citation smuggling ANY `zone_label` refuses to
  parse — the frozen TIP-007 model forbids extra fields, so zone stays null
  and no chip renders) and `evidenceFromResearchHit` /
  `parseResearchSearchEvidence` (hit, citation AND response must carry the
  exact `research` label; `zone_label:"sot"` on research-shaped evidence
  throws `zone_label_forged`); `parseObjectLocator` (bounded server-dict →
  locator union), `evidenceHref` (TIP-008 `/files?version=…&<locator>` deep
  link), `railEntryId`.
- `v2/apps/web/src/rail/ZoneChip.tsx` — trust-zone chip lifted **verbatim**
  from knowledge-ops (typed on the shared `EvidenceZone`).
- `v2/apps/web/src/rail/EvidenceRail.tsx` — the one rail component:
  `<aside id="evidence-rail" tabIndex={-1} data-shell-region>` (joins F6
  cycle), zone chip / marker / tier / DLP chips, dl facts with accessible
  text for every relationship, snippet, locator link with `locatorText()`
  accessible equivalent, `onActivateLocator` callback, house bottom-sheet
  `.open` pattern; exports `focusRailEntry`.
- `v2/apps/web/src/rail/contracts.test.ts` (15),
  `v2/apps/web/src/rail/EvidenceRail.test.tsx` (4) — incl. the required
  forged-zone regression both at contract and adapter level.
- `v2/apps/web/src/ask/contracts.ts` + `contracts.test.ts` (13) — typed
  `AskResponse`/`ConversationResponse`/catalog-page parsing (a non-grounded
  answer may not smuggle citations; forged citation zone rejects the whole
  answer), URL state (`?conversation=<uuid>` only, ids never content).
- `v2/apps/web/src/app/api/ask/[[...path]]/route.ts` + `route.test.ts` (16)
  — same-origin proxy mirroring the governance proxy EXACTLY; family
  allowlist is only what Ask consumes: `{"ask", "conversations"}`; typed
  400 `invalid_ask_path` / 503 `ask_service_unavailable`.
- `v2/apps/web/tests/browser/ask.spec.ts` — 11 Playwright tests (house
  route-mock conventions; screenshots `tip011-ask-mobile.png`,
  `tip011-ask-desktop-en.png`).

Modified:
- `v2/apps/web/src/app/(shell)/ask/page.tsx` — placeholder body replaced;
  `PageHeader` kept (one H1). Question input; scope radios (SOT default,
  research enabled only after probe success); file-scope picker over
  `/api/files`; grounded/honest-null/failed rendering; research section;
  conversation reopen + in-session history; typed
  empty/loading/denied/error states via `shared/surface` semantics; 401
  drops session.
- `v2/apps/web/src/app/(shell)/ask/page.test.tsx` — placeholder tests
  replaced by 6 workspace tests (single-H1-in-both-locales assertions
  preserved).
- `v2/apps/web/src/app/knowledge-ops/zone.tsx` — `ZoneChip` now a re-export
  shim from `src/rail/ZoneChip`; `GatedCrossing`/`crossingPhase` unchanged.
  **Zero behavior change; zero knowledge-ops test edits.**
- `v2/apps/web/src/shell/AppShell.tsx` — F6 handler: first-match
  `findIndex` → innermost-match reduce so a region nested inside `main`
  (the rail) cycles nav → surface → rail instead of trapping (see
  DEVIATIONS 1; Builder A's shell tests pass unchanged).
- `v2/apps/web/src/app/files/page.tsx` — `/files` redirect now preserves the
  query string, so rail deep links minted as `/files?version=…&page=…`
  survive Builder C's move of the workspace (A's redirect test still green).
- `v2/apps/web/src/i18n/messages.ts` — `ask.*` + `rail.*` namespaces added
  (vi source of truth, en twins; tsc-enforced parity); unused placeholder
  keys `ask.comingSoon`/`ask.note` removed from both locales.
- `v2/apps/web/src/app/styles.css` — append-only section
  `/* TIP-011 Builder B … */`; tokens untouched, var() reuse only; rail
  bottom-sheet at ≤1100px mirrors the ops/files house breakpoint.

## TEST RESULTS (before → after)

| Gate | Before | After |
|---|---|---|
| eslint | PASS | PASS |
| tsc --noEmit | PASS | PASS |
| vitest (`pnpm --filter @rtr/web test`) | 82 passed / 13 files | **134 passed / 17 files** (all pre-existing tests green; only the 2 ask *placeholder* tests were replaced by 6 workspace tests) |
| `next build` | PASS | PASS (adds ƒ `/api/ask/[[...path]]`) |
| Playwright (prod build, `next start`, `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`) | 35/35 | **46/46** (35 existing byte-identical + 11 new ask) |
| Backend | 210/71 untouched | untouched (no file changed under `apps/backend`) |

What the new browser tests prove (AC mapping):
- **AC-03**: grounded answer renders with citation markers; citation click
  (mouse AND keyboard-only) focuses `rail-entry-C1` with `aria-current`;
  the rail's "Mở đúng vị trí — Trang 4" link navigates same-tab to
  `/files?version=…&page=4` → files viewer opens the PDF with locator spine
  `P4` — the exact TIP-008 contract, end-to-end.
- **AC-04**: honest-null shows the server sentence, recorded gap id, gap
  state `open` (fetched best-effort via the governance proxy; unit test
  covers the denied-degradation "ngoài phạm vi xem của bạn"), a
  `/knowledge-ops?view=gaps&gap=<id>` curator link, and an empty rail (no
  fabricated evidence).
- **AC-05**: denied catalog renders the typed state
  (`policy_denied · req-…`) inside the picker; a picked file sends
  `filters.source_key=<logical_name>` on the ask request and clearing the
  scope removes it (request bodies asserted).
- **AC-02**: research results render exactly the server labels (RESEARCH
  chips, `Tier P`, corroboration, `research_supported` note) and the rail
  distinguishes "Sự thật SOT (grounded)" from "Do nghiên cứu hỗ trợ
  (research_supported)"; typed 403 disables the research scope with
  `curator_required · req-…`; forged-zone refusal is vitest-covered
  (research-shaped evidence with `zone_label:"sot"` never renders).
- Shell integration: F6 cycles nav → work surface → rail → nav (and
  Shift+F6 reverse); mobile 360×800 rail is a bottom sheet (toggle,
  Escape, citation auto-open) with zero horizontal overflow; EN locale runs
  the primary flow with no mixed-language chrome; conversation reopens from
  `/ask?conversation=<id>` with citations wired to the rail;
  `localStorage.length + sessionStorage.length === 0` asserted.

## ISSUES

1. **L2 escalation — file-scoped retrieval is missing backend work.**
   TIP-007 explicitly deferred it ("file-specific/private attachment
   retrieval belongs to later work", TIP-007 spec §CONTEXT) and the frozen
   `AskRequest` exposes exactly one scoping hook: `filters.source_key` (an
   SOT source key). The picker therefore sends the picked file's
   `logical_name` as that key. This is correct wherever SOT sources are
   registered under file logical names; elsewhere a file-scoped ask
   honestly returns honest-null (recording a gap). No wrong-file or
   denied evidence can ever surface — retrieval ACL/DLP are untouched —
   but a real file/version-id ask filter needs an additive TIP-007-plane
   endpoint change (out of my frozen scope; did NOT patch the backend).
2. **L2 note — no conversation LIST endpoint exists** (TIP-007 shipped only
   `GET /conversations/{id}`; verified in `rag/api.py`). "List + reopen as
   the APIs exist" is delivered as: in-memory session history (no browser
   storage) + URL-restorable reopen by id. A cross-session list needs an
   additive backend endpoint.
3. **Research probe semantics**: the research search API returns 200-empty
   (zero-leak filtering) for authenticated non-curators rather than 403;
   `curator_required` 403s come from the curator-gated operations. The UI
   implements the specified behavior — typed 403 ⇒ option disabled with
   denied state — and treats 2xx as authorized (searches then honestly
   return nothing for unauthorized scopes). Each authenticated page load
   issues one audited probe (`{"query":"rtr","limit":1}`); Contractor
   should confirm that audit noise is acceptable.
4. Ask citations carry **no** server zone label (frozen `Citation` model,
   `extra="forbid"`), so rail entries for SOT citations render "Không có
   nhãn vùng từ máy chủ" instead of a chip — the client never guesses. The
   SOT-fact vs research-supported distinction rides on the server grounding
   metadata (`state:"grounded"` / `grounding:"research_supported"`), which
   is server-provided and gated.

## DEVIATIONS

1. **AppShell F6 fix** (only shell edit): the region search now picks the
   innermost `[data-shell-region]` containing focus. With Builder A's two
   regions the behavior is identical (their tests pass unedited); with the
   rail nested in `main` it prevents an F6 trap. Asserted in
   `ask.spec.ts` F6 test.
2. **`/files` redirect preserves query** — required so the rail's TIP-008
   deep links remain stable before AND after Builder C moves the workspace;
   A's redirect test unchanged.
3. **Citation activation model**: clicking/entering a citation focuses its
   rail entry ("bật nắp" — evidence first); the entry's locator link
   performs the same-tab TIP-008 navigation, and `onActivateLocator` fires
   alongside it. The full keyboard path input → submit → citation → rail →
   viewer is proven in E2E. (Chosen over navigate-on-citation-click, which
   would make the rail unreachable on inspect.)
4. Placeholder catalog keys (`ask.comingSoon`, `ask.note`) deleted from
   both locales (unused after replacement; tsc + runtime parity guard keep
   the catalog consistent).
5. Zero new dependencies (runtime or dev). Backend untouched. Cookie-only
   persistence; no localStorage/sessionStorage anywhere (browser-asserted).
6. Research scope submits ask + research search in parallel and renders the
   research section strictly from the labeled response — retrieval/
   grounding semantics untouched (D-011-03).
7. Reopened conversations feed the rail from the most recent
   citation-bearing message (markers repeat per-message in the frozen
   contract; latest wins). Clicking a marker in an older message focuses
   the current entry for that marker.

## SUGGESTIONS

**Rail adoption contract for Builder C (files/documents/knowledge-ops):**
1. Import `EvidenceRail` from `src/rail/EvidenceRail` and render it as the
   page's right rail; props
   `{entries, activeKey?, onActivateLocator?, open?, onClose?, note?}`.
   The component owns the `<aside id="evidence-rail" data-shell-region>`
   (F6 already handled), heading and mobile close; the page owns the
   toggle button + scrim (copy the `.ask-rail-toggle`/`.ask-scrim` pattern;
   sheet breakpoint 1100px = the ops/files house breakpoint).
2. Build entries through the adapters, or write a new adapter per surface
   returning `EvidenceEntry`. Rules the contract enforces: `zone` only from
   a literal server `zone_label` (pass `null` otherwise — no chip),
   checksums hex64, locator via `parseObjectLocator`, deep links via
   `evidenceHref` (mints `/files?version=…&<locator>`; works today through
   the query-preserving redirect and keeps working after you move files to
   `(shell)/files` — then delete my redirect logic with the move).
   For a files-manifest entry: `recordVersionId=manifest.version_id`,
   `recordChecksum=source_sha256`, no zone. For documents private-context
   payloads: only pass `zone:"private"` if the API literally returns it.
3. `ZoneChip` now lives in `src/rail/ZoneChip`; `knowledge-ops/zone.tsx` is
   a re-export shim you can collapse during migration (`GatedCrossing`
   stays knowledge-ops-local).
4. Citation/row → rail focus: give rows `onClick={() => focusRailEntry(key)}`
   and set `activeKey`; ids come from `railEntryId(key)`.
5. i18n: the whole `rail.*` namespace exists in vi+en — reuse, don't fork.
   `locatorText(locator, t, locale)` is exported for accessible locator
   strings anywhere.

**For Builder D (axe/keyboard coverage of /ask):**
- Mock set required: `/api/auth/me`, POST `/api/governance/research/search`
  (the page probes it on every authenticated load), `/api/ask/ask`,
  `/api/ask/conversations/*`, `/api/files*` — copy `mockAsk()` from
  `tests/browser/ask.spec.ts`.
- Keyboard invariants already proven you can build on: skip link → `#main`
  → question input is 2 tabs; Enter submits; markers are buttons with
  aria-label prefix "Trích dẫn — mở bằng chứng…"; rail entries are
  `tabIndex={-1}` articles with `aria-current`; F6 three-region cycle.
- axe surface notes: all async states use `role="status"`/`role="alert"`;
  scope controls are radios in a `fieldset/legend`; the rail is a named
  `complementary`; one H1 via `PageHeader`. Bottom sheet at 360×800 has 0
  horizontal overflow (screenshot `tip011-ask-mobile.png`); EN desktop
  screenshot `tip011-ask-desktop-en.png`.
- Reduced motion: the rail sheet uses the house transform transition, which
  the global `prefers-reduced-motion` kill-rule in `styles.css` already
  neutralizes.
- Grounded/honest-null answers are corpus data (Vietnamese in fixtures) —
  do not count answer text as "mixed language" in the i18n sweep; chrome
  strings are fully catalogued.
- Suggested axe target list for `/ask`: default state, grounded state,
  honest-null state, picker open, rail sheet open at 360×800.
