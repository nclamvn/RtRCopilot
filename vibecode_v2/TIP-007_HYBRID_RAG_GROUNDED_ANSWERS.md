# TIP-007 · ACL-filtered Hybrid RAG & Grounded Answers

## HEADER

- **TIP-ID:** TIP-007
- **Project:** RtR Copilot V2
- **Module:** `v2/apps/backend` + PostgreSQL FTS/pgvector + retrieval/answer worker contracts
- **Depends on:** TIP-006 VERIFIED
- **Priority:** P0
- **Status:** VERIFIED · READY

## CONTEXT

- Working directory: `/Users/os/RtR/KnowledgeBase/RtR_Copilot`
- Blueprint: `vibecode_v2/02_BLUEPRINT_RTR_COPILOT_V2.md`
- Task Graph: `vibecode_v2/03_TASK_GRAPH.md`
- Identity/policy contract: `vibecode_v2/TIP-003_IDENTITY_POLICY.md`
- SOT publish contract: `vibecode_v2/TIP-006_SOT_PUBLISH_PROVENANCE.md`
- Requirements directly implemented/advanced: REQ-007, REQ-008, REQ-009,
  REQ-010, REQ-011, REQ-015, REQ-018, REQ-028, REQ-031.

TIP-006 provides immutable active record versions, evidence, policy resources and a
durable `sot_reindex_outbox`. TIP-007 consumes only activated SOT revisions. It
must never scan staged/rejected/superseded candidates or import the live kernel.

This TIP builds the backend knowledge/answering core and typed API. The full Ask UI
and Evidence Rail belong to TIP-011; file-specific/private attachment retrieval
belongs to later work.

## NON-NEGOTIABLE SECURITY INVARIANTS

1. Candidate **metadata** may be inspected to decide policy, but denied value,
   searchable text, evidence text and embedding must not be loaded or scored.
2. Policy filtering runs before lexical/vector retrieval and runs again immediately
   before model-context construction.
3. DLP/provider-egress checks run on every selected chunk. A chunk rejected by DLP
   is absent from prompt, logs, traces and returned snippets.
4. No allowed evidence means honest-null and **zero model calls**, even when the
   model could answer from prior knowledge.
5. SOT is read-only. Ask/search cannot mutate record, record version, evidence,
   active revision or ACL state.
6. Every factual answer claim is supported by returned citation IDs bound to the
   exact active record version/evidence/checksum/locator used for the answer.
7. Research/private-context data cannot enter this TIP's SOT index.
8. A revision swap and its retrieval index become visible atomically through an
   active generation pointer; partial generations are never queried.
9. Model/provider output is untrusted input and must pass structural grounding
   validation before being returned.

## TASK

### 1. Additive retrieval and answering schema

Create migration `0007_hybrid_rag_grounded_answers` with typed domain/repository
models for:

#### `search_generations`

- generation UUID, source key, source revision, publish run ID;
- deterministic index fingerprint and embedding model/version/dimension;
- lifecycle `building`, `validated`, `active`, `failed`, `superseded`;
- chunk/document counts, build timestamps and sanitized failure fields;
- one active generation per source key through a pointer table or equivalent
  transactionally enforced structure.

#### `chunks`

- immutable chunk UUID and deterministic chunk key;
- generation, record, record version and package identity;
- evidence span identity when evidence-backed;
- source zone fixed to `sot`;
- classification, owner, department/project security snapshot;
- provenance, verification and freshness snapshot;
- normalized text and SHA-256;
- deep locator and source/evidence checksum;
- PostgreSQL `tsvector`;
- pgvector embedding with fixed configured dimension;
- deterministic ordinal and chunking fingerprint;
- lifecycle preventing staged/failed chunks from serving.

#### `index_jobs`

- durable idempotent consumer state for one `sot_reindex_outbox` row;
- lease/heartbeat/retry fields consistent with TIP-005 job patterns;
- pipeline/model versions, progress, failure fingerprint and correlation IDs.

#### `conversations` and `messages`

- immutable IDs, owner, classification and lifecycle;
- message role, sanitized content/checksum and timestamps;
- answer state, provider/model metadata and request ID;
- this TIP supports text questions only; attachments remain unavailable.

#### `answer_runs` and `answer_citations`

- query fingerprint, authorized scope fingerprint, retrieval configuration;
- selected chunk IDs/scores and provider decision;
- grounded/honest-null/failed state;
- token/latency counters without raw secrets;
- citations binding answer marker to record key, version ID, evidence key,
  checksum, freshness, provenance and deep locator.

#### `gaps`

- deterministic normalized-question fingerprint;
- sanitized question/summary, owner/routing state, occurrence count;
- classification, requester and timestamps;
- lifecycle `open`, `triaged`, `resolved`, `dismissed`;
- link to answer run and optional future resolving record;
- duplicate honest-null questions upsert occurrence rather than create spam.

Add necessary indexes/constraints, runtime grants and backup/restore coverage.
Canonical chunks/citations are immutable; runtime cannot DELETE them.

### 2. Reindex consumer and atomic generation

Consume `sot_reindex_outbox` idempotently:

```text
claim outbox/job
  → load exact active package/revision
  → enumerate active record versions/evidence
  → deterministic chunk
  → DLP/indexability validation
  → lexical document + embedding
  → validate counts/checksums/security lineage
  → atomically swap active search generation
  → mark outbox dispatched
```

Rules:

- PostgreSQL is source of truth; Redis may only deliver at-least-once signals.
- Reindex only if the outbox run still matches the active SOT revision.
- Chunk identity is deterministic from active version/evidence/checksum, locator,
  ordinal and chunker version.
- Prefer evidence-aligned chunks. Long text splits at stable paragraph/sentence
  boundaries with bounded overlap and configured token/character limits.
- Do not create a chunk that loses record/evidence/security lineage.
- Same outbox replay produces the same fingerprint and no duplicate visible chunks.
- Failure at any step keeps the prior generation active and marks candidate failed.
- A newer revision supersedes older generations only after candidate validation.
- Embedding adapter is provider-independent. Tests/dev use deterministic offline
  embeddings; production can configure a private/approved adapter without changing
  retrieval contracts.
- Embedding dimensions/model version are validated. Never mix incompatible vectors
  in one generation.
- Empty active package yields a valid empty generation, not stale prior facts.

### 3. Policy-first retrieval pipeline

Implement:

```text
normalize query
  → enumerate active candidate IDs + security metadata only
  → TIP-003 policy decision for requested action
  → query lexical/vector scores restricted to allowed IDs
  → reciprocal-rank or documented deterministic fusion
  → rerank
  → freshness/provenance threshold
  → policy recheck
  → DLP/provider-egress check
  → bounded evidence pack
```

Requirements:

- The first-stage policy query must not select chunk text, searchable text, vector,
  value payload, quoted evidence or locator.
- Lexical and vector SQL both contain an explicit allowed-ID predicate/scope.
- Empty allowed-ID scope short-circuits before content query.
- Policy denial, provider-egress denial and DLP denial are indistinguishable to the
  caller from “not found”; no hidden-result count/timing detail is returned.
- Query normalization handles Unicode/Vietnamese, case, punctuation, CamelCase,
  common exact identifiers and safe typo tolerance without query injection.
- Metadata filters may include source, classification ceiling, freshness and
  provenance; client filters can only narrow server-authorized scope.
- Reranking is deterministic for identical index/query/config. Tie-break by stable
  chunk key.
- Stale/expired evidence is excluded by default or clearly marked only when an
  explicit allowed request mode permits it.
- `claim` evidence cannot support an answer presented as verified.
- Budget limits: query bytes/tokens, candidates, vector/lexical top-k, rerank set,
  evidence pack bytes/tokens and wall time.

Expose a typed internal retrieval result containing score components and citation
lineage, but do not expose embeddings or hidden candidate statistics.

### 4. DLP and provider-egress gate

Create a provider policy adapter receiving only security metadata first.

Default rules:

- deterministic local test/extractive provider may process allowed internal chunks;
- external provider receives only classifications explicitly allowlisted by config;
- `restricted` and `highly_restricted` are external-egress denied by default;
- secrets, credential-like values, personal identifiers and configured sensitive
  patterns are redacted or rejected according to typed rule results;
- DLP runs after retrieval and again on the final serialized context;
- a redaction cannot invalidate checksum/citation semantics silently—returned
  citation says content was redacted, or the chunk is omitted.

Logs/audit contain rule IDs, counts and fingerprints, never rejected raw text.
Production configuration fails closed for an external provider without explicit
classification allowlist, endpoint policy and credential source.

### 5. Model/provider contract and grounded answer verifier

Define provider-independent interfaces for embedding, reranking and answer
generation. Do not hard-code OpenAI, Anthropic, Gemini or any vendor SDK into
domain/service code.

The answer request sent to a provider contains:

- system policy requiring use of supplied evidence only;
- sanitized user question;
- evidence items identified `C1..Cn`;
- per-item provenance/freshness label;
- no local path, ACL internals, hidden counts, UUID not required for citation or
  provider credential.

Provider output must use a strict typed schema:

- answer text;
- used citation markers;
- optional supported follow-up suggestions;
- no tool calls or arbitrary HTML.

Grounding verifier rejects:

- unknown citation marker;
- citation marker for omitted/DLP-denied evidence;
- factual sentence/paragraph without a marker;
- answer claiming verified status from claim/stale/expired evidence;
- quoted evidence not byte/normalized-text supported;
- answer exceeding configured size;
- provider refusal/error disguised as grounded answer.

On grounding failure, retry at most once with a repair instruction if budget permits;
otherwise return honest-null/grounding-failed without leaking the rejected output.

Provide a deterministic offline/extractive answer adapter used by default in local
development and tests. It must demonstrate the complete contract without network.

### 6. Ask/search API

Add typed endpoints:

- `POST /api/v1/search`
  - query plus narrowing filters;
  - returns authorized result cards with snippets, trust/freshness and citations;
  - no model call.
- `POST /api/v1/ask`
  - question, optional conversation ID and safe retrieval options;
  - returns `grounded`, `honest_null` or `failed`;
  - grounded result contains answer, citations and evidence metadata;
  - honest-null contains a safe explanation and gap ID, never model speculation.
- `GET /api/v1/conversations/{id}`
  - owner/policy protected text history and citations;
  - no attachments in this TIP.

All endpoints:

- require current corporate identity;
- use server request ID and typed machine-readable error codes;
- enforce body/query/provider budgets and bounded timeout;
- append durable audit events;
- never reveal whether denied facts exist;
- do not accept client-provided record IDs as authorization proof;
- do not expose raw provider prompt, response, embedding or secret.

Conversation history is not automatically fed back to retrieval/model. Only bounded,
sanitized turns explicitly selected by the service may be included.

### 7. Honest-null and gap workflow foundation

Return honest-null without provider call when:

- no policy-allowed chunks;
- all chunks fail DLP/provider policy;
- retrieval score/grounding threshold not met;
- only unverified claims exist for a verified-fact question;
- selected evidence is expired and stale mode is not permitted.

Create/upsert a gap with:

- sanitized normalized question;
- subject/classification/request context;
- reason category such as `no_evidence`, `denied_or_unavailable`,
  `insufficient_confidence`, `stale_only`, `grounding_failed`;
- deterministic owner routing to configured curator/group or source owner;
- no denied evidence text/count.

The API intentionally coalesces security-sensitive reasons into a safe public
message. Curator workflow/UI is TIP-010.

### 8. Citations and deep locators

Every returned citation includes:

- public citation marker;
- record key and immutable version ID;
- evidence key when present;
- record/evidence content checksum;
- package source/revision;
- provenance, verification and freshness;
- source label;
- typed locator for page, sheet/cell, slide/shape, paragraph/table, bounding box or
  timecode as available.

Citation resolution must verify the record/version/evidence is still active and
policy-allowed at read time. If a revision changes between retrieval and response,
the run fails/retries against the new active generation; it cannot cite a mixed
revision pack.

### 9. Evaluation, leak and benchmark suite

Create deterministic synthetic corpora only. Include:

- exact ID, Vietnamese diacritics/no-diacritics, typo, CamelCase and paraphrase;
- lexical-only, vector-only and fusion wins;
- equal-score stable ordering;
- stale/expired/claim exclusion;
- revision replacement and generation swap;
- owner/group/department/project/classification allow/deny;
- explicit deny overriding role allow;
- same query by two roles yielding different authorized result sets without leaks;
- restricted fact never entering external-provider prompt;
- prompt injection inside evidence treated as data;
- credential/secret DLP fixtures;
- no-evidence, denied-only, stale-only and grounding-failure honest-null;
- citation locator/checksum/version correctness;
- unknown/missing/unsupported citation rejection;
- model timeout/error/malformed output;
- concurrency, replay and failed reindex preservation.

Leak suite gate: **zero** denied chunk text, value, snippet, embedding, locator,
provider context or hidden count in API/audit/log capture.

Retrieval benchmark must have explicit committed thresholds, for example:

- Recall@5 and MRR on synthetic golden set;
- 100% exact identifier retrieval;
- 100% policy correctness;
- 100% citation lineage validity;
- bounded p95 on local seeded corpus with provider time excluded.

Thresholds must be realistic, documented and fail CI when regressed; do not claim
production latency from tiny fixtures.

## ACCEPTANCE CRITERIA

1. **AC-01 — Schema/index:** migration upgrade/downgrade passes; chunk, generation,
   answer, citation, conversation/message and gap constraints enforce lineage.
2. **AC-02 — Atomic reindex:** valid outbox builds one active generation;
   replay/concurrency is idempotent and failure preserves the prior generation.
3. **AC-03 — Active-only:** staged/rejected/superseded SOT versions and partial
   generations are never indexed or returned.
4. **AC-04 — Policy before content:** instrumentation proves denied text/vector/value
   is not loaded or scored before policy selection.
5. **AC-05 — Hybrid quality:** lexical/vector/fusion/rerank pass committed golden
   Recall@5/MRR/exact-ID thresholds with deterministic ordering.
6. **AC-06 — Policy correctness:** all user/group/role/department/project/
   classification/deny scenarios return only allowed chunks.
7. **AC-07 — DLP/provider gate:** restricted/secret fixtures never enter an external
   provider context or logs; final serialized context is rechecked.
8. **AC-08 — Grounding:** every factual answer unit has valid evidence markers and
   unknown/missing/weak citation output is rejected.
9. **AC-09 — Honest-null:** all no-safe-evidence cases return safe honest-null,
   create/upsert one gap and make zero provider calls.
10. **AC-10 — Deep citation:** returned and persisted citations resolve to the exact
    active version/evidence/checksum/locator under current policy.
11. **AC-11 — Revision consistency:** a request never mixes source revisions; swap
    during answering causes bounded retry/fail-closed.
12. **AC-12 — API security:** anonymous is denied; identities receive role-specific
    results with no hidden count, prompt, embedding, path or provider output leak.
13. **AC-13 — Conversation ownership:** history is owner/policy protected, bounded
    and cannot inject arbitrary prior content into model context.
14. **AC-14 — Audit/cost:** search/ask/gap/provider events are durable, sanitized and
    include request/run IDs, latency and token/budget counters.
15. **AC-15 — Recovery:** backup/restore verifies generations, chunks, citations,
    gaps, active pointers and immutable checksums/grants.
16. **AC-16 — Regression/leak:** leak suite has zero violations; TIP-001..006
    regression, Ruff, strict mypy, unit/integration and security gates pass.
17. **AC-17 — Runtime smoke:** migrated local stack is healthy; deterministic local
    provider completes one grounded Ask and one honest-null Ask through HTTP.

## CONSTRAINTS

- Do not modify or activate `/Users/os/RtR/kernel`, KnowledgeBase registries, GOI or
  research/refinery data.
- Do not implement TIP-008 Files UI/viewers, TIP-010 research graduation/admin UI
  or TIP-011 final Ask UI/Evidence Rail.
- Do not add a generic SOT mutation endpoint.
- Do not send denied/raw corpus content to any external service during BUILD/VERIFY.
- Do not require external network/model credentials for local tests or runtime smoke.
- Do not let the answer provider perform retrieval, authorization, tool calls or
  direct database access.
- Reuse TIP-003 policy, TIP-004 audit/UoW, TIP-005 job/outbox patterns and TIP-006
  active revision/security lineage.
- New provider/vendor integration beyond the adapter contract is a Level-2
  suggestion, not an implicit dependency.

## REPORT FORMAT

Create `vibecode_v2/TIP-007_COMPLETION_REPORT.md` containing:

- `STATUS: DONE | PARTIAL | BLOCKED`
- `REQUIREMENT COVERAGE`: implemented/advanced/missing REQ-ID counts
- `FILES CHANGED`
- `MIGRATION`
- `REINDEX/ATOMICITY EVIDENCE`
- `POLICY/DLP/LEAK EVIDENCE`
- `RETRIEVAL BENCHMARK`: dataset size, Recall@5, MRR, exact-ID and p95
- `GROUNDING/HONEST-NULL EVIDENCE`
- `TEST RESULTS`: every AC with pass/fail and exact counts
- `RUNTIME SMOKE`
- `ISSUES`: severity and owner
- `DEVIATIONS`
- `SUGGESTIONS`
