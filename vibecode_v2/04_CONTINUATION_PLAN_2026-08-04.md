# RtR Copilot — Continuation Plan after X-Ray

> **Date:** 04/08/2026
> **Status:** APPROVED · execution started with TIP-022
> **Input:** `PROJECT_XRAY.md`, commit `0d8f9e0`
> **Method:** Vibecode Kit v6.1
> **Goal:** convert the advanced mechanism into one reproducible release candidate,
> then a measured internal pilot, without weakening SOT/policy/grounding.

---

## 1. Contractor recommendation

Do not add another broad feature now. The shortest path to value is:

```text
BASELINE GREEN
    │
    ▼
TIP-018 REAL PER-FILE / PRIVATE CONTEXT RETRIEVAL
    │
    ├────► TIP-014 FORMAL CLOSURE + REAL SEMANTIC EMBEDDING
    │
    └────► ADMIN WORKSPACE + PILOT CORPUS
                    │
                    ▼
          PRODUCTION-LIKE PILOT
                    │
                    ▼
           CONNECTORS → APPROVED ACTIONS
```

The original 13-TIP architecture is largely complete. The next work is not a
rewrite; it is closure, activation and proof.

---

## 2. Proposed work graph

| Order | Work package | Priority | Exit condition |
|---:|---|---:|---|
| 0 | Recovery Gate / TIP-022 | P0 for continuation | local + CI green, runtime matches HEAD, worker healthy |
| 1 | Resume TIP-018 | P0 product | version-scoped private file retrieval; leak 0 |
| 2 | Close TIP-014 | P0 quality | real embedding path + independent Verify Report |
| 3 | TIP-023 Admin Workspace — local verified, PR/CI pending | P1 rollout | operator can manage approved admin surfaces without raw APIs |
| 4 | TIP-024 Pilot Corpus & Provenance | P0 rollout | representative Files/Templates/Research live; soft-fact ownership |
| 5 | TIP-025 Production-like Pilot | P0 rollout | real OIDC/TLS/secrets, measured pilot, go/no-go |
| 6 | Phase C connectors | post-pilot | read-only MRP/CRM/HRM/IP/Workspace/chat adapters |
| 7 | Action workflows | post-governance | approvals, idempotency, audit and rollback proven |

Numbers TIP-022…025 are proposed because commit labels already consumed 020/021.
No implementation begins until the Homeowner approves this revised graph.

---

## 3. Recovery Gate — proposed TIP-022

### Objective

Establish one reproducible truth for source, CI and local runtime before touching
the retrieval safety path.

### Scope

- fix `make verify` Docker fallback so sibling `v2/eval` is available;
- fix the ambiguous Playwright conversation heading selector;
- rebuild/force-recreate API, worker and Web from current HEAD;
- require worker heartbeat in the operational readiness summary;
- expose build SHA/version in API status and Web diagnostics;
- rerun 148 web unit tests, backend suite, data integration and 88 browser tests;
- reconcile stale status headers and add factual paper trail for CI fixes 020/021;
- review and remove tracked `_to_delete` artifacts;
- replace tracked `.env.demo` with a safe example; rotate its signing value if
  it was reused outside local demo.

### Acceptance criteria

- **AC-022.1:** `make verify` passes on a machine without preinstalled `uv`.
- **AC-022.2:** GitHub aggregate `verify` passes on the resulting commit.
- **AC-022.3:** browser 88/88; axe critical/serious = 0.
- **AC-022.4:** API/Web report the same commit SHA as Git HEAD/deploy ledger.
- **AC-022.5:** worker is healthy and `POST /system/ping` returns 200.
- **AC-022.6:** worktree contains no tracked runtime secret or recovery trash.
- **AC-022.7:** no product behavior, schema or authorization contract changes.

Estimated effort: **1–2 focused days**.

---

## 4. Resume TIP-018 — Real per-file retrieval

### Objective

Close REQ-020 and allow Ask to use a specific authorized file version as private
evidence without publishing that file as company SOT.

### Build decision

The previous infrastructure blocker is gone. Use **ingest-time per-version
chunks** unless a measured storage/latency comparison proves on-demand indexing
materially safer or cheaper.

### Required implementation

- additive migration for version-scoped chunks/index if required;
- `SearchFilters.version_id`, mutually exclusive with `source_key`;
- anchor policy to the exact file-version resource;
- reuse Files viewer authorization; no second weaker ACL path;
- every candidate must satisfy exact version equality;
- citations carry version checksum and deep locator;
- UI sends `version_id`, not logical source name;
- revocation immediately removes retrieval access;
- private file chunks never enter active SOT generations.

### Acceptance criteria

- allowed version → grounded answer cites only that version;
- file A scope never returns file B bytes/tokens;
- denied, expired, revoked and nonexistent are indistinguishable;
- allowed miss → honest-null;
- SOT-only asks remain unchanged;
- leak matrix = 0;
- grounding and DLP remain unchanged;
- within-version Recall@5 meets a declared fixture target;
- full local/CI/browser gates green.

Estimated effort: **2–4 focused days** after TIP-022.

---

## 5. Close TIP-014 — Query understanding and semantic quality

### Current truth

Implemented:

- curated deterministic product aliases;
- bounded fuzzy resolution;
- optional Anthropic → OpenAI query rewrite;
- circuit breaker/timeout/fallback;
- guard against entities outside the curated registry.

Verified on 04/08/2026:

- independent Contractor Verify issued;
- external rewrite now requires explicit `internal` classification allowlist;
- orchestration timeout preserves Anthropic → OpenAI fallback;
- actual rewrite attempts debit the shared provider budget;
- alias variants ground to their exact scoped SOT citations; unavailable scope
  remains honest-null.

Still open:

- retrieval/reindex still use `OfflineHashEmbedding`;
- no representative real-provider benchmark;
- optional answer composition remains deferred.

### Required closure

- implement a provider-neutral real embedding adapter;
- version embedding model/index and support atomic reindex;
- keep offline hash only as test/demo mode;
- benchmark natural Vietnamese/English, typo, acronym, price/spec/compare intents;
- measure Recall@5, MRR, honest-null precision, leakage and latency;
- rerun the existing provider timeout/breaker/budget evidence with the selected
  live provider without committing credentials.

### Exit targets

- answerable pilot queries: target agreed after baseline, recommended grounded
  success ≥90%;
- truly unsupported queries: honest-null precision 100%;
- leak 0;
- wrong-entity resolution 0 in the curated eval set;
- p95 retrieval and provider latency within declared SLO;
- deterministic fallback remains functional with all external providers disabled.

Estimated effort: **2–4 focused days**, plus provider access/calibration.

---

## 6. TIP-023 — Admin Workspace

**Execution status 04/08/2026:** implemented and Contractor-verified locally;
GitHub PR/CI and post-merge convergence remain. See
`TIP-023_ADMIN_WORKSPACE.md`, `TIP-023_COMPLETION_REPORT.md` and
`TIP-023_VERIFY_REPORT.md`.

### Objective

Convert the existing backend admin APIs into an operator-safe UI. This corrects
the product-level overstatement that REQ-032 is fully complete.

### Surfaces

- subjects and role/group mappings;
- research sources;
- governance settings/SLA thresholds;
- gap-priority override;
- job/worker health;
- read-only audit/status links;
- no direct SOT mutation.

### Gates

- admin/curator/staff/anonymous matrix;
- admin non-bypass remains true;
- every mutation audited;
- stale-session revocation verified;
- keyboard, vi/en, mobile and axe gates;
- worker-unavailable state is explicit.

Estimated effort: **2–3 focused days**.

---

## 7. Proposed TIP-024 — Pilot corpus and provenance campaign

### Objective

Make Files, Documents and Research real, not empty surfaces, while increasing
the strict-evidence share of the 219 activated facts.

### Pilot batch recommendation

- 20–30 high-use product/company records;
- 30–50 representative PDF/DOCX/XLSX/PPTX/image/media files;
- 4–8 approved company templates;
- 50–100 research records from one chosen industry space;
- 25–40 pilot questions across staff, leader, curator and admin.

### Provenance policy

- keep 8 strict facts as gold baseline;
- assign domain owners to all 211 caveated ready facts;
- prioritize facts used in external/legal/price/spec outputs;
- do not bulk-remove caveats;
- held cost/derived/gap facts stay held until their named condition is resolved.

### Gates

- zero unauthorized activation;
- zero cross-zone masquerade;
- original/rendition/checksum parity;
- template locked-fact binding on real examples;
- no stale value in official output;
- eval metrics and curator SLA captured.

Estimated effort: **1–3 weeks**, dominated by human curation rather than code.

---

## 8. Proposed TIP-025 — Production-like pilot

### Homeowner inputs

- Google Workspace OIDC tenant/client/groups;
- real hostname and TLS certificate;
- production secret store/injection;
- named data owners and curator;
- pilot cohort and role matrix;
- authority to sign go/no-go.

### Exit criteria

- hardened deployment passes ingress/security probes;
- worker, queues, backup/restore and rollback drills pass on the target host;
- external penetration test has no P0/P1;
- real-provider cost/latency calibrated;
- pilot runs at least two measured weeks;
- leakage/authorization failure = 0;
- five product metrics reported:
  - time-to-evidence;
  - grounded answer rate;
  - honest-null correctness;
  - document cycle time;
  - gap resolution/freshness SLA;
- zero open P0/P1 and signed go/no-go.

Estimated effort: **2–4 weeks after TIP-024**, depending on infrastructure and
pilot participation.

---

## 9. Post-pilot roadmap

### Phase C1 — Read connectors

Connect MRP, CRM, HRM, IP, Google Workspace and internal chat through:

- domain-owned adapters;
- incremental sync/event contracts;
- source/version/owner/classification mapping;
- read-only access first;
- connector health and reconciliation dashboard.

### Phase C2 — Strategic intelligence

- industry signal registry;
- account/opportunity hypotheses;
- partner-fit and proposal suggestions;
- forecast objects explicitly separated from facts;
- outcome feedback to measure recommendation quality.

### Phase C3 — Approved action workflows

- create CRM follow-up, draft Workspace document, open MRP/HRM/IP task;
- human approval for consequential actions;
- idempotency, least privilege, audit and rollback;
- no autonomous write access by default.

---

## 10. Homeowner decisions

Recommended defaults:

| ID | Decision | Recommendation |
|---|---|---|
| H-022-01 | Approve Recovery Gate before new feature work | **YES** |
| H-018-01 | Require TIP-018 before production-like pilot | **YES** |
| H-014-01 | Supply one real embedding provider for calibration | **YES**, secret via env only |
| H-023-01 | Include Admin UI in pilot scope | **YES** |
| H-024-01 | Allow caveated soft facts in pilot | **YES, internal-only with visible caveat and owner** |
| H-025-01 | Permit production activation now | **NO**, only after TIP-022/018/014/023/024 gates |

Approval phrase:

> **APPROVED CONTINUATION PLAN 2026-08-04**

After approval, the Contractor should issue TIP-022 first. No architecture
change is required; the plan restores verified truth, closes the last P0
requirement gap and moves into controlled pilot evidence.

---

## 11. Completion definition

The next phase is complete only when:

- source, CI and runtime identify the same release;
- every required gate is reproducible locally and in CI;
- REQ-020 is fully implemented;
- query quality is measured with real embeddings without weakening grounding;
- Admin is operational;
- representative real files/templates/research are onboarded;
- real OIDC/TLS/secrets and pilot metrics are proven;
- zero P0/P1 remain;
- Homeowner signs go/no-go.

Until then, the correct label is **advanced internal release candidate under
controlled development**, not company-wide production.
