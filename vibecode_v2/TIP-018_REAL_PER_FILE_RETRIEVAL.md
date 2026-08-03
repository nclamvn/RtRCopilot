# TIP-018 · Real Per-File Retrieval (design + gate plan)

**Depends:** TIP-006 (SOT/provenance), TIP-007 (hybrid RAG), TIP-008 (file versions/renditions), TIP-011 (Ask file-scope, safe form). **Branch:** `tip-013b`.
**Contractor** authored this packet + design. **Builder** slice is **NOT executed** — see §8 Build disposition (BLOCKED on the compose stack). **Homeowner:** the DB-backed safety gates are the merge condition.

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
- **Indexing.** Per-version content must be searchable. Two options, decided in DRY-RUN by measuring index cost:
  - (a) **On-ingest version chunks** — TIP-005 already extracts text/renditions per version; add a per-version chunk generation (lexical `tsvector` + `OfflineHashEmbedding` vector) written at ingest, lifecycle-tied to the version. Preferred (query-time parity with SOT).
  - (b) **On-demand extraction** — extract+embed the version at ask time if not indexed; higher latency, no new storage. Fallback only.
- **ACL — identical predicate, version-anchored.** Reuse the SOT guards against the version's resource: `has_effective_acl_deny(version_record, principal, 'view')`, classification ceiling from `filters.classification_ceiling`, owner/department/project ABAC via `policy.decide`. A caller may ask within a version **iff** they may view it (same predicate the Files catalog/viewer uses — no second, weaker path).
- **Isolation invariant.** With `version_id` set, every candidate row MUST satisfy `chunk.version_id = :version_id`; a row from any other version is a leak and fails the gate. Denied/other-version → honest-null (never a partial answer from the wrong file).
- **Grounding unchanged.** `verify_grounding` still requires a citation per sentence; citations carry the version's provenance (version_id, checksums, locator) so the Evidence Rail deep-links into the exact file position (TIP-008 locator contract) — already wired in the UI.
- **DLP / provider policy unchanged.** `ProviderPolicy` and DLP redaction apply as today.

### 3.3 API contract
`POST /ask` `filters`: accept `{version_id}` OR `{source_key}` (never both). The Ask UI already holds `FileScopeItem.versionId`; switch the client to send `version_id` (a one-line change in `ask/page.tsx`, folded into this TIP's Builder slice). Backward compatible: `source_key`-only requests keep the safe-form behaviour.

## 4. Decisions (D-018-##)

- **D-018-01** version_id scope replaces source_key when present; mutually exclusive; source_key path retained (no behaviour change for SOT-only asks).
- **D-018-02** ACL predicate for a version == the Files viewer predicate (single source of truth; no weaker retrieval path).
- **D-018-03** per-version indexing at ingest (option a) unless DRY-RUN shows unacceptable storage; else on-demand (option b) with a recorded latency note.
- **D-018-04** isolation invariant enforced in SQL (`version_id` equality) AND asserted by two-file leak probes.

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

## 8. Build disposition — **BLOCKED (infra), not started**

The Builder slice is **intentionally not executed in this sandbox.** Contractor due-diligence (03/08/2026):

- The safety gates (§6.1–6.4) require Postgres+pgvector+MinIO+Redis via Docker. In this sandbox the **Docker daemon cannot be started** (`ulimit: Operation not permitted` — privileged start denied), `5432/6379/9000` are closed, and there is **no local pgvector**. Non-DB unit toolchain works (61/61) but covers none of the retrieval safety path.
- Per Vibecode — *gates with teeth; never green-by-assertion; no silent leak* — a change to evidence isolation / ACL **must not** be written-and-shipped without its leak/ACL/grounding gates running. Producing that code here would be exactly the unverified safety-critical change the method forbids.

**To unblock (Homeowner / infra):** bring the compose stack up (a Docker-capable environment) and re-run this TIP's Builder slice; the design above is ready to implement against the live gates. Until then TIP-018 stays at **DESIGN COMPLETE · BUILD BLOCKED**.
