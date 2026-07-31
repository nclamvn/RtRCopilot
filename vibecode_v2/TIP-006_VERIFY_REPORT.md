# TIP-006 · Independent Verify Report

**Date:** 31/07/2026  
**Verifier:** Contractor · Vibecode Kit v6.1  
**Overall status:** READY — implementation verified; live company kernel remains
blocked from activation by design.

## REQUIREMENT COVERAGE

- TIP-scoped REQ-IDs addressed: **8/8 (100%)**.
- Fully implemented in this TIP: **2/8** — REQ-011, REQ-015.
- Foundation advanced for later end-to-end completion: **6/8** — REQ-008,
  REQ-016, REQ-022, REQ-023, REQ-025, REQ-033.
- Missing from the approved TIP-006 scope: **0/8**.
- Retrieval/RAG, citation UX, templates, research graduation and bulk migration
  remain assigned to TIP-007, TIP-009, TIP-010 and TIP-013.

## SCENARIO RESULTS

Acceptance criteria: **16/16 PASS (100%)**.

| AC | Result | Independent evidence |
|---|---|---|
| AC-01 Schema | PASS | Migration `0006` upgrade, downgrade and head checks |
| AC-02 Package safety | PASS | Rooted deterministic parser; hostile member/checksum tests |
| AC-03 Provenance | PASS | Complete semantic/security hash and bounded findings |
| AC-04 Trust zone | PASS | Typed/allowlisted states; non-SOT/unsupported states rejected |
| AC-05 Attestation | PASS | HMAC binding, expiry, identity, policy and future-time guard |
| AC-06 Authorization | PASS | Anonymous/staff mutation denial; curator/admin policy gate |
| AC-07 Atomicity | PASS | Failure injection preserves prior pointer and hides candidates |
| AC-08 Concurrency/idempotency | PASS | Concurrent publish yields one activation/outbox/audit |
| AC-09 Version integrity | PASS | Collision, rollback and unresolved overlap rejection |
| AC-10 Policy read | PASS | Active-only reads plus per-record policy; hidden records return 404 |
| AC-11 Freshness | PASS | Injected-clock current/stale/expired/unknown |
| AC-12 Outbox | PASS | Exactly one correlated durable reindex request |
| AC-13 Audit | PASS | Stage/validate/publish/read-deny correlation and sanitization |
| AC-14 Kernel guard | PASS | Live kernel blocked; 508-file before/after fingerprint identical |
| AC-15 Recovery | PASS | SOT tables, active pointers, links, checksums and grants verified |
| AC-16 Health | PASS | Full independent gate listed below |

## INDEPENDENT REFINE FINDINGS

Initial BUILD was not accepted immediately. VERIFY found:

1. **P0 security projection:** a stricter replacement revision could retain the
   prior record/resource classification.
2. **P0 integrity:** canonical hashes and database triggers did not initially bind
   every semantic/security field.
3. **P1 state validation:** unsupported fact/verification strings could pass a
   deny-list validator.
4. **P2 attestation time:** a future validation timestamp was not rejected.
5. **P1 deployment drift:** the worker/local environment still expected schema
   `0005`, making the rebuilt API report `database_schema_outdated` after migration.

REFINE corrected all four findings:

- replacement revisions now atomically synchronize classification, department,
  project and ACL projection while owner/source identity remains fail-closed;
- record/evidence hashes bind all semantic/security fields and version rows retain
  the security snapshot;
- PostgreSQL permits only explicit lifecycle transitions, rejects direct content
  tamper and denies DELETE on all seven canonical SOT tables;
- fact and verification states are typed/allowlisted;
- attestations more than five minutes in the future are rejected.
- API and worker now share the `0006` schema/SOT environment contract; the ignored
  local environment was migrated and the three application containers recreated.

Regression coverage includes public-to-restricted replacement, stale-policy
attribute denial, ACL replacement, direct value/evidence tamper and DELETE denial.

## TECHNICAL HEALTH

Independent `make verify` result: **PASS**.

- Web lint/typecheck/Vitest/production build: PASS; **1/1** test.
- Ruff: PASS.
- Strict mypy: PASS on **54 source files**.
- Backend unit/API regression: **153 passed, 21 integration/environment skipped**.
- PostgreSQL data integration: **20 passed**.
- Migration revisions/fixtures: **6/6**.
- Policy scenarios retained: **48**.
- Runtime database denials: **12**.
- Supported formats retained: **14**; required rendition outputs: **31**.
- Container vulnerability scan: **0 detected OS/Python vulnerabilities**.
- Git diff check: PASS.
- Local deployment smoke: API, worker and web healthy; API/web readiness **200**;
  PostgreSQL revision `0006_sot_publish_provenance`.

Warnings are limited to existing Starlette/httpx, SWIG and read-only pytest cache
deprecations; none is a TIP-006 P0/P1/P2 failure.

## LIVE KERNEL RESULT

The live kernel is **not activated**. The read-only guard returns `blocked` because
the publish token/fingerprint/provenance boundary is not currently eligible.
No file under `/Users/os/RtR/kernel`, KnowledgeBase registry or GOI export was
modified or legitimized.

This is the required fail-closed result, not a failed TIP. Business-data repair,
curator approval and production package signing remain separate controlled work.

## OVERALL STATUS

**READY.** TIP-006 code and contracts are accepted for TIP-007 consumption.

Deferred, explicitly:

- real company SOT package activation;
- operator package-builder/signing workflow for production;
- hybrid retrieval/index consumption of `sot_reindex_outbox`;
- full corpus migration and business provenance remediation.

Open P0/P1/P2 within TIP-006 implementation: **0**.
