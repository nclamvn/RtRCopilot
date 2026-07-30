# TIP-004 · Builder Completion Report

- **Builder result:** DONE · 16/16 AC PASS after two refinement cycles
- **Scope:** `v2/`
- **Reported at:** 2026-07-30
- **Independent verification:** VERIFIED · READY

## Reported evidence

| Gate | Result |
|---|---:|
| Backend unique tests | 100 |
| Unit/API phase | 94 passed |
| PostgreSQL/MinIO integration | 6/6 |
| PostgreSQL policy parity | 48 scenarios |
| Alembic revisions | 4 |
| Public tables including Alembic | 16 |
| Indexes | 37 |
| Runtime forbidden operations | 9/9 denied |
| Ruff | PASS |
| Mypy strict | PASS — 34 source files |
| Vitest / Playwright | 1/1 · 3/3 |
| Dependency audit | 0 known vulnerabilities |
| Docker / Compose | PASS · healthy |

## Builder acceptance summary

- Fresh, idempotent and downgrade/upgrade migrations passed for revisions
  `0001` through `0004`.
- Migration and runtime credentials are separated; runtime DDL and direct audit
  mutation/insert are denied.
- PostgreSQL identity persistence preserves immutable `(issuer, sub)` UUIDs and
  current authority.
- Resource/ACL projection preserves policy semantics, expiry and fail-closed
  lifecycle behavior.
- Object upload streams server-side SHA-256 and size, uses UUID keys and verifies
  object HEAD before version activation.
- Concurrent version writers preserve sequential versions and the current pointer;
  activated versions are immutable.
- Interrupted workflows remain staged and reconcile read-only unless explicit,
  audited repair/delete is requested.
- Audit events are redacted, append-only and chained; controlled tamper is detected.
- Privileged state and audit commit or roll back in one Unit of Work.
- Retention/legal hold fail closed; no business retention duration is hard-coded.
- Restart preserved UUIDs, current version, object SHA and audit head.

## Builder backup/restore drill

- Archive size: 12,074 bytes.
- Backup duration / measured write-pause window: 1 second.
- Isolated restore duration: 4 seconds.
- Alembic head, row counts/current links, object size/SHA-256 and audit
  count/head/full chain: 100% match.
- Drill database and bucket were removed after verification.

## Declared deviation

Alembic uses synchronous `psycopg` for transactional multi-statement DDL. Application
runtime remains SQLAlchemy async with `asyncpg`. Retention duration, purge authority,
backup destination/encryption and production RPO/RTO remain configurable decisions.

This is Builder evidence only. `TIP-004_VERIFY_REPORT.md` controls final acceptance.

## Final restore refinement

After independent QA reproduced a post-preflight target race, restore gained:

- per-operation UUID ownership;
- atomic S3 reservation and database ownership markers;
- object-level restore-operation metadata;
- exact final key/checksum/ownership validation;
- compensating cleanup limited to resources provably owned by the current operation;
  and
- an explicit recovery-required/exit-90 path when cleanup cannot be proven complete.

The deterministic race now leaves no restored database or backup object and preserves
the unrelated object. Happy restore completes with matching ready markers, exact rows
and checksums, valid audit chain, restored grants and repository smoke.
