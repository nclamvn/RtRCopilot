# TIP-011 · Builder A Completion Report — Unified application shell + i18n foundation

## STATUS

**DONE — all gates green.** Frontend only; backend proven untouched
(`git status -- v2/apps/backend` empty). Working tree left uncommitted for
Contractor checkpoint.

Slice delivered: unified AppShell (topbar, six-area nav, drawer, skip link,
landmarks, F6 region shortcut), `/ask` + `/admin` placeholder pages under the
shell, `/files` route contract, typed-error `Surface` extracted to a shared
module, typed vi/en i18n catalog with cookie persistence + locale formatters,
vitest + Playwright coverage.

## FILES CHANGED

New:
- `v2/apps/web/src/i18n/messages.ts` — typed catalog. `vi` literal object is
  the source of truth; `MessageKey = keyof typeof vi`; `en` is
  `Record<MessageKey, string>` so a missing/extra English key is a **compile
  error**. Also `Locale`, `LOCALES`, `DEFAULT_LOCALE ("vi")`,
  `LOCALE_COOKIE ("rtr_locale")`, `resolveLocale()`.
- `v2/apps/web/src/i18n/format.ts` — `formatNumber`, `formatDate`,
  `formatDateTime`, `intlLocale` (vi→`vi-VN`, en→`en-US`) for later Builders.
- `v2/apps/web/src/i18n/provider.tsx` — `I18nProvider` + `useI18n()`
  (`{locale, t, setLocale}`). `setLocale` re-renders in place (no reload),
  sets `document.documentElement.lang`, persists via cookie ONLY. Context
  default = vi catalog, so components render correctly without a provider
  (keeps existing page unit tests wrapper-free).
- `v2/apps/web/src/shared/surface.tsx` — **canonical typed-error surface**:
  `Surface`, `errorText`, `Load<T>`, `IDLE`, re-exports `TypedError` +
  `parseTypedError` from `governance/contracts`. Strings come from the
  catalog (identical vi output to 4b's originals).
- `v2/apps/web/src/shell/AppShell.tsx` — `AppShell`, `PageHeader`,
  `activeArea()`, `NAV_AREAS` (adoption API below).
- `v2/apps/web/src/app/(shell)/layout.tsx` — route group rendering AppShell
  (Suspense-wrapped for `useSearchParams`).
- `v2/apps/web/src/app/(shell)/ask/page.tsx` — placeholder "sắp có" surface
  (Builder B replaces the body only).
- `v2/apps/web/src/app/(shell)/admin/page.tsx` — placeholder listing the five
  existing `/api/v1/admin/*` surface areas (checked backend `admin_api.py`;
  no admin UI exists anywhere, so placeholder per TIP).
- `v2/apps/web/src/app/files/page.tsx` — server redirect `/files` → `/`
  (route contract stable for the nav; workspace moves under C).
- `v2/apps/web/src/i18n/i18n.test.ts`, `src/shell/AppShell.test.tsx`,
  `src/app/(shell)/ask/page.test.tsx`, `src/app/(shell)/admin/page.test.tsx`
  — 15 new vitest tests.
- `v2/apps/web/tests/browser/shell.spec.ts` — 7 Playwright tests (house
  route-mock conventions; screenshots `tip011-shell-desktop.png`,
  `tip011-shell-mobile.png`).

Modified:
- `v2/apps/web/src/app/layout.tsx` — async root layout: reads
  `rtr_locale` cookie, `<html lang={locale}>`, wraps children in
  `I18nProvider`; metadata title generalized to "RtR Copilot".
- `v2/apps/web/src/app/knowledge-ops/page.tsx` — imports `Surface`,
  `errorText`, `Load`, `IDLE` from `../../shared/surface`; local copies
  deleted. **No behavioral change; zero test edits needed.**
- `v2/apps/web/src/app/styles.css` — append-only shell section at EOF
  (`/* TIP-011 Builder A … */`); tokens untouched, only var() reuse.

## TEST RESULTS (before → after)

| Gate | Before | After |
|---|---|---|
| eslint | PASS | PASS |
| tsc --noEmit | PASS | PASS |
| vitest (`pnpm --filter @rtr/web test`) | 67 passed / 9 files | **82 passed / 13 files** (all 67 originals unchanged and green) |
| `next build` | PASS | PASS (all routes now ƒ dynamic — see DEVIATIONS 1) |
| Playwright | 28/28 | **35/35** (28 existing untouched + 7 new shell) |
| Backend | 210/71 untouched | untouched (no file changed under `apps/backend`) |

Playwright ran against the production build: `pnpm build` then `next start`,
`PLAYWRIGHT_BASE_URL=http://localhost:3000`,
`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` (avoids 4b's dev-origin 127.0.0.1
issue entirely).

What the new tests prove: brand + six nav areas with correct hrefs and
`aria-current="page"`; active state follows navigation; skip link is the
first tab stop and moves focus to `#main`; F6/Shift+F6 cycle nav ⇄ work
surface; mobile (360×800) drawer opens/Escape-closes/closes after navigating
with zero horizontal overflow; language switch flips strings + `lang` without
reload, persists across client navigation AND reload via cookie with
`localStorage.length + sessionStorage.length === 0`; vi/en runtime key
parity + non-empty values; locale-correct number/date formatting; `/files`
redirects to the files workspace; anonymous shell shows the company sign-in
affordance; placeholders render exactly one H1 in both locales.

## ISSUES

- None blocking. One test-authoring fix during the run: mobile-drawer locator
  needed `exact: true` ("Điều hướng" is a substring of "Đóng điều hướng").
- Interim (by design, documented): while the shell wraps only `/ask` and
  `/admin`, switching to EN affects the shared `Surface` strings on
  knowledge-ops (denied/error/retry) — the only place a user opting into EN
  can see mixed language until Builders C/D migrate page strings. Vi default
  is pixel-identical to before.

## DEVIATIONS

1. **Root layout is now dynamic** (`await cookies()`), so `next build` emits
   every route as ƒ server-rendered on demand (previously some prerendered).
   Required: the `lang` attribute must reflect the cookie locale on first
   paint without browser storage and without hydration mismatch. No gate or
   test is affected; app is served by `next start`/compose anyway.
2. Root metadata title "Files · RtR Copilot" → "RtR Copilot" (one product,
   per AC-01 spirit). No test asserted the old title.
3. **Knowledge-ops nav split decision (recorded per TIP):** two entries, both
   trivially URL-param based on the existing restorable `view` state —
   "Tri thức" → `/knowledge-ops?view=research`, "Vận hành" →
   `/knowledge-ops`. `activeArea()` maps `view=research|graduation` →
   knowledge, all other views → operations.
4. `/files` exists as a server `redirect("/")` only; the files workspace
   still renders at `/` (Builder C moves it — see SUGGESTIONS).
5. Shell coexistence strategy: the shell wraps ONLY the `(shell)` route
   group (`/ask`, `/admin`). files/documents/knowledge-ops keep their own
   topbars and `<main>`s untouched → no double-H1/landmark on any route.
6. Drawer breakpoint 760px, mirroring the knowledge-ops ledger house
   breakpoint ("under tablet width"; at 768×1024 the nav is a sidebar, same
   as the existing workspaces' left panels).
7. Zero new dependencies (runtime or dev) — i18n is a typed module +
   context, no library.
8. **Existing tests adjusted: NONE.** All 67 vitest + 28 Playwright tests
   pass byte-identical.
9. `page.tsx` edit for knowledge-ops was imports-only (task authorized
   making it consume the shared module; behavior assertions all still pass).

## SUGGESTIONS — adoption API for Builders B/C/D

**Shell adoption (Builder C):**
1. Move a workspace under the group: `src/app/(shell)/documents/page.tsx`
   etc. — URL unchanged (route groups don't affect paths).
2. Delete the page's own topbar `<header>` and its gate header; the shell
   provides topbar/identity/logout/search/language.
3. Replace the page's root `<main className="…">` with a `<div>` (or
   fragment) — **AppShell owns `<main id="main">`**; keep the page's
   internal grid classes on that div.
4. Replace the page's H1(s) with ONE `PageHeader {eyebrow?, title, actions?}`
   (from `src/shell/AppShell.tsx`) — the enforced single-H1 title row.
5. Files: move the workspace to `(shell)/files/page.tsx`, fix its hardcoded
   `history.*State(…, "/")` URLs to `/files`, replace my
   `src/app/files/page.tsx` redirect, and turn `/` into a redirect to
   `/files` (then drop `"/"` from `activeArea`'s files rule).
6. Keep workspace-internal drawers (catalog/ledger/rail) as-is; only the
   left NAV is the shell's.
7. Active state needs nothing from you — `activeArea(pathname, view)`
   already maps every route incl. knowledge-ops views; extend it there if
   sub-routes appear.

**Evidence Rail (Builder B):** render the rail inside your page as
`<aside tabIndex={-1} data-shell-region aria-label=…>` — F6 cycling picks it
up automatically (nav → work surface → rail). Replace the body of
`(shell)/ask/page.tsx`; keep `PageHeader`. Import `Surface`/`errorText`/
`Load`/`IDLE`/`parseTypedError`/`TypedError` from `src/shared/surface` (the
canonical home — do not re-copy). The topbar search affordance already
routes to `/ask`.

**i18n migration pattern (Builders C/D, mechanical):** for each hardcoded
Vietnamese literal: add a namespaced key to `vi` in `src/i18n/messages.ts`
(`files.*`, `documents.*`, `ops.*`), let tsc list the missing `en` twin,
replace the literal with `t("key")` via `useI18n()`. Dates/numbers:
`new Date(x).toLocaleString("vi-VN")` → `formatDateTime(x, locale)` (same
output under vi). The parity test guards the catalog at runtime; the types
guard it at compile time. Cookie only — never localStorage/sessionStorage.

**Other observations for the Contractor / later builders:**
- `Suspense` in `(shell)/layout.tsx` exists for `useSearchParams`; keep it
  when C migrates pages.
- On mobile, F6 into the nav auto-opens the drawer (documented behavior).
- The keyboard hint (F6/Shift+F6) is rendered visibly at the nav footer in
  both locales — Builder D's keyboard E2E can assert it.
- Admin placeholder lists real backend surfaces (`/api/v1/admin/research-
  sources|settings|gaps/{id}/priority|subjects|jobs/health`); the governance
  proxy already allowlists the `admin` family when a real admin UI lands.
