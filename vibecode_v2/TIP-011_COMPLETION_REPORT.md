# COMPLETION REPORT — TIP-011 · Unified UX

**STATUS:** DONE — four builder slices (A shell/i18n, B rail/Ask, C integration/additive-backend, D a11y/i18n-completion/pickers) completed sequentially on branch `tip-011`, consolidated by the Contractor. Individual reports: `vibecode_v2/_tip011_builder{A,B,C,D}_report.md`.

## What was built

- **One shell:** single topbar + six-area nav (Hỏi, Tệp, Tài liệu, Tri thức, Vận hành, Quản trị), drawer at mobile, skip link, F6 region cycling, route-change focus management. Files moved to `/files` (root redirects), Documents and Knowledge Ops under the shell; all standalone topbars deleted.
- **One Evidence Rail:** shared `src/rail/` module — typed evidence contract (zone server-provided only, forged-zone client gates), locator union with TIP-008 deep links, zone chips, mobile bottom sheet — adopted by Ask, Files, Documents and Knowledge Ops via per-surface adapters.
- **Ask workspace** over the frozen TIP-007 API: grounded answers with citations that open the exact page/sheet/cell/slide/timecode; SOT-vs-research grounding distinguished; honest-null shows the recorded gap id/state; research scope gated by a content-free capability endpoint; server-backed conversation history, URL-restorable.
- **Additive backend (no migration, retrieval logic untouched):** `zone_label` literals on gap/queue/review-task payloads and ask citations; policy-filtered subject + active-record pickers (HMAC cursors, zero existence leak, audited); conflict + owner-review dashboard tiles; owner-only conversation LIST; `GET /research/scope`.
- **i18n:** typed catalog 395 keys × vi/en, compile-time + runtime parity, cookie-persisted locale, locale-correct dates/numbers, no mixed-language screens.
- **Accessibility as gates:** axe (`@axe-core/playwright` 4.12.1, dev-only) — 5 pages × 4 viewports × 2 locales + 10 stateful surfaces = **0 violations at every impact level**; keyboard-only E2E for ask→citation→viewer, file deep-open, document bind→render→approve, ops triage→assign→answer (via new WAI-ARIA pickers), language switch; reduced-motion verified; 0px overflow across the matrix. Four real a11y defects found and fixed (landmark uniqueness, two contrast fixes with ratios recorded, scrollable-region focus).

## Gates (final tree)

| Gate | Result |
|---|---|
| web eslint / tsc | PASS / PASS |
| web vitest | **143 passed / 18 files** (from 67) |
| next build | PASS |
| Playwright (production `next start`) | **73/73** (from 28): 47 flows + 21 a11y + 5 keyboard |
| backend ruff / mypy | PASS / 83 files clean |
| backend pytest unit | **220 passed / 75 skipped** (from 210/71) |
| backend pytest FULL (live Postgres+MinIO+Redis) | **292 passed / 3 skipped** (from 278/3) |
| masquerade/leak/boundary/forged probes | **10/10 PASS** |
| compose build (api, worker, web, migrate) | EXIT=0 |
| Trivy (api image) | Clean — 0 HIGH/CRITICAL |
| data-integration containerized | **DATA INTEGRATION PASS** (tests=45, denials=18) |

## Issues / escalations resolved by Contractor decision

- **File-version-scoped ask retrieval** (Builder B L2): TIP-007 explicitly deferred attachment/private retrieval; B shipped the safe form (SOT `source_key` filter — wrong-file or denied evidence can never surface; misses → honest-null). Real per-file retrieval remains **deferred to a future TIP** — recorded in the Verify Report, not silently absorbed.
- **Conversation list + citation zone label + scope capability** (B's gaps): folded into Builder C's additive package and delivered.
- Graduation/proposal payload zone labels still ride the dashboard label (C deviation 7) — cosmetic, TIP-012/13 polish candidate.

## Deviations of note (full lists in builder reports)

Root layout is now dynamic (locale cookie); `/` redirects to `/files`; F6 innermost-region fix; `EvidenceRail` footer prop; vi copy completions (English artifacts translated); axe-driven CSS fixes are append-only with contrast ratios recorded; only new dependency is dev-only `@axe-core/playwright` 4.12.1.
