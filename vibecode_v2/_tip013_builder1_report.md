# _tip013_builder1_report — Final 34/34 REQ Matrix (Phase A, item 1 / AC-A1)

- **STATUS:** DONE. `vibecode_v2/TIP-013_REQ_MATRIX.md` written — 34 rows,
  header + method + summary + Phase-B list + confidence notes. Working tree left
  uncommitted per BUILDER HANDOFF.
- **AC mapped:** AC-A1 (matrix exists, 34 rows, each with status + code/test/gate
  evidence, no unsupported "implemented"). Ready for Contractor sample re-check.

## What I audited

- Read all 34 REQ definitions (`01_SCAN_RRI_REPORT.md` §5), the TIP served
  (`TIP-013_MIGRATION_FINAL_VERIFY.md`), Blueprint, Task Graph, and all twelve
  `TIP-0{01..12}_VERIFY_REPORT.md` to locate evidence.
- Confirmed each REQ in **actual source**, not reports: `auth/policy.py`,
  `auth/api.py`, `config.py`, `auth/oidc.py`, `api/main.py`, `rag/retrieval.py`,
  `rag/answering.py`, `rag/dlp.py`, `sot/service.py` (publish txn),
  `sot/kernel_guard.py`, `commands/mutation_probe.py`, `research/service.py`,
  `governance/dashboard.py`, `governance/queues.py`, `documents/service.py`,
  `documents/renderers.py`, `ingestion/service.py`, `ingestion/extractors.py`,
  `repositories/objects.py`, `storage/s3.py`, `web/shell/AppShell.tsx`,
  `web/.../ask/page.tsx`, `web/.../knowledge-ops/page.tsx`, `web/files/viewers.tsx`;
  migrations `0001`, `0003`, `0004`, `0006`, `0007`; `.github/workflows/verify.yml`.
- Re-ran three pure-unit gates live to confirm teeth: `test_policy.py` **51 passed**,
  `test_rag_unit.py`+`test_config.py` **23 passed** (74 total). Did NOT run heavy
  gates (compose/Trivy/data-integration/Playwright/load) — that is Contractor AC-A6.

## Counts

- **implemented 33 · partial 1 · deferred 0** (of 34).
- Backend test fns ~260; web unit ~83; browser specs ~57 (counts for orientation).

## Surprises / refuted claims

1. **Prior "~23 e2e / ~9 partial" is stale.** Current honest truth is **33/1/0**.
   TIP-011 (REQ-026/027) and TIP-012 (REQ-005/029/030/031) moved multiple rows from
   *foundation* to *implemented mechanism with a runnable gate*. The higher count is
   legitimate under the TIP-013 standard (synthetic-fixture mechanism = implemented);
   the real-data proof for those rows is Phase B, enumerated in the matrix.
2. **The one honest downgrade is REQ-020 (partial).** The per-conversation
   *attachment-as-private-context retrieval* (the blueprint's PRIVATE CONTEXT ZONE)
   is **not built** — the Ask "file scope" only ACL-filters already-published SOT by
   `source_key`. It ships in a safe, non-leaking honest-null form (TIP-011 AC-05) and
   inherits the TIP-007 private/attachment retrieval deferral. Disposition:
   fix-in-pilot (Phase B) or a later TIP.
3. **REQ-029 has a small, real gap:** load/k6 + SLO evaluation is NOT wired into
   `verify.yml` (it exists only as `scripts/` + a TIP-012 drill), and the workflow
   push-trigger is `tip-012`, not `main`/`tip-013`. Everything else in the REQ
   (unit/integration/E2E/a11y via Playwright/security via Trivy/migration gate) IS
   CI-wired. Disposition: fix-now (add a load/SLO smoke stage + branch) or accept.
4. **Minor notes, not defects:** REQ-007 DLP *blocks* chunks rather than *redacts*
   (`redacted=False`) — fine for current policy; REQ-026 hosts the 7 blueprint
   surfaces under Knowledge-Ops views rather than 7 nav items — a naming choice.

## Suggestions for the Contractor's sample re-check

- **Highest-value samples to independently re-verify** (most load-bearing / most
  likely to move a go/no-go): **REQ-020** (confirm the partial — grep for any
  attachment→answer path; expect none), **REQ-007** (leak-0 + input/context DLP
  ordering), **REQ-011** (mutation_probe denial + kernel fingerprint), **REQ-015**
  (publish `inject_failure` atomicity), **REQ-029** (read `verify.yml`; confirm
  load absent).
- **Re-run AC-A6 heavy gates** I did not: backend full suite, web vitest, Playwright
  73/73 (incl. a11y), compose build, Trivy, data-integration — the matrix leans on
  the committed TIP-012 numbers for those.
- **For REQ-019**, if a stronger proof is wanted, execute the OCR/Vosk/ClamAV
  containers (I confirmed code + sha-pinned model + TIP-005 gate, not live run).
- Treat the matrix's **"NO real-data proof yet (Phase B)"** list as the direct input
  to the go/no-go's AC-B1..B5 rows.
