# TIP-023 — Admin Workspace

> **Status:** CONTRACTOR VERIFIED · PR/CI PENDING
> **Date:** 04/08/2026
> **Method:** Vibecode Kit v6.1 — Homeowner intent → Contractor contract → Builder → Verify

## 1. Intent

Turn the already-governed backend administration APIs into one operator-safe
workspace. The workspace is a control plane for identities, research-source
registration, bounded governance settings, gap priority and worker health. It
is not a second path into company truth.

## 2. Design contract

- **Subject:** RtR internal governance control plane.
- **Audience:** administrators and curators operating a live knowledge system.
- **Primary job:** inspect operational risk, then make one bounded and audited
  change without using raw APIs.
- **Visual direction:** preserve the existing graphite/light Design DNA,
  Inter/mono typography and `--pc-*` tokens. Use a compact governance ledger,
  not a generic analytics dashboard.
- **Signature element:** an authority rail that keeps the system boundary
  visible: writes are audited; SOT, audit events and issued documents are
  read-only/out of scope.

## 3. In scope

1. Read job/worker health with explicit unavailable and recent-failure states.
2. List subjects and assign/unassign one approved role or group with a reason.
3. List, register and update research sources, including lifecycle,
   classification and owner.
4. List governance settings, update a registry-typed value with a reason and
   inspect immutable version history.
5. Override one visible knowledge-gap priority with a reason.
6. Link to read-only system status and expose typed error/request IDs.
7. Support Vietnamese/English, keyboard operation, mobile layout, both themes
   and reduced motion.

## 4. Explicit non-goals

- no direct SOT/research-record content mutation;
- no audit-event, issuance or document mutation;
- no arbitrary proxy relay or free-form backend paths;
- no bulk role/source/settings changes;
- no hidden retry or optimistic success when the worker/API is unavailable.

## 5. Acceptance criteria

- **AC-023.1 — Authorization matrix:** anonymous makes no admin API call;
  staff/curator without admin policy receives a persistent 403 state; admin can
  use all declared surfaces. A 401 after load revokes the workspace session.
- **AC-023.2 — Closed proxy:** only allowlisted governance families cross the
  Web edge; required `GET`, `POST`, `PUT` and `PATCH` methods work; truth
  families and malformed segments remain refused.
- **AC-023.3 — Audited writes:** every form requires a non-empty reason where
  the backend contract requires it and displays success or typed failure with
  request ID. Returned server state replaces the affected row.
- **AC-023.4 — No admin bypass:** UI sends only documented bounded payloads;
  the backend policy and immutable database boundaries remain authoritative.
- **AC-023.5 — Operational truth:** worker/job health comes from
  `/api/v1/admin/jobs/health`; unavailable, failures and last-computed time are
  explicit and never represented as healthy.
- **AC-023.6 — Contract safety:** unknown or malformed server payloads fail
  closed as `contract_violation`; no unsafe cast is the data boundary.
- **AC-023.7 — Accessibility:** all controls have labels, visible focus and
  keyboard operation; axe critical/serious = 0; mobile has no clipped actions.
- **AC-023.8 — Localization/theme:** every user-visible workspace string exists
  in Vietnamese and English; dark and light themes preserve readable contrast.
- **AC-023.9 — Verification:** Web lint/typecheck/unit/browser gates pass and
  CI aggregate is green before merge.

## 6. Delivery order

1. Specify contracts and proxy method boundary.
2. Build strict client parsers and unit tests.
3. Build authenticated ledger/work surface and bounded mutations.
4. Add the scoped responsive visual layer and complete i18n.
5. Verify auth/error/mutation states, browser keyboard/mobile/axe, then run the
   repository gates and issue a Contractor Verify report.
