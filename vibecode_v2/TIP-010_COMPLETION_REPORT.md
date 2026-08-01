# COMPLETION REPORT — TIP-010 · Governance & Research

**STATUS:** DONE (build scope) — five builder slices completed on branch `tip-010`,
consolidated by the Contractor. Container-image gates deferred to the local
environment (see ISSUES).

**Build environment:** Anthropic cloud sandbox — Python 3.12 (uv), Node 22/pnpm,
native PostgreSQL 16 @ migration 0009, MinIO, Redis provisioned in-container.
Builders: five sequential agents (schema → gaps/queues → research/graduation →
admin/dashboard → web workspace), each with an individual report in
`vibecode_v2/_tip010_builder{1,2,3,4a,4b}_report.md`.

## FILES CHANGED

Created (backend, `v2/apps/backend`):
- `migrations/versions/0009_governance_research.py` — 8 governance/research
  tables, CHECKs, immutability triggers, least-privilege grants, full downgrade.
- `src/rtr_copilot/governance/{__init__,models,service,queues,admin,admin_api,api,dashboard}.py`
  — gap lifecycle, live-computed queues, settings, admin surfaces with AC-11
  boundary tarpit, live policy-scoped dashboard.
- `src/rtr_copilot/research/{__init__,package,models,service,candidate,api}.py`
  — Refinery package contract (fail-closed), immutable zone-labeled research
  registry, research-only lexical search, graduation gate staging through the
  TIP-006 publish pipeline with full lineage.
- `src/rtr_copilot/repositories/governance.py` — governance repository (typed
  `GovernanceError`, fingerprint idempotency, append-only invariants).
- Tests: `test_governance_unit/integration`, `test_governance_service_unit/integration`,
  `test_research_unit/integration` (+ `research_fixtures`),
  `test_governance_admin_unit/integration`.

Created (web, `v2/apps/web`):
- `src/app/knowledge-ops/{page,zone}.tsx` — three-pane “Vận hành tri thức”
  workspace; trust-zone chips; gated-crossing graduation; Vietnamese action verbs.
- `src/app/api/governance/[[...path]]/route.ts` — same-origin proxy with strict
  family allowlist.
- `src/governance/contracts.ts` — typed contracts incl. client-edge
  `zone_label_forged` gate.
- Tests: `contracts.test.ts` (13), `page.test.tsx` (7), proxy `route.test.ts` (13),
  `tests/browser/knowledge-ops.spec.ts` (11 Playwright).

Modified:
- `rag/answering.py` (honest-null → governed gap), `sot/service.py`
  (`answered → published` flip inside activation transaction),
  `api/main.py` (router registrations), `config.py` + `.env.example`
  (revision pin 0009, research staging root), backup/restore/verify scripts
  (0009 manifest coverage), `test_data_integration.py` (revision pins),
  one cursor-walk robustness fix in Builder 2's queue test (4a·D5),
  web `page.tsx` (nav link) + `styles.css` (appended tokens-only block).

Untouched: migrations 0001–0008, all TIP-001…009 module behavior, auth policy
model, legacy pilot, kernel/KnowledgeBase.

## TEST RESULTS

| Gate | Before TIP-010 | After TIP-010 |
|---|---|---|
| ruff | PASS | PASS |
| mypy --strict | 68 files, 0 issues | **83 files, 0 issues** (0 new ignores) |
| pytest unit phase (no infra) | 175 passed / 38 skipped | **210 passed / 71 skipped** |
| pytest FULL (live Postgres+MinIO+Redis) | 242 baseline | **278 passed / 3 skipped — run 3× (2 builder + 1 independent Contractor rerun ×2), identical** |
| eslint / tsc | PASS | PASS |
| vitest | 34 passed / 6 files | **67 passed / 9 files** |
| next build | PASS | PASS (`/knowledge-ops` + governance proxy present) |
| Playwright (route-mocked, chromium) | 17 | **28/28 passed** |
| Masquerade probe suite | n/a | **PASS — 0 hits** (6 adversarial probes) |
| AC-11 boundary probes | n/a | **PASS** (typed 403 + audit on every truth family) |

Remaining 3 pytest skips are environmental fixtures (private media runtime,
eSpeak, kernel checkout) — identical to the TIP-009 baseline.

## ACCEPTANCE CRITERIA (Builder self-assessment)

AC-01…AC-12, AC-14 tested and passing; AC-13 passing in mocked-browser scope
(4-viewport overflow/focus/keyboard, drawer/sheet behavior); AC-15 passing at
schema/manifest/grants level; AC-16 passing in native-equivalent scope. The
Contractor Verify Report holds the authoritative per-AC verdict.

## ISSUES DISCOVERED

- **MEDIUM (environmental):** `make verify`'s container stage cannot complete in
  the cloud sandbox — the worker/api image build downloads the Vosk model with
  strict TLS + checksum verification, which correctly fails against the
  sandbox's TLS-intercepting egress proxy. Compose image build, Trivy scan,
  containerized data-integration and live-stack browser E2E are therefore
  **deferred to the local machine** (they ran there for TIP-001…009).
- LOW: dashboard coverage/gap scans bounded at 1000 rows (house precedent) —
  revisit in TIP-012/013 at real scale.
- LOW: OIDC re-sync overwrites admin role/group bindings at next login
  (inherent to TIP-003's IdP-authoritative model) — documented in 4a·D2.
- LOW: crashed-approval edge (decision committed, staging failed) leaves an
  approved proposal without submission; audited; recovery is re-proposal.

## DEVIATIONS FROM SPEC (all L1, per-builder logs in individual reports)

Headline items: Pydantic+SQL house convention instead of literal “SQLAlchemy
models” wording (1·D1); `gaps` extends the existing 0007 table rather than
duplicating it (1·D2); research search is lexical-only — keeping research out
of the vector index is part of the separation proof (3); graduation lineage via
`publish_package_id` FK settable once (1·D5); no byte-upload endpoint — staging-
name import mirroring the SOT adapter (3·D2); admin bindings limited to the
operations TIP-003's engine already supports internally (4a·D2).

## SUGGESTIONS FOR CHỦ THẦU

- TIP-011 should: add `zone_label` to gap/queue payloads so chips never wait on
  the dashboard; conflict/owner-review dashboard tiles; subject/record pickers
  (assign/answer currently take raw UUIDs); unify the three topbars/rails.
- TIP-012 should revisit dashboard scan bounds with SQL-side policy filtering,
  and consider durable admin authority via `entitlements`.
- TIP-013 must exercise the Refinery adapter against the real 587-record corpus
  read-only before any import batch.
