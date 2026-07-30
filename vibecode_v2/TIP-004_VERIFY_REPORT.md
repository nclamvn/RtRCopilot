# TIP-004 · Independent Verify Report

- **Verifier result:** NOT READY
- **Coverage:** 10 PASS · 1 PARTIAL · 5 FAIL / 16 AC
- **Verified at:** 2026-07-30

## P1 blockers

1. Same-size S3 corruption can activate because HEAD validates length but not actual
   SHA-256 metadata/content.
2. Deleting the audit tail is not detected; the database chain has no trusted
   head/anchor outside the deletable event set.
3. Subject role/status authority mutations and audit are not committed in the same
   Unit of Work; the API sink is fire-and-forget in a separate transaction.
4. Object reconciliation deletes S3 before its database audit commit, so audit
   failure can leave an unaudited external deletion.
5. Backup `MAINTENANCE_MODE=true` is a shell assertion, not an enforced mutation
   pause across API, worker and database.
6. Restore uses `--no-privileges` without reapplying runtime grants; restored runtime
   repository smoke fails.
7. Restore target validation happens after database mutation for some invalid MinIO
   names, leaving a partially restored target.

## P2

Backup inventory records ETag but not SHA-256 object metadata.

## AC mapping

| AC | Result |
|---|---|
| 004.1 clean migration | PASS |
| 004.2 upgrade/downgrade | PARTIAL |
| 004.3 least privilege | PASS |
| 004.4 identity adapter | PASS |
| 004.5 schema invariants | PASS |
| 004.6 ACL projection | PASS — 48 scenarios |
| 004.7 object integrity | FAIL |
| 004.8 version concurrency | PASS |
| 004.9 failure/orphan | FAIL |
| 004.10 audit completeness/redaction | PASS |
| 004.11 append-only/tamper evidence | FAIL |
| 004.12 transactional audit | FAIL |
| 004.13 retention/legal hold | PASS |
| 004.14 restart persistence | PASS |
| 004.15 backup/restore | FAIL |
| 004.16 technical/boundary | PASS |

## Positive independent evidence

- Fresh migrations `0001→0004`, head and no-op passed.
- Runtime CRUD works while seven forbidden DDL/audit operations are denied.
- Twelve concurrent identity upserts produce one UUID and one row.
- Forty-eight PostgreSQL policy scenarios pass.
- Two version writers preserve sequential versions and a valid current pointer.
- Declared checksum mismatch, cross-zone separation and orphan reporting pass.
- Concurrent audit inserts and middle-row tamper detection pass.
- Full `make verify` passes 96 tests in their correct environments; dependency audit
  is clean; Docker builds pass.
- Restart database/object digests match.
- Happy-path isolated restore matches rows, one object and the current audit chain.
- Legacy boundary hash remains
  `8ed582a7194e70c447fc4fbe3e1fcf3192db48a7651fffb2ff3ac3a9ddc3bdbf`.

TIP-004 returns to Builder. TIP-005 remains DRAFT until every P1 is closed.

## Re-verification after first refinement

Independent QA closed every original finding except restore consistency:

- **15 AC PASS / 1 AC FAIL.**
- Object streamed SHA verification, audit anchor, transactional identity audit,
  durable reconciliation intent, enforced backup pause/release, manifest content
  SHA-256, restored grants/repository smoke, revision fixtures and failing-DDL
  rollback all passed.
- `make verify` passed 92 unit/API tests plus six real integration tests, four
  revision fixtures, 48 policy scenarios and nine runtime denial probes.

### Remaining P1 · AC-004.15

The target bucket changed from absent to non-empty after preflight. Restore correctly
detected the unexpected object, but left the restored database and a mixed bucket
behind. The restore workflow needs race-safe target ownership/reservation and
conditional compensating cleanup. It must never remove a database, bucket or object
that it cannot prove was created by the current restore operation.

## Final independent QA

**READY · 16/16 AC PASS.**

The remaining restore consistency finding is closed:

- A deterministic post-preflight target change causes restore to fail while leaving
  the target database absent, copying zero backup objects and preserving the unrelated
  marker.
- Ownership tests prove cleanup deletes only current-operation objects and refuses
  foreign or missing ownership.
- Forced cleanup failure returns exit 90 with an explicit recovery message.
- Happy restore finishes with matching database/bucket operation markers in `ready`
  state, 100% row/current-link and SHA-256 matches, valid audit chain, restored runtime
  grants and repository smoke.

Final regression: 94 unit/API tests plus 6/6 real PostgreSQL/MinIO integration tests,
four migration fixtures, one injected DDL rollback, 48 policy scenarios, nine runtime
denials, Ruff, strict mypy over 34 source files, web gates, dependency audit and Docker
builds all passed. No V2 source imports or mounts legacy/kernel/GOI/KnowledgeBase.
