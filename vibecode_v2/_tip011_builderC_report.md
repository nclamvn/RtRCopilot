# TIP-011 · Builder C Completion Report — Workspace integration + additive backend

## STATUS

**DONE — all gates green** (web lint/tsc/vitest/build + full Playwright;
backend ruff/mypy/pytest unit AND full live-infra integration). Working tree
left uncommitted for Contractor checkpoint (git-mv renames staged as renames,
new files intent-to-add for visibility).

Slice delivered:

- **Backend additive package** (no migration, retrieval/grounding untouched):
  literal `zone_label: "sot"` on gap, queue-entry, queue-page and review-task
  payloads AND on ask-answer citations (response model only — D-011-03
  intact); policy-filtered subject + active-record pickers with HMAC
  kind-bound cursors, zero existence leak and audited disclosure (AC-06);
  live conflict + owner-review dashboard tiles (AC-08); owner-only
  conversation LIST endpoint (HMAC cursor, DLP-safe metadata, stored
  first-question digest); content-free `GET /api/v1/research/scope`
  capability sharing the search's policy predicate.
- **Frontend integration** (AC-01/02/07): Files moved under the shell at
  `/files` (root `/` now redirects there, query-preserving; B's temporary
  `/files` redirect deleted; history URLs fixed; `activeArea` updated),
  Documents at `(shell)/documents`, Knowledge Ops at
  `(shell)/knowledge-ops`; all three standalone topbars and bespoke rail
  shells deleted; one `PageHeader` per page; internal drawers kept; all three
  rails render through the SHARED `EvidenceRail` with per-surface adapters;
  B's ZoneChip shim collapsed; gap/queue chips now render from their own
  payload `zone_label`s (no dashboard dependency); Ask history panel wired to
  the new conversation list; Ask research probe replaced by the scope
  capability; i18n minimum (PageHeader, nav-visible strings, primary
  actions) migrated for all three pages.

## FILES CHANGED

Backend (all additive):
- `v2/apps/backend/src/rtr_copilot/governance/models.py` — `SotZone` literal +
  `SOT_ZONE_LABEL`; `zone_label` on `Gap` and `ReviewTask` (server constants,
  never stored).
- `v2/apps/backend/src/rtr_copilot/governance/queues.py` — `zone_label` on
  `QueueEntry` and `QueuePage`.
- `v2/apps/backend/src/rtr_copilot/rag/models.py` — `zone_label: Literal["sot"]`
  on `Citation` (adds a response field only); `ConversationSummary` +
  `ConversationListPage`.
- `v2/apps/backend/src/rtr_copilot/governance/service.py` —
  `search_subjects` / `search_records` (bounded queries, ILIKE-escaped,
  scan-limited, per-record view+owner/curate filtering identical to the queue
  visibility rule, signed cursors kind-bound `picker:subjects|records`,
  audited disclosure `governance.picker.*` with count + query digest);
  `SubjectPickerItem/Page`, `RecordPickerItem/Page` (record item carries the
  SOT literal), `escape_like`, `validate_picker_query`, picker constants.
- `v2/apps/backend/src/rtr_copilot/governance/api.py` —
  `GET /api/v1/governance/pickers/subjects|records`; `STATUS_BY_CODE` extended
  with `picker_query_invalid: 400`.
- `v2/apps/backend/src/rtr_copilot/governance/dashboard.py` — `ConflictTile` +
  `OwnerReviewTile` (zone-labeled literals), computed live via Builder 2's
  queue computations under the caller's scope; wired into
  `GovernanceDashboard` + audit-export details.
- `v2/apps/backend/src/rtr_copilot/rag/api.py` — `GET /api/v1/conversations`:
  caller's own conversations, newest activity first (sorted by
  `COALESCE(MAX(messages.created_at), conversations.created_at)` because
  TIP-007 never bumps `conversations.updated_at` — live computation, no new
  storage), HMAC cursor kind `conversations`, `first_question_digest` = the
  first user message's already-stored `content_sha256`, audited
  `rag.conversation.list`.
- `v2/apps/backend/src/rtr_copilot/research/service.py` — the search-scope
  policy predicate factored into `_search_scope_decision` used by BOTH
  `source_searchable` and the new `search_scope_allowed` (evaluated on generic
  research-zone attributes; reads no rows → content-free, leak-free).
- `v2/apps/backend/src/rtr_copilot/research/api.py` —
  `GET /api/v1/research/scope` → `{allowed: bool}`.
- `v2/apps/backend/tests/test_tip011_unit.py` — 10 unit tests (zone literals
  incl. forged-value rejection at model level, picker validation/gating/cursor
  discipline before any data access, anonymous 401s, typed 400/403 shapes,
  scope predicate incl. disabled subject, conversation cursor tamper).
- `v2/apps/backend/tests/test_tip011_integration.py` — 4 live-infra tests in
  4a style: subject picker two-subject scoping + pagination + kind-bound
  cursor + audit; record picker zero-leak (stranger's response for an existing
  key is byte-identical to a nonexistent key's response) + title match + `%`
  wildcard literalness + audit; conflict/owner-review tiles exact for owner,
  all-zero for stranger, live reassignment reflected, queue payload zone
  labels; full SOT publish→index→grounded ask proving `zone_label: "sot"` on
  real citations (object and serialized JSON), then the conversation list over
  HTTP (ASGITransport): owner-only, newest-first, stored digest equality,
  cursor pagination, stranger sees nothing, audited.

Frontend:
- Moves (git renames): `src/app/page.tsx → src/app/(shell)/files/page.tsx`,
  `src/app/documents/* → src/app/(shell)/documents/*`,
  `src/app/knowledge-ops/* → src/app/(shell)/knowledge-ops/*`;
  `src/app/files/page.tsx` (B's redirect) deleted.
- New `src/app/page.tsx` — server redirect `/` → `/files`, query-preserving
  (old deep links keep opening the exact position).
- `src/app/(shell)/files/page.tsx` — shell adoption: topbar deleted, root
  `<main>` → `<div>`, ONE `PageHeader` ("Tệp"), `history.*State` URLs
  `/` → `/files`, gate = PageHeader + lede + status (sign-in lives in the
  shell topbar); catalog drawer kept; rail = shared `EvidenceRail` with one
  manifest-adapter entry + capabilities/warnings/download/copy as `note`.
- `src/files/evidence.ts` — manifest → `EvidenceEntry` adapter (version id,
  source checksum, live locator; `zone: null` — no server label, no chip).
- `src/app/(shell)/documents/page.tsx` — shell adoption; ONE `PageHeader`
  ("Tài liệu") with render-state + drawer toggles as actions; template ledger
  kept; rail = shared `EvidenceRail`: locked SOT facts as typed entries
  (record key/checksums/provenance/freshness exactly as bind returned them),
  approval timeline + actions + history as rail `footer`.
- `src/documents/evidence.ts` — locked-field → `EvidenceEntry` adapter.
- `src/app/(shell)/knowledge-ops/page.tsx` — shell adoption; ONE `PageHeader`
  ("Vận hành tri thức"); ledger kept (its `<h1>` removed); **chips from
  payload labels**: gap rows/detail ← `gap.zone_label`, queue rows ←
  `entry.zone_label`, queue rail ← `page.zone_label` (AC-07 — no dashboard
  dependency); conflict + owner-review ledger rows now read the new dashboard
  tiles (the two per-queue `limit=1` aggregate fetches removed); two new
  dashboard tiles rendered; rail = shared `EvidenceRail` (gap/research-record
  adapter entries + per-view facts as `note`).
- `src/app/(shell)/knowledge-ops/zone.tsx` — B's ZoneChip re-export shim
  collapsed; `GatedCrossing` stays local (it is not the rail).
- `src/governance/evidence.ts` — gap + research-record adapters.
- `src/governance/contracts.ts` — `sotZoneOptional` client-edge gate (literal
  `"sot"` parses; absent → null/no chip; anything else →
  `zone_label_forged`), applied to gap/queue-entry/queue-page/review-task;
  `Dashboard` type + parser extended with required `conflict` + `owner_review`
  tiles.
- `src/rail/contracts.ts` — `evidenceFromAskCitation` accepts the literal
  server `zone_label: "sot"` (renders the SOT chip); any other label still
  refuses; absent label (older shape) renders no chip.
- `src/rail/EvidenceRail.tsx` — additive `footer` prop (Documents approval
  timeline); the empty message shows only when there are no entries AND no
  note/footer (Ask behavior unchanged — its honest-null empty-rail assertions
  still pass).
- `src/ask/contracts.ts` — `parseConversationList` (id/timestamps/hex64
  digest) + `parseResearchScope`.
- `src/app/(shell)/ask/page.tsx` — research probe replaced by
  `GET /api/governance/research/scope` (`{allowed:false}` renders the option
  disabled with the denied note; removes the per-load audited search);
  history panel now server-backed via `GET /api/ask/conversations` (digest +
  last activity + reopen; refreshed after each ask; URL-restorable reopen
  kept; still zero browser storage).
- `src/shell/AppShell.tsx` — `activeArea` drops the `"/"` files rule (per A's
  handoff; `/` is a server redirect now).
- `src/i18n/messages.ts` — `files.*`, `documents.*`, `ops.*` namespaces +
  `rail.toggle` (vi source of truth, en twins, tsc-enforced parity);
  `ask.history.*` retitled ("Hội thoại của bạn") for the cross-session list.
- `src/app/styles.css` — append-only `/* TIP-011 Builder C */` section:
  `.files-layout`/`.doc-layout`/`.ops-layout` grids inside the shell, drawer
  toggle visibility classes, rail-as-column overrides ≥1101px, doc-note rail
  styles, files catalog search now visible at all widths. Tokens untouched,
  var() reuse only.
- `v2/README.md` — Files-at-`/files` note + new "Unified shell và additive
  API (TIP-011)" section documenting every new endpoint/field.
- Tests: unit tests for the three moved pages adjusted (documented below);
  `governance/contracts.test.ts`, `rail/contracts.test.ts`,
  `ask/contracts.test.ts`, `shell/AppShell.test.tsx` extended/adjusted;
  browser specs `shell|files|documents|knowledge-ops|ask.spec.ts` adjusted +
  extended (1 new ask history test, 2 new AC-07 payload-chip assertions).

## TEST RESULTS (before → after)

| Gate | Before | After |
|---|---|---|
| web eslint | PASS | PASS |
| web tsc --noEmit | PASS | PASS |
| web vitest (`pnpm --filter @rtr/web test`) | 134 passed / 17 files | **135 passed / 17 files** |
| web `next build` | PASS | PASS (routes now incl. ƒ `/files`, `/documents`, `/knowledge-ops` under the shell; `/` redirect) |
| Playwright (prod build, `next start`, `PLAYWRIGHT_BASE_URL=http://localhost:3000`, `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`) | 46/46 | **47/47** (46 existing preserved with the documented markup adjustments + 1 new server-history test) |
| backend ruff | PASS | PASS |
| backend mypy | PASS (83 files) | PASS (83 files) |
| backend pytest (unit, no infra) | 210 passed / 71 skipped | **220 passed / 75 skipped** (+10 unit; the 4 new integration tests skip without infra) |
| backend pytest (LIVE INFRA, full suite) | 278 passed / 3 skipped (TIP-010 final) | **292 passed / 3 skipped** (+10 unit +4 integration; zero regressions) |

Live-infra recipe used (fresh DB per handoff): started the local PG 16
cluster (`sudo pg_ctlcluster 16 main start`), `docker start repro-minio
repro-redis` (dockerd first), created fresh `rtr_v2_tip011c` owned by
`rtr_owner`, `alembic upgrade head` → `0009_governance_research`; env:
`INTEGRATION_DATABASE_DSN`/`POSTGRES_DSN` =
`postgresql://rtr_app:rtr_app_pw@localhost:5432/rtr_v2_tip011c`,
`MIGRATION_DSN` as `rtr_owner`, `REDIS_URL=redis://localhost:6380/0`,
`S3_ENDPOINT=http://127.0.0.1:9002` local/local-secret bucket `rtr-test`.

What the new/adjusted browser tests prove (AC mapping):
- **AC-01**: all three moved pages render inside the one shell (single H1 via
  `PageHeader`, sign-in affordance only in the shell topbar); `/` → `/files`
  redirect; nav active states unchanged (A's shell tests pass as-is except
  the two documented lines).
- **AC-02/07**: files/documents/knowledge-ops rails are the SAME
  `EvidenceRail` component (aria name "Bằng chứng & xuất xứ" everywhere);
  gap-row and queue-entry chips assert `.zone-chip.zone-sot` rendered from
  the payloads' own literals; ask citations now render the SOT chip from the
  server literal; research forged-`sot` regression unchanged and still
  blocking.
- **AC-08**: dashboard shows 5 SOT + 2 RESEARCH self-labeled tiles (counts
  asserted in vitest + Playwright).
- **AC-13**: every pre-existing flow (7 viewer families, deep locators,
  upload retry, revocation drills, gap triage→assign→answer, gated crossing,
  Ask grounded/honest-null/research/file-scope/keyboard/F6/mobile-sheet/EN)
  passes against the migrated pages.
- Backend integration proves AC-06 two-subject zero-leak for both pickers,
  AC-08 live scoped tiles, AC-07 citation zone label on a REAL grounded
  answer, and the owner-only conversation list end to end.

## ISSUES

1. None blocking. Note on `research/scope` semantics: under the current
   policy engine the caller-level predicate (view+search on research-zone
   attributes) allows every ACTIVE subject — exactly like the search endpoint
   itself, whose real filtering is per-source (owner/curator, zero-leak)
   inside the query. The capability deliberately does NOT consult source
   rows: consulting them would couple the boolean to existence (the leak the
   task forbids). `allowed:false` occurs for disabled subjects and any future
   policy tightening of the shared predicate.
2. Conversation "last activity" is computed live from `messages.created_at`
   (TIP-007 never updates `conversations.updated_at`); no schema change, and
   ordering/cursors are deterministic because messages are append-only.
3. Playwright infra note: the compose web container occupies :3000 in this
   container; I `docker stop rtr-copilot-v2-web-1` before `next start` for
   the browser gate (no code impact; Contractor's compose rerun rebuilds the
   image with this TIP's routes).

## DEVIATIONS

1. **Ask citation zone contract updated with the backend** (planned by the
   task): `evidenceFromAskCitation` now accepts exactly the literal server
   `zone_label: "sot"` (chip renders); any other label still throws
   `zone_label_forged`; an absent label renders without a chip. B's contract
   tests were updated accordingly (`rail/contracts.test.ts`,
   `ask/contracts.test.ts`) — the forged-zone regression is preserved with
   `research`/`private`/`"SOT"` as the forged values.
2. **EvidenceRail additive props**: `footer?: ReactNode` (Documents approval
   timeline renders after the entries) and the empty message now shows only
   when there are no entries AND no note/footer. Ask's usage and B's tests
   are unchanged and green.
3. **Legitimately adjusted markup assertions** (behavior assertions
   preserved in every case):
   - `(shell)/files/page.test.tsx`: gate heading "File Workspace" → "Tệp";
     sign-in-link assertion → gate-lede assertion (the link lives in the
     shell, which the unit test does not render). The behavioral core —
     anonymous never requests `/api/files`, exact call list — unchanged.
   - `(shell)/documents/page.test.tsx`: heading "Documents" → "Tài liệu";
     same link→lede swap; call-list assertions unchanged.
   - `(shell)/knowledge-ops/page.test.tsx`: link→lede swap + single-H1
     check; dashboard SOT chip count 3 → 5 (the two new tiles); rail aria
     name "Bằng chứng và xuất xứ" → shared "Bằng chứng & xuất xứ"; dashboard
     fixtures gained the two new tiles; obsolete per-queue `limit=1`
     aggregate mocks removed (page no longer issues those requests).
   - `shell/AppShell.test.tsx`: `activeArea("/")` → null (route is a server
     redirect now; per A's own handoff note).
   - `governance/contracts.test.ts`: dashboard fixture extended (parser now
     REQUIRES the two tiles — the live backend always sends them).
   - Browser: `shell.spec.ts` redirect test inverted (`/` → `/files`,
     heading "Tệp"); `files.spec.ts` rail aria name; revoked-rendition empty
     text → shared `rail.empty` string; revocation proof → page gate lede
     (the shell keeps its own session state — see 6); `documents.spec.ts`
     rail aria name; `knowledge-ops.spec.ts` fixtures (gap/queue payload
     `zone_label`s + dashboard tiles), SOT tile count 3 → 5, rail aria name;
     `ask.spec.ts` probe mock → scope + conversations-list mocks, citation
     fixture carries `zone_label:"sot"`, "no server zone label" assertion →
     SOT chip assertion, denied-scope test asserts `{allowed:false}`
     semantics (no error code — there is no error envelope in a 200).
4. **Ask history panel semantics** (per task item 4): B's in-memory session
   list replaced by the server list; the panel shows the stored
   first-question digest (code) + last-activity time + reopen — DLP-safe by
   construction (the endpoint never returns content). `ask.history.*`
   strings retitled in both locales ("Hội thoại của bạn"/"Your
   conversations").
5. **`/research/scope` writes no DB audit row**: the endpoint discloses
   nothing (content-free boolean; no row read), and the task's stated purpose
   is removing the per-page-load audit noise of B's probe. The policy
   engine's structured audit sink still applies to its decisions, and every
   other new endpoint IS DB-audited per house rule.
6. **Session-revocation UX under the shell**: when a workspace page loses its
   session (401), the page drops to its gate; the SHELL's identity chip
   refreshes on next navigation/reload (shell and page fetch `/api/auth/me`
   independently, as with `/ask` since Builder A/B). Recorded for D as a
   possible shell-level polish (shared identity context).
7. **Graduation/proposal-row chips** still take the research zone from the
   dashboard's `research_intake.zone_label` (payload data, never a guess):
   proposal payloads carry no `zone_label` and adding one is outside the
   bounded additive list. Gap/queue/review-task chips — the AC-07 set — are
   fully payload-local now.
8. Files desktop search: the old topbar `global-search` was deleted with the
   topbar; the catalog search (same label "Tìm tệp") is now visible at every
   width (it was mobile-only), so search capability is preserved.
9. Dashboard ledger simplification: conflict/owner-review ledger rows read
   the new tiles; two fewer authenticated requests per Knowledge Ops load.
10. Zero new dependencies (runtime or dev), zero schema changes, zero
    retrieval/grounding changes, no localStorage/sessionStorage anywhere,
    `make verify` scripts untouched, tokens frozen (appended CSS uses
    existing custom properties only).

## SUGGESTIONS — what remains for Builder D

**i18n leftovers (mechanical, per A's pattern; vi values must stay
byte-identical where unit/browser tests assert them):**
- Files: type-filter labels ("Tất cả/Ảnh/…"), viewer-empty texts ("Chọn một
  tệp để bắt đầu", "Safe rendition surface", …), "Đang mở bản xem…", viewer
  error strings, upload panel secondary strings ("Đích lưu", size hint,
  "Chưa có vị trí tải lên…", "Tải lên thất bại:"), scrim aria "Đóng bảng
  điều khiển", rail note dt "Checksum"/"Locator", and the whole TIP-008
  `src/files/viewers.tsx` module ("Bản xem PDF an toàn", "Tìm trong tệp",
  "Lưới bảng tính", pager strings, …).
- Documents: "Structured assembly", "Governed registry", registry aria
  "Template registry" / desk aria "Structured assembly desk", bind
  valid/invalid messages, all error strings, watermark aria, rail footer
  headings ("Phiên bản & trạng thái", "Lịch sử & so sánh"), "Sao chép",
  "Lý do", "Reviewer", "Tham số đổi/SOT đổi" lines.
- Knowledge Ops: `STATUS_TEXT` map, surface headings ("Bảng điều hành tri
  thức", queue titles, "Khoảng trống tri thức", "Gói nghiên cứu", "Cổng nâng
  cấp"), aria labels ("Bàn xử lý", "Danh sách khoảng trống", …), detail-fact
  labels, action-form labels/placeholders, notices ("Đã ghi nhận…"), rail
  note texts, gap-filter strings, `GatedCrossing` `PHASE_TEXT`, "Hủy".
- Locale dates: `when()` (knowledge-ops) and the two documents
  `toLocaleString("vi-VN")` calls should become `formatDateTime(x, locale)`.

**axe/keyboard surfaces for D:**
- New primary-page states to target: `/files` (gate, catalog, viewer per
  kind, rail sheet at 360×800), `/documents` (registry drawer, bind result,
  approval footer inside the rail sheet), `/knowledge-ops` (all six views +
  ledger drawer + rail sheet). F6 cycles nav → surface → rail on ALL four
  workspaces now (the rail is the shared aside with `data-shell-region`).
- Drawer toggles live in `PageHeader` actions: "Danh mục" (files, ≤720px),
  "Mẫu"/"Hàng đợi" (≤760px), "Bằng chứng"/"SOT / duyệt" (≤1100px) — good
  keyboard-E2E anchors.
- Browser-mock sets: files/documents/knowledge-ops mocks are unchanged in
  shape except knowledge-ops dashboards need the `conflict`/`owner_review`
  tiles and ask needs `/api/governance/research/scope` +
  `/api/ask/conversations` (copy from the updated specs).

**Markup quirks / debts:**
- The picker BACKEND (AC-06) is live and proxy-reachable at
  `/api/governance/pickers/subjects|records`, but the Knowledge Ops
  assign/answer forms still take raw UUID inputs — wiring typeahead pickers
  into those forms is the natural next step (kept out of my slice: the TIP
  assigns the pickers as backend work; flag for D or the Contractor).
- `.files-layout`/`.doc-layout` use `height:calc(100vh - 250px)` inside the
  scrolling `.shell-main` (viewer/desk need definite height); if D's
  viewport sweep finds clipping at unusual zoom levels, that calc is the
  knob.
- The Documents approval form now lives inside the rail (bottom sheet at
  ≤1100px) — verify focus order in the keyboard E2E for
  render→submit→approve.
- Shell/page dual `/api/auth/me` (deviation 6): consider a shared identity
  context in the shell so a page-level 401 also clears the topbar identity.
- Playwright port: stop `rtr-copilot-v2-web-1` (compose) before `next start`
  on :3000, or export another `PLAYWRIGHT_BASE_URL`.

**For the Contractor:**
- Backend picker cursors intentionally sort by `created_at` (+id) — the
  signed-cursor helper is datetime-bound; display-name ordering would need a
  new cursor shape (not needed for bounded typeahead pages).
- The record picker searches `record_key` ILIKE + `value_payload->>'title'`
  ILIKE (both escaped, substring); subject picker is prefix-only per spec.
- `GovernanceDashboard` gained two REQUIRED fields — any external consumer
  of `/api/v1/governance/dashboard` sees a strictly larger payload (the web
  parser now requires them; TIP-010 tests unaffected).
