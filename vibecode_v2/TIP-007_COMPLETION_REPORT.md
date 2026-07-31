# TIP-007 Completion Report

STATUS: DONE

## REQUIREMENT COVERAGE

- Implemented: 5 — REQ-007, REQ-008, REQ-009, REQ-010, REQ-011.
- Advanced: 4 — REQ-015, REQ-018, REQ-028, REQ-031.
- Missing within TIP-007 scope: 0.
- File viewers, private attachments, curator/admin UI and final Ask/Evidence Rail
  remain in TIP-008, TIP-010 and TIP-011 by design.

## FILES CHANGED

- Schema: `v2/apps/backend/migrations/versions/0007_hybrid_rag_grounded_answers.py`.
- RAG domain/services: `v2/apps/backend/src/rtr_copilot/rag/` — adapters,
  answering, API, DLP, models, reindex and retrieval.
- Runtime wiring/config: `api/main.py`, `worker/main.py`, `config.py`,
  `.env.example`, `compose.yaml`.
- Tests/fixtures: `test_rag_unit.py`, `test_rag_integration.py`,
  `sot_fixtures.py`, plus schema-revision assertions in
  `test_data_integration.py`.
- Recovery/gates: `backup-data.sh`, `restore-data.sh`,
  `verify-data-integration.sh`.
- Documentation: task graph and this completion report.

## MIGRATION

- Head: `0007_hybrid_rag_grounded_answers`.
- Upgrade, downgrade, full downgrade-to-base and idempotent upgrade-to-head all
  pass against isolated PostgreSQL 16.
- Added immutable active search generations/chunks, durable index jobs,
  conversations/messages, answer runs/citations and deduplicated gaps.
- `vector(64)`, generated PostgreSQL FTS, HNSW/GIN indexes, deterministic keys,
  checksums, lifecycle constraints and exact lineage foreign keys are enforced.
- Canonical chunks, citations and messages reject mutation; runtime cannot
  DELETE canonical retrieval/answer rows.
- `has_effective_acl_deny` resolves active user, group, role, department and
  project principals in one shared database contract.

## REINDEX/ATOMICITY EVIDENCE

- Reindex consumes only an outbox run that still equals the active SOT
  package/revision.
- Chunk IDs and generation fingerprints bind version/evidence/checksum/locator,
  security snapshot, chunker and embedding model version.
- Same outbox replay returns the same visible generation.
- Concurrent consumers converge on one generation.
- Injected failure after chunk creation rolls back the candidate, marks the job
  failed and preserves the prior active pointer.
- Revision swap uses the same per-source advisory-lock protocol as SOT publish.
- Final answer persistence acquires those source locks and revalidates exact
  active generation/current record version/effective policy inside the final
  transaction before inserting the answer or citations.

## POLICY/DLP/LEAK EVIDENCE

- First-stage queries select security metadata only; denied text, vector,
  evidence, value and locator are not selected.
- Metadata is paginated until the authorized candidate budget, exhaustion,
  scan hard cap or wall deadline. Regression proves denied first pages cannot
  starve a later allowed result.
- Lexical/vector SQL has an explicit allowed chunk-ID predicate. Empty policy
  scope short-circuits with `content_queries=0`.
- Effective deny regression passes for user, group, role, department and project;
  deny overrides role clearance.
- Policy is checked again after ranking and immediately before grounded
  persistence.
- DLP checks the user question, each evidence item and final serialized context.
  Secret input is replaced with a safe placeholder before message/gap storage;
  restricted external-provider evidence and credential fixtures make zero model
  calls.
- Leak result: 0 denied raw texts/snippets/vectors/locators/provider contexts or
  hidden counts observed in API, persisted messages/gaps, audit details or test
  traces.

## RETRIEVAL BENCHMARK

- Corpus: 5 deterministic synthetic golden records; no company/kernel/research
  data.
- Coverage: exact dotted ID, Vietnamese no-diacritic normalization, CamelCase,
  typo-tolerant vector features, lexical and deterministic RRF fusion ordering.
- Committed gates: Recall@5 >= 1.00, MRR >= 0.80, exact-ID >= 1.00,
  local p95 <= 500 ms.
- Observed repeat-safe local run: Recall@5 **1.000**, MRR **0.900**,
  exact-ID **1.000**, p95 **6.80 ms**.
- The latency is a tiny local synthetic-corpus regression metric, not a
  production SLO claim.

## GROUNDING/HONEST-NULL EVIDENCE

- Default local adapter is deterministic, offline and extractive; there is no
  vendor SDK or network/model credential dependency.
- Verifier rejects unknown/missing markers, ungrounded factual sentences,
  unsupported evidence overlap, claim/stale “verified” statements, refusals,
  HTML/control payloads and answer-budget overflow.
- Evidence instructions are treated as data by the provider system contract.
- Provider execution has a configured hard timeout and at most one repair.
  A hanging provider test completes under one second, records two bounded calls
  and returns honest-null.
- No allowed evidence, DLP-denied input/context and grounding failure all return
  the same safe public explanation. Repeated questions upsert one gap and
  increment occurrence count.
- Grounded citations persist and return exact record/evidence keys, immutable
  version ID, checksums, source revision, trust/freshness and deep locator.
- Conversation reads recheck active lineage and effective policy; revoked
  citations and the derived old answer content are withheld.

## TEST RESULTS

- Full backend regression: **158 passed, 34 skipped** environment integrations.
- Isolated PostgreSQL data integration: **33 passed**.
- TIP-007 focused: **5 unit + 13 integration cases**, with four parameterized
  effective-principal paths.
- Migration revisions/fixtures: **7/7**; runtime mutation denials: **18/18**.
- Verification database and object bucket are isolated per invocation, so
  concurrent gate runs cannot migrate or clean up one another's fixtures.
- Existing policy matrix: **48 scenarios**.
- Web: ESLint pass, TypeScript pass, Vitest **1/1**, Next production build pass.
- Ruff pass; strict mypy pass across **62 source files**.
- Compose/image build pass; Trivy detected **0** OS/Python vulnerabilities.

| AC | Result | Evidence |
|---|---|---|
| AC-01 Schema/index | PASS | 0007 up/down/full-chain; vector/FTS/constraints |
| AC-02 Atomic reindex | PASS | replay, concurrent consumer, injected failure |
| AC-03 Active-only | PASS | active pointer/package/version joins |
| AC-04 Policy before content | PASS | deny trace has zero content queries/IDs |
| AC-05 Hybrid quality | PASS | committed Recall@5/MRR/exact-ID/p95 gates |
| AC-06 Policy correctness | PASS | 48 policy scenarios + five principal types |
| AC-07 DLP/provider gate | PASS | secret/restricted zero-call leak regressions |
| AC-08 Grounding | PASS | sentence/marker/support/trust/output validation |
| AC-09 Honest-null | PASS | no-safe-evidence gap upsert and zero model calls |
| AC-10 Deep citation | PASS | exact persisted version/checksum/locator |
| AC-11 Revision consistency | PASS | advisory lock plus final transaction recheck |
| AC-12 API security | PASS | anonymous 401; policy-specific opaque results |
| AC-13 Conversation ownership | PASS | owner-only, bounded, revocation recheck |
| AC-14 Audit/cost | PASS | durable sanitized runs/events/tokens/latency |
| AC-15 Recovery | PASS | row counts, pointers, lineage, checksums and grants |
| AC-16 Regression/leak | PASS | full VERIFY and leak=0 |
| AC-17 Runtime smoke | PASS | healthy stack; HTTP grounded + honest-null |

## RUNTIME SMOKE

- Rebuilt local API, worker and web are healthy at schema
  `0007_hybrid_rag_grounded_answers`.
- Corporate development OIDC session resolved a persisted staff subject.
- HTTP grounded request `tip007-runtime-grounded` returned a cited active answer
  with record version, record/evidence checksums and paragraph locator.
- HTTP DLP request `tip007-runtime-honest-null` returned honest-null with a gap
  ID, no citations and no provider call.
- Recovery drill: backup archive completed; isolated restore passed revision
  0007, 25 object checks, 100% row counts/checksums, valid audit chain and 16
  runtime denial probes. The isolated restore database/bucket were removed.

## ISSUES

- P3 / dependency owners: existing Starlette/httpx and SWIG deprecation warnings
  remain; they do not affect gates.
- No P0, P1 or P2 issue remains in TIP-007 scope.

## DEVIATIONS

- Development/test embeddings use a deterministic 64-dimensional hashing
  adapter rather than an external semantic model. This is the approved offline
  adapter boundary; provider replacement does not alter retrieval contracts.
- RRF is the deterministic reranker for this TIP. No external reranking service
  was introduced.
- No kernel, KnowledgeBase registry, GOI or research/refinery file was modified
  or indexed.

## SUGGESTIONS

- Before production rollout, calibrate `rag_metadata_scan_limit`,
  `rag_retrieval_timeout_ms`, score thresholds and provider timeout on a
  representative authorized corpus; retain the synthetic gates as regression,
  not capacity evidence.
- TIP-010 should build curator triage/resolution on the existing gaps table.
- TIP-011 should consume the typed Ask/search/citation contracts without moving
  retrieval authorization into the browser.
