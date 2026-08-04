# TIP-018 · Real Per-File Retrieval

**Status:** VERIFIED (04/08/2026)<br>
**Depends:** TIP-006, TIP-007, TIP-008, TIP-011, TIP-022.<br>
**Branch:** `agent/tip-018-per-file-retrieval`.<br>
**Baseline:** `064d5db6f77f19624e43e9cd0f25f547a79643b4`.<br>
**Merge rule:** DB-backed isolation, ACL, grounding and regression gates are mandatory.

---

## 1. Objective

Replace the TIP-011 **safe-form** file scope (SOT `source_key` filter only) with **real per-file retrieval**: let a caller ask a question grounded in a **specific file version they are permitted to view** — including content that lives in that file's own renditions/private context and is not a published SOT source — while keeping the evidence-isolation and ACL guarantees exactly as strict as SOT retrieval. Misses still resolve to honest-null; wrong-file or denied content can never surface.

This closes the deferral recorded in TIP-007 (§92/§262 "no attachments") and TIP-011 (Completion §32 / Verify AC-05 "safe form; real per-file deferred").

## 2. Scope

**In:** the retrieval path (`rag/retrieval.py`, `rag/answering.py`, `rag/models.SearchFilters`), a version-scoped chunk source, the Ask API's filter contract (`filters.version_id`), and the leak/ACL/grounding test matrix. **Out:** UI (the Ask file picker already sends a version — TIP-011 `FileScopeItem.versionId`); SOT publish/graduation; document OS; any migration beyond an additive index if required.

## 3. Design

### 3.1 Current safe form (baseline)
`RetrievalService._metadata` selects from `active_search_generations → chunks c` and filters `WHERE (:source_key IS NULL OR c.source_key = :source_key)` plus classification ceiling, freshness, provenance and `has_effective_acl_deny(...)`; `_allowed` then runs `policy.decide` (ABAC) per row. File scope = restrict to the SOT source's chunks. It **cannot** surface a file's own non-SOT content (that content is not in `chunks`).

### 3.2 Real per-file retrieval
- **D — Scope by immutable `version_id`, not `source_key`.** Add `SearchFilters.version_id: uuid | None`. When set, retrieval targets the chunks produced from **that file version** (join `chunks c → renditions/extraction of version_id`), NOT the SOT source key. `source_key` and `version_id` are mutually exclusive at the API boundary.
- **Indexing.** The 04/08 DRY-RUN found that `chunks` is intentionally SOT-only
  (`source_zone='sot'` plus mandatory package/record/generation FKs). File content
  therefore uses a separate immutable `file_chunks` plane, keyed by
  `document_version_id`, populated from verified JSON renditions during ingest.
  It has the same lexical/vector primitives but cannot masquerade as SOT.
- **ACL — identical predicate, version-anchored.** Reuse the SOT guards against the version's resource: `has_effective_acl_deny(version_record, principal, 'view')`, classification ceiling from `filters.classification_ceiling`, owner/department/project ABAC via `policy.decide`. A caller may ask within a version **iff** they may view it (same predicate the Files catalog/viewer uses — no second, weaker path).
- **Isolation invariant.** With `version_id` set, every candidate row MUST satisfy `chunk.version_id = :version_id`; a row from any other version is a leak and fails the gate. Denied/other-version → honest-null (never a partial answer from the wrong file).
- **Grounding unchanged.** `verify_grounding` still requires a citation per sentence.
  Citation persistence uses an XOR source reference (`chunk_id` for SOT or
  `file_chunk_id` for private context), with exact version checksum and locator.
- **DLP / provider policy unchanged.** `ProviderPolicy` and DLP redaction apply as today.

### 3.3 API contract
`POST /ask` `filters`: accept `{version_id}` OR `{source_key}` (never both). The Ask UI already holds `FileScopeItem.versionId`; switch the client to send `version_id` (a one-line change in `ask/page.tsx`, folded into this TIP's Builder slice). Backward compatible: `source_key`-only requests keep the safe-form behaviour.

## 4. Decisions (D-018-##)

- **D-018-01** version_id scope replaces source_key when present; mutually exclusive; source_key path retained (no behaviour change for SOT-only asks).
- **D-018-02** ACL predicate for a version == the Files viewer predicate (single source of truth; no weaker retrieval path).
- **D-018-03** use a dedicated on-ingest `file_chunks` plane. Reusing SOT chunks
  was rejected because it would break publish provenance and source-zone truth.
- **D-018-04** isolation invariant enforced in SQL (`version_id` equality) AND asserted by two-file leak probes.
- **D-018-05** persisted citations have exactly one source: SOT chunk XOR file
  chunk. Conversation replay re-authorizes the same version lineage before text
  or citation disclosure.

## 5. Acceptance criteria

| AC | Criterion |
|---|---|
| AC-01 | Ask within a viewable version returns a grounded answer citing **only** that version's chunks; deep locator opens the exact position. |
| AC-02 | **Isolation:** a two-file probe never surfaces file B's content when scoped to file A (byte-level leak check), at every classification. |
| AC-03 | **ACL:** a version the caller cannot view → honest-null; classification ceiling and explicit deny both honoured; denied ≡ nonexistent (no existence leak). |
| AC-04 | Miss within an allowed version → honest-null (never a fabricated or cross-file answer). |
| AC-05 | SOT-only asks (source_key / no filter) are **byte-unchanged** vs pre-TIP (no regression). |
| AC-06 | Grounding invariant holds (citation per sentence); confidence caveat behaviour unchanged. |
| AC-07 | Recall@5 within-version ≥ target on the fixture corpus. |

## 6. Gates with teeth (DB-backed — MANDATORY, cannot be asserted)

Run on the live stack (Postgres 16 + pgvector, MinIO, Redis) via `compose.yaml`:

1. `pytest tests/ -q` (full) — incl. new `test_retrieval_per_file` isolation/ACL/grounding cases; **0 fail**.
2. **Leak matrix** — two-file, cross-classification, denied-vs-nonexistent byte-identical probes; **0 leak**.
3. **Masquerade/boundary/forged** probes re-run (as TIP-010/011) — **0 hit**.
4. Recall@5 within-version on the eval harness ≥ target.
5. `ruff` + `mypy` clean; `alembic upgrade head` single head (additive index migration only, if option a).
6. Web: the `filters.version_id` client switch keeps Playwright + axe green.

**A retrieval change to the leak-critical path is not mergeable until 1–4 pass on the live stack.**

## 7. DRY-RUN

Measure per-version index cost (option a vs b) → add `SearchFilters.version_id` + SQL version-scope + ACL anchor → write leak/ACL/grounding fixtures + tests → run §6 → switch the Ask client filter → Completion + Verify.

## 8. Build disposition

TIP-022 restored the full local compose gate. Postgres+pgvector, MinIO, Redis,
API, worker and Web are operational at the baseline SHA, so the prior
infrastructure blocker is closed. Builder implementation and live verification
are now authorized; no completion claim is permitted until §6 passes.
