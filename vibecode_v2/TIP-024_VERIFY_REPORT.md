# VERIFY REPORT — TIP-024 · Pilot Corpus & Provenance

**Date:** 2026-08-04

**Verifier:** Contractor — full local source, data and runtime reconciliation

**Disposition:** **VERIFIED · READY-with-deferred**

## Verdict

TIP-024 satisfies **AC 11/11**. Critical findings: **0**. New open P0/P1 code or
security defects: **0**. The sole blocked readiness gate is the explicitly
deferred human-owner assignment for 211 caveated records; AI did not invent
owners or promote provenance to make the score green.

## Acceptance evidence

| AC | Result | Independent evidence |
|---|---|---|
| AC-024.1 readiness truth | PASS | Live service reconciliation matches direct SQL; integration proves counts change from DB state and curator is denied; Web contract/browser render the gate panel |
| AC-024.2 provenance honesty | PASS | Live result remains exactly 8 strict, 211 caveated, 219 placeholder-owned; mutation count zero |
| AC-024.3 research evidence | PASS | Adapter rerun: 124 input claims, 124 verbatim spans, 110 current, 70 parser-valid records, stable fingerprint |
| AC-024.4 conflict preservation | PASS | Live/import tests: 16 corroborated, 24 disputed, 30 uncorroborated; unequal records keep null value and all claims |
| AC-024.5 research zone | PASS | Research package/source remain separate; masquerade regression and readiness zone finding both zero |
| AC-024.6 real templates | PASS | Four deterministic fingerprints, four approved internal versions, 11 locked bindings; strict factsheet bind succeeds |
| AC-024.7 caveat gate | PASS | Integration renders caveat + named owner in internal DOCX; official bind/render returns `fact_caveated` |
| AC-024.8 real files | PASS | 30/30 ready, five families, 83 renditions, 3,252 private chunks, mismatch 0; second activation 30/30 idempotent |
| AC-024.9 questions | PASS | 32 cases each have explicit status/reason; evaluator reports no measured/provider result without authenticated observation |
| AC-024.10 regression | PASS | Backend, Web, browser/axe, data integration, migration, image and vulnerability gates all green |
| AC-024.11 production boundary | PASS | Commands refuse production; reports say `local_dev_only`; no OIDC/secret/owner/go-live claim |

## Verification ledger

| Gate | Result |
|---|---|
| Ruff | PASS · all backend files |
| strict mypy | PASS · 112 source files |
| backend pytest | PASS · 422 passed, 116 skipped |
| containerized data integration | PASS · 58 passed |
| Web ESLint + TypeScript | PASS |
| Web Vitest | PASS · 165/165 |
| Next.js production build | PASS |
| Playwright + axe | PASS · 93/93, critical/serious accessibility findings 0 |
| Alembic gate | PASS · 11 revisions, one head `0011_ingestion_pub_deferred` |
| DB least privilege | PASS · seven forbidden runtime operations denied |
| image policy | PASS · digest pins, non-root app images, hardened containment |
| Trivy | PASS · 0 HIGH/CRITICAL in API image |
| local health | PASS · API/Web/worker/Postgres/Redis/MinIO/ClamAV all healthy |
| recent API/worker/Web error scan | PASS · no ERROR/Traceback/CRITICAL/FATAL |

Warnings are non-blocking dependency/tool warnings only: Starlette's TestClient
deprecation, SWIG module deprecations, Alembic path-separator notice and a
read-only pytest cache warning in the integration container.

## Adversarial and failure-driven probes

- Path traversal, symlink escape, duplicate manifest key, family omission,
  checksum drift and unknown owner fail closed before ingestion.
- ClamAV freshness was repaired by loading the available newer signature; no
  fake scanner or bypass flag was introduced.
- A physically drifted local DB reported 0010 while missing
  `upload_sessions.publication_deferred`; migration 0011 repaired it
  transactionally and the clean 0→head/downgrade/upgrade matrix passed.
- Real XLSX files exposed temporal JSON and sparse `EmptyCell` failures; the
  shared extractor fix is deterministic and regression-covered.
- Official/legal output refuses caveated facts before a render job is created.
- Internal use cannot hide the debt: rendered text contains the caveat code and
  owner identity.
- Research disagreement cannot be collapsed by stronger tier or source order.
- Global readiness counts old small fixtures but the representative gate only
  counts versions at least 1 KiB; the manifest batch itself is exactly 30 real
  artifacts.

## Runtime reconciliation at verification

```text
SOT       219 active/current · 8 strict · 211 caveated · 219 placeholder owner
FILES      30 representative ready · 5 families · checksum/lineage findings 0
TEMPLATES   4 approved internal · 11 locked bindings · official/legal approved 0
RESEARCH   70 records · 16 corroborated · 24 disputed · 30 uncorroborated
QUESTIONS  32 total · 32 explicit untestable · provider claim false
READINESS   8 met · 1 blocked (named human owners)
```

## Residuals and next gate

1. RtR must assign named accountable owners to the 211 caveated records and
   prioritize the 13 caveated high-risk facts; bulk caveat removal is forbidden.
2. The 32-case pilot must be observed under real authenticated roles. Current
   untestable results are honest scope, not missing error handling.
3. No video/audio source existed in the approved local batch; those two flows
   remain explicit honest-null cases.
4. Real OIDC, TLS hostname, production secret injection, pilot cohort and
   signed go/no-go belong to TIP-025.
5. Real semantic embedding/provider calibration remains the deferred phase of
   TIP-014 and must not be confused with TIP-024 corpus readiness.

There is no basis for a production-ready or company-wide-ready claim. The
correct product state is **local pilot corpus ready, production authority
deferred**.
