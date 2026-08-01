# TIP-011 · Unified UX

## HEADER

- **TIP-ID:** TIP-011
- **Project:** RtR Copilot V2
- **Module:** Unified application shell, shared Evidence Rail, Ask workspace,
  workspace integration, Vietnamese/English i18n, WCAG 2.2 AA accessibility
- **Depends on:** TIP-007, TIP-008, TIP-009, TIP-010 VERIFIED
- **Priority:** P0
- **Status:** ISSUED · awaiting Builders
- **Working directory:** `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2`
- **Requirements directly implemented/advanced:** REQ-026, REQ-027 (owned);
  advances REQ-008, REQ-018, REQ-020, REQ-034
- **Gate chính (Task Graph):** *Browser E2E + axe; keyboard-only critical
  flows. Người dùng cảm nhận đây là MỘT sản phẩm, không phải ba module ghép.*

## CONTEXT

TIP-007 delivered the grounded-answer backend (ACL-filtered hybrid retrieval,
DLP, deep citations, honest-null with gap routing) but explicitly deferred the
complete Ask UI. TIP-008 delivered Files with seven viewer families and deep
locators. TIP-009 delivered the Documents workspace. TIP-010 delivered the
Knowledge Ops workspace, trust-zone chips and a governance dashboard.

What exists today is therefore **three-plus workspaces with three topbars and
three evidence rails**, no Ask surface, no systematic i18n, and no axe gate.
Builder reports from TIP-010 (`_tip010_builder4a_report.md` §API SURFACE,
`_tip010_builder4b_report.md` §SUGGESTIONS) enumerate the exact debts this TIP
must clear: `zone_label` missing on gap/queue/review-task payloads (chips wait
on the dashboard response today); conflict and owner-review dashboard tiles
missing; assign/answer actions take raw UUIDs (no pickers); three topbars and
rails to unify; a `Surface` wrapper and typed-error helpers ready for reuse.

TIP-011 makes the product feel like ONE application. It does not harden
production (TIP-012) and does not touch real company data (TIP-013).

## DECISIONS LOG

| ID | Decision | Rationale |
|---|---|---|
| D-011-01 | Reuse the approved Blueprint §6 UI direction verbatim; no new Homeowner checkpoint | Nav shell (Ask · Files · Documents · Knowledge · Operations), work surface, Evidence Rail are already the contract |
| D-011-02 | ONE shared Evidence Rail component with a typed evidence contract (zone, source, version, locator, checksums, freshness, policy state) consumed by Ask, Files, Documents and Knowledge Ops | The rail is the product signature; four implementations would drift |
| D-011-03 | Ask UI consumes the TIP-007 answer API as-is; retrieval/grounding logic is frozen | UX TIP must not reopen verified retrieval semantics |
| D-011-04 | Backend changes are ADDITIVE contract work only: `zone_label` on gap/queue/review-task payloads, policy-filtered subject/record pickers, conflict + owner-review dashboard tiles. No schema migration | All zones are already derivable constants server-side; pickers read existing tables |
| D-011-05 | i18n is Vietnamese-default with complete English; strings externalized; language preference persists WITHOUT browser storage of restricted data (cookie/profile only) | REQ-027; artifact rule forbids localStorage |
| D-011-06 | axe (0 critical/serious) and keyboard-only E2E become required gates in the browser suite | The Task Graph gate is executable, not aspirational |
| D-011-07 | No visual redesign: TIP-008/009/010 tokens (graphite, steel, RtR signal orange, locator cyan) are frozen; this TIP unifies structure, not style | Design DNA is an asset; churn is regression risk |
| D-011-08 | Tests use synthetic fixtures; live corpora remain read-only | Same rule as D-009-09/D-010-09 |

## DESIGN DIRECTION

Blueprint §6, made literal:

```text
┌──────────────┬──────────────────────────────────────┬──────────────────┐
│ RT ROBOTICS  │ Work surface                         │ Evidence Rail    │
│              │                                      │ (shared)         │
│ Hỏi (Ask)    │ chat · file · document · governance  │ zone chip        │
│ Tệp (Files)  │                                      │ source/version   │
│ Tài liệu     │                                      │ locator·checksum │
│ Tri thức     │                                      │ freshness·policy │
│ Vận hành     │                                      │ (bottom sheet    │
│ Quản trị     │                                      │  at mobile)      │
└──────────────┴──────────────────────────────────────┴──────────────────┘
```

**Signature:** the Evidence Rail follows the user everywhere. Every material
number or statement can "bật nắp" — pop open to show source, version,
effectiveness and permission. Trust states use restrained signal color, never
decoration. The left nav collapses to a drawer under tablet width; the rail
becomes a bottom sheet. Plain Vietnamese verbs throughout; English via i18n.

## TASK

### 1. Unified application shell (Builder A)

- One persistent shell: single topbar (product mark, global search affordance
  placeholder, identity/session, language switch), left nav with the six
  areas, consistent page scaffold (one H1, landmarks, skip-to-content link);
- route consolidation under the shell: `/ask`, `/files`, `/documents`,
  `/knowledge-ops`, `/admin` (+ existing sub-routes unchanged); the legacy
  standalone topbars are removed by Builder C, not duplicated;
- shared typed-error surface (reuse 4b's helpers): every workspace renders
  `error.code` + `request_id` identically; 401 drops session, 403 renders
  denied state;
- i18n foundation: string catalog (vi default, en complete for shell), locale
  dates/numbers, `lang` attribute, cookie-persisted preference, no
  localStorage/sessionStorage;
- keyboard: skip links, focus outline tokens, nav operable by keyboard,
  shortcut to jump between nav / work surface / rail.

### 2. Shared Evidence Rail + Ask workspace (Builder B)

**Evidence Rail extraction:**

- one component + typed contract: zone (`sot|research|private`), source,
  record/document version, locator (page/sheet/cell/slide/timecode), evidence
  checksums, freshness/effectiveness, policy state; zone labels are
  server-provided, never client-inferred (4b's client-edge gate pattern);
- locator activation opens the TIP-008 viewer at the exact position (reuse
  existing deep-link contracts); accessible text equivalent for every stitch.

**Ask workspace (`/ask`):**

- question input with explicit scope control: company SOT (default) and, when
  authorized, an explicit research scope — results labeled per zone exactly as
  the backend returns them;
- optional file scope: pick an accessible file (picker over the existing
  Files catalog API) to ask within it — attachment/private context stays in
  the private zone (REQ-020);
- grounded answer rendering: statements with citation markers wired to the
  shared rail; each citation opens the exact locator; grounding metadata
  distinguishes SOT facts from research-supported statements visibly;
- honest-null state: clear "chưa có bằng chứng" treatment showing the gap that
  was recorded (id + state), linking to Knowledge Ops for authorized curators;
- conversation history via existing `conversations`/`messages` tables and
  APIs (list, reopen; no new retention semantics); DLP/policy refusals render
  as typed states;
- empty/loading/denied/error/expired states; URL-restorable conversation
  without restricted metadata in browser storage.

### 3. Workspace integration + additive backend (Builder C)

**Integration:** Files, Documents and Knowledge Ops adopt the shell and the
shared Evidence Rail; per-page topbars and bespoke rails are removed; no
functional regression (their suites keep passing, browser flows included);
Knowledge Ops trust-zone chip and gated-crossing render through the shared
rail/chip primitives.

**Additive backend (bounded, no migration):**

- `zone_label` on gap, queue-entry, queue-page and review-task payloads
  (server constants, typed as literals like 4a's dashboard);
- policy-filtered pickers: subject search (display name → subject id, for
  queue assign) and active-record search (record key → version, for gap
  answer); 404-before-403 discipline, HMAC cursors, no existence leak, audited
  disclosure per house rule;
- dashboard: add the missing conflict and owner-review tiles (live-computed,
  policy-scoped, zone-labeled — 4a conventions);
- extend `STATUS_BY_CODE` for new codes; unit + integration tests mirroring
  the 4a patterns (two-subject scoping, zero-leak, live computation).

### 4. Accessibility, i18n completion and E2E gates (Builder D)

- axe integration in the Playwright suite (`@axe-core/playwright`, dev-only
  dependency — record in DEVIATIONS): every primary page (`/ask`, `/files`,
  `/documents`, `/knowledge-ops`, `/admin` landing) at 360×800, 768×1024,
  1440×900, 1920×1080 with **zero critical/serious violations**;
- keyboard-only E2E for the critical flows: ask → citation → viewer at
  locator; file open → deep locator; document template → render → approve
  path; ops triage → assign → answer; language switch;
- reduced-motion compliance for every animated element (gated crossing,
  drawers, sheets);
- i18n completion sweep: no mixed-language screen in either locale; date/
  number locale checks; vitest coverage for the catalog (missing-key guard);
- visual/overflow regression at the four viewports; focus management on
  route change (focus lands on H1/main).

### 5. Tests, documentation and gates (all Builders, D consolidates)

- vitest units for shell, rail contract, Ask states, i18n guard;
- Playwright: existing 28 specs stay green (adjusted only where shell
  structure legitimately changes markup — behavior assertions preserved),
  plus new Ask/e2e/axe/keyboard specs;
- backend: full suite stays green; new picker/zone/tile tests follow 4a
  integration patterns;
- README/API docs updated (Ask UI, pickers, tiles, i18n);
- `make verify` preserved; leak and masquerade probes remain zero.

## ACCEPTANCE CRITERIA

### AC-01 · One shell, one identity of product
All five areas render inside a single shell with one topbar and one nav; no
page ships its own topbar; typed-error and denied states are visually and
semantically identical across areas.

### AC-02 · Evidence Rail is one component
Ask, Files, Documents and Knowledge Ops consume the same rail component and
contract; zone labels are server-provided; a research item can never render
without its chip (client-edge gate test).

### AC-03 · Ask answers are grounded and inspectable
An authorized user asks a question and receives an answer whose every cited
statement opens the exact source locator in the in-app viewer; grounding
distinguishes SOT facts from research-supported statements.

### AC-04 · Honest-null is a first-class state
When evidence is insufficient, the UI states it plainly and shows the recorded
gap (id + state); no fabricated content appears; curators can navigate to the
gap.

### AC-05 · File-scoped ask respects the file's ACL
Asking within a chosen file works only for files the caller can view; DLP and
policy refusals render as typed states; private attachments never surface
outside their owner's scope.

### AC-06 · Pickers leak nothing
Subject and record pickers return only policy-visible entries under
adversarial two-subject probes; denied existence is invisible through results,
counts, cursors and timing.

### AC-07 · Zone labels ship in governance payloads
Gap, queue, review-task responses carry literal-typed `zone_label`; Knowledge
Ops chips render from payload data with no dashboard dependency.

### AC-08 · Dashboard tiles are complete
Conflict and owner-review tiles compute live under the caller's policy scope
with the same leak-safety proofs as existing tiles.

### AC-09 · Vietnamese/English are both complete
Every primary screen renders fully in vi and in en; switching persists without
restricted browser storage; no mixed-language screen; locale-correct dates and
numbers.

### AC-10 · axe gate passes
Zero critical/serious axe violations on every primary page at all four
viewports, in both locales.

### AC-11 · Keyboard-only critical flows pass
Ask→citation→viewer, file deep-open, document render→approve, ops
triage→assign→answer and language switch each complete keyboard-only in E2E,
with visible focus and correct focus management on navigation.

### AC-12 · Reduced motion and responsive integrity
All animation respects reduced-motion; no overflow/clipping at 360×800,
768×1024, 1440×900, 1920×1080 in either locale.

### AC-13 · No regression across TIP-001…010
Backend full suite, web unit suite and prior browser flows remain green; leak
and masquerade probes remain zero.

### AC-14 · Full verification passes
`make verify`, backend/web/browser/axe suites and deterministic gates all pass
with zero P0/P1.

## OUT OF SCOPE

- HTTPS ingress, quotas, observability, CI/CD, load/DR (TIP-012).
- Real company SOT/templates/corpora activation (TIP-013).
- Streaming answers, voice input, model/provider changes, retrieval tuning.
- Collaborative editing, notifications delivery, mobile-native apps.
- New policy primitives or any non-additive backend change.
- Global search implementation (topbar affordance may land as placeholder
  routing to Ask; real cross-entity search is future work).

## BUILDER HANDOFF

Builders A→B→C→D work sequentially on branch `tip-011`, each must:

1. implement only inside `v2` plus TIP completion evidence;
2. keep kernel/KnowledgeBase/GOI/refinery corpora and `phase1_pilot` read-only;
3. write `vibecode_v2/_tip011_builder{A,B,C,D}_report.md` mapping their slice's
   ACs to code, tests, commands, counts and deviations;
4. keep every existing gate green before declaring done (unit phases minimum;
   full/browser where infra allows);
5. leave the working tree uncommitted for Contractor checkpoint.

Contractor will independently rerun all gates (including compose, axe and
keyboard E2E), execute adversarial leak probes, then write
`TIP-011_VERIFY_REPORT.md`. P0/P1 failure returns the TIP to BUILD.
