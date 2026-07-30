# TIP-005 · Independent Verify Report

- **Verifier result:** NOT READY
- **Coverage:** 9 PASS · 9 NOT READY / 18 AC
- **Verified at:** 2026-07-30

## Blocking findings

1. **P1 · Manual retry HTTP 500.** Retry audit uses `upload_id` as
   `audit_events.resource_id`, but uploads are not resources, causing an FK failure.
2. **P1 · OCR is not executed.** Only schema and `ocr_unavailable` warning exist.
3. **P1 · Transcript is not executed.** Real media rendering passes, but no transcript
   JSON or WebVTT is generated.
4. **P1 · Required rendition matrix lacks end-to-end persistence proof.** Fourteen
   inputs and 31 outputs are proven at function level; only PNG is proven through
   persisted object, ready rendition and viewer manifest.
5. **P1 · Parent ACL inheritance is broken.** Ingestion leaves
   `documents.source_id` empty, allowing unrelated staff to read private upload status,
   viewer manifest and rendition content and ignoring source deny-download.
6. **P1 · Viewer/content authorization leaks through the same inheritance break.**
7. **P1 · Worker and tool sandbox have real Internet egress.** OS-level network
   isolation is absent and non-URL network syntax bypasses argument screening.
8. **P2 · Retry failure logs contain traceback, SQL and container paths; retry audit is
   missing because of the FK failure.**
9. **P2 · Required container vulnerability scan evidence is absent.**

## AC mapping

| AC | Result |
|---|---|
| 005.1 authorized streaming quarantine | PASS |
| 005.2 magic-byte allowlist | PASS |
| 005.3 archive/OOXML safety | PASS |
| 005.4 malware fail-closed | PASS |
| 005.5 immutable accepted version | PASS |
| 005.6 persistent idempotent delivery | PASS |
| 005.7 retry/terminal semantics | NOT READY · P1 |
| 005.8 extraction fidelity | PASS |
| 005.9 OCR provenance/quality | NOT READY · P1 |
| 005.10 transcript/media safety | NOT READY · P1 |
| 005.11 rendition matrix | NOT READY · P1 |
| 005.12 ACL inheritance/non-bypass | NOT READY · P1 |
| 005.13 viewer manifest contract | NOT READY · P1 |
| 005.14 provenance/quality completeness | PASS |
| 005.15 sanitized errors/audit | NOT READY · P2 |
| 005.16 sandbox/cleanup | NOT READY · P1 |
| 005.17 restart/reconciliation | PASS |
| 005.18 technical/boundary | NOT READY · P2 |

## Positive evidence

- Full verify passes 132 unit/API tests and nine Docker integration tests.
- Fourteen magic signatures and hostile structural fixtures pass expected outcomes.
- Real ClamAV clean/infected and fail-closed states pass.
- Accepted object/version integrity, concurrency/idempotency and lease reclaim pass.
- Deterministic PDF/DOCX/XLSX/PPTX extraction and 12 real FFmpeg outputs pass.
- Provenance completeness and restart byte/checksum persistence pass.
- Migrations, revision fixtures, DDL rollback, policy regressions, runtime grants,
  static/web gates, Docker builds and seven-service health pass.

TIP-005 returns to Builder. No downstream TIP may treat ingestion or viewer contracts
as READY until all P1 findings are closed and P2 evidence is resolved or explicitly
deferred by the Human.

## Re-verification after first refinement

Independent QA closed seven of the nine failed acceptance criteria. Current result:
**16/18 READY, 2/18 NOT READY**.

Remaining root cause:

- `private_context` lineage is now persisted, but the effective authorization
  projection still treats its `internal` classification as readable by any staff.
  Unrelated staff can receive upload status, viewer metadata and rendition bytes.
- Parent deny-download, direct rendition deny, admin non-bypass, request-time
  reauthorization and unknown-resource indistinguishability otherwise pass.

Required refinement: effective lineage must inherit source zone and owner. A
`private_context` resource is owner-only by default; a non-owner needs an active
explicit allow on the lineage, while any active explicit deny still wins. This can be
implemented in the existing resource/ACL projection without changing TIP-003's public
policy input contract.

All other findings are independently closed: manual retry, real private OCR, real
offline transcript, persisted 14-format/31-output matrix, seccomp network isolation,
redaction and pinned container scanning.

## Final independent QA

**READY · 18/18 AC PASS.**

The final `private_context` authorization finding is closed with live HTTP evidence:

- owner status, manifest and content are allowed;
- unrelated staff and admin receive the same typed 404 as an unknown resource with no
  business metadata;
- an active action-specific `view` allow enables preview/content but not original
  download;
- expired allow denies;
- active deny wins over allow, owner and admin; and
- content is re-authorized on every request and becomes unavailable immediately after
  a deny is added.

Final regression evidence:

- 133 unit/API tests passed; 16 integration-only tests were skipped in the unit phase;
- 16/16 PostgreSQL/MinIO integration tests passed;
- 14/14 input formats persisted end-to-end with 31/31 required rendition artifacts;
- five migration fixtures, one failing-DDL rollback, 48 policy scenarios and nine
  runtime database denial probes passed;
- Ruff, strict mypy over 47 files, web gates and Docker builds passed;
- digest-pinned Trivy found zero HIGH/CRITICAL findings in Debian and Python packages;
- seven long-running services are healthy.

No company data, SOT/evidence/index model, UI implementation or quarantine fixture was
introduced. **TIP-005 is READY.**
