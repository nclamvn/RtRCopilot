# Scan and requirements · Enterprise OS upgrade

Date: 2026-10-06. Baseline: `0e88f48588dc3228f1ae9eca7a7597d96589af8b`.
Scan mode: focused, read-only Builder scan plus Contractor source inspection.

## Measured source inventory

| Metric | Count | Interpretation |
|---|---:|---|
| Git-tracked repository files | 908 | Baseline before this packet |
| Backend Python source files | 152 | Current V2 source |
| Web TS/TSX source/test files | 59 | Includes colocated unit tests |
| Backend first-level packages | 20 | Cache directories excluded |
| Backend test files | 70 | File count, not test pass count |
| Backend test declarations | 730 | Static declarations; parametrization changes executed count |
| Web unit-test files | 22 | No new execution claimed |
| Browser spec files | 12 | CI primarily uses mocked services |
| Alembic revisions | 15 | Expected head `0015_generation_term_stats` |
| Backend HTTP route declarations | 91 + 2 dev | Static route inventory |

Stack: Python 3.12, FastAPI, Pydantic, SQLAlchemy async, PostgreSQL/pgvector,
Redis, MinIO; Next.js/React/TypeScript with custom CSS; pytest/mypy/Ruff and
Vitest/Playwright/axe. Versions are those in the current manifests, not a claim
that they are latest available. No installed dependency or runtime was changed
during preparation.

## Current capability and reusable seam

| Area | Verified in source | Gap for Enterprise OS |
|---|---|---|
| Identity/policy | OIDC/PKCE/session identity, explicit deny, resource principals, project/department scope, separation of duties | Capability-specific effects and delegation |
| SOT/RAG | Signed package publish, immutable revisions, evidence, hybrid retrieval, DLP, `use_class`, budgets, SSE | Breadth/freshness and utility require renewed acceptance, not only retrieval rank |
| Files | Governed upload, extraction, renditions, immutable version scope, ACL | Stronger artifact composition and Vietnamese/media fidelity tests |
| Documents | Typed binding, four formats, approved template plan, render/review/issue/revoke | Semantic autofill, richer document composition, reliable crash recovery |
| Conversations | Stored owner-bound history; last four sanitized messages at 600 characters each feed planning | Workspace/task memory, retained decisions, preferences and lifecycle |
| Intelligence | Authorized SOT/Research briefing computed on demand | Durable watches, subscriptions, event-driven proposals |
| Jobs | Ingestion leases/outbox/retry, render state, reindex | Versioned general workflows, durable waits, compensation and effect reconciliation |
| Connectors | CRM/MRP/IP contract-ready, HRM blocked; all read-only | Actual connector adapters, governed MCP client/server and source write contracts |

Source anchors (relative to repository root):

- `v2/apps/backend/src/rtr_copilot/auth/policy.py:11,72` — action vocabulary,
  rights/scoping; reuse the engine, extend action mapping deliberately.
- `rag/answering.py:115,1110,2192` — bounded history and persisted answers;
  memory already exists at conversation scope.
- `documents/service.py:570` — approved-template recommendation with separate
  render policy, bounded candidates.
- `documents/renderers.py:78,168` — format limitations: existing XLSX formulas
  are not recalculated; PDF is generic key/value rendering with line truncation;
  DOCX run replacement/PPTX capacity checks need real layout acceptance.
- `documents/service.py:958,1000,1180,1254` and `worker/main.py:160` — document
  DB→Redis publication, retry states and pending-only claim.
- `enterprise_corpus/connectors.py:1,35,180` — no remote I/O in registry,
  read-only contracts and readiness interpretation.
- `intelligence/service.py:178` — on-demand source projection.

## Findings that change the proposed order

**F-01 · Document recovery risk, source-derived, P0 for expansion.** The job
and publication outbox are committed before a direct Redis push. The worker
dispatches ingestion outbox; no document dispatcher/stale-render reclaimer was
found. A render claims only `pending`, and manual retry accepts `failed` or
`cancelled`. A crash can therefore plausibly strand pending/rendering work.
Reproduce with isolated crash injection before changing or certifying behavior.

**F-02 · Artifact fidelity, P1.** Existing file types are supported, but their
rendering quality differs. A file extension and successful HTTP response do not
prove a usable spreadsheet, slide deck or PDF. Recalculation, full text,
layout/font and formula safety need business oracles.

**F-03 · Purpose consistency, P1.** Historical TIP-050 recorded the UI purpose
selector and `/search`/`/intelligence` purpose integration as deferred. Verify
actual behavior across future capabilities and drafts; do not infer closure
from the latest IDF work.

**F-04 · Baseline usefulness remains a gate.** TIP-053 verifies retrieval and
does not recertify external answer synthesis. Historic completion reports and
test counts do not certify the current serving build.

**F-05 · Scale/cost seam.** Single sequential worker, globally serialized audit
append and multi-call Ask repair/review can add tail latency. Measure before
increasing concurrency or adding autonomous loops.

## RRI condensed from existing user decisions

The user's repeated instructions already establish: company employee audience;
ordinary/noisy Vietnamese and English; useful, complete grounded responses;
compact ChatGPT-like UI; creating files; company data first, TheSkyWatch for
external research; cost optimization without quality sacrifice; local-first
completion; external applications can remain ready until owners finish them;
synthetic AI testing must be labelled and does not invent human feedback.

These points are carried forward instead of asking the same questions again.
The five-persona interview is condensed into the requirement matrix below.
New business approvals, retention duration, actual team capacity and spending
caps remain explicit unresolved configuration decisions, not invented facts.

## Requirements matrix

| REQ-ID | Output that must be achieved | Priority | Persona | Milestone |
|---|---|---|---|---|
| EOS-001 | Ordinary/noisy VI/EN questions and follow-ups preserve intended entities and useful answers | P0 | End user | 054.1/.9 |
| EOS-002 | Partial company evidence produces useful supported facts plus explicit missing items, without fabricated completeness | P0 | End user | .1/.2/.9 |
| EOS-003 | Common reads and requested internal drafts avoid repeated approval friction | P0 | End user | .3/.5 |
| EOS-004 | Ask produces a usable draft file, preview and saved artifact with source identity | P0 | End user | .5 |
| EOS-005 | UI streams actual stages, exposes cancel/resume and keeps composer/rail geometry consistent | P0 | End user | .5/.9 |
| EOS-006 | Files have full Vietnamese text, correct fonts/layout and recalculated formula results where required | P0 | QA | .5/.9 |
| EOS-007 | Business state/receipt verifies work completed; prose alone cannot claim success | P0 | QA | .3/.4 |
| EOS-008 | Company entity IDs, ownership, relations, revisions and temporal validity are queryable | P0 | Business | .2 |
| EOS-009 | SOT, live operating state, Research, proposals and memory retain explicit provenance/authority | P0 | Business | .2/.7 |
| EOS-010 | Source deletion and access revocation propagate to cached context and resumed work | P0 | QA | .2/.4/.6 |
| EOS-011 | User/workspace/task memory has scope, owner, evidence, expiry and user correction/deletion | P1 | End user | .2 |
| EOS-012 | Versioned capabilities carry input/output schema, policy action, effect class and limits | P0 | Developer | .3 |
| EOS-013 | Typed plans freeze tool versions, resource versions, arguments, actor and plan digest | P0 | Developer | .3 |
| EOS-014 | Policy checks run before content access and immediately before effects/resumption | P0 | QA | .3/.4 |
| EOS-015 | R2/R3 approval binds exact plan/effect/recipient/amount/version, with expiry and invalidation | P0 | Business | .3/.4 |
| EOS-016 | Crash/restart, queue failure and worker ownership changes recover safely | P0 | Operator | .1/.4 |
| EOS-017 | Duplicate requests/retries do not produce duplicate supported source effects | P0 | QA | .4 |
| EOS-018 | Unknown external effect is reconciled or requires review; unsafe blind retry is prevented | P0 | Operator | .4/.6 |
| EOS-019 | Timeout/cancel/compensation are honest about already-completed irreversible work | P0 | Business | .4 |
| EOS-020 | Durable runner selection is backed by identical local fault/load measurements | P0 | Developer | .4a |
| EOS-021 | MCP tools are admitted by endpoint/identity/schema/version; annotations cannot grant rights | P0 | QA | .6 |
| EOS-022 | MCP tokens have appropriate audience/scopes, secrets stay server-side, egress is controlled | P0 | Operator | .6 |
| EOS-023 | Source contracts remain ready without pretending integrations are connected | P0 | Business | .6/.7 |
| EOS-024 | Company/source context is fetched on demand under caller rights and freshness rules | P0 | End user | .2/.7 |
| EOS-025 | Source delta proposals show additions, changes, conflicts and owner decisions before SOT publication | P0 | Business | .7 |
| EOS-026 | Durable schedules/watches deduplicate events and honor current rights | P1 | Operator | .8 |
| EOS-027 | Model/tool/time/token/spend ceilings apply across the whole workflow | P0 | Operator | .3/.4/.9 |
| EOS-028 | Observe p50/p95/p99, first useful output, success/false-refusal/duplicate rates and cost per accepted outcome | P0 | Business | .9 |
| EOS-029 | Internal content is exported only under applicable purpose/provider policy and session authorization | P0 | Business | all |
| EOS-030 | Audit events correlate actor, build, plan, attempts and evidence without secrets or reasoning dumps | P0 | Operator | .3/.4/.9 |
| EOS-031 | Upgrade/rollback/restore keep specialist contracts, ACL and active SOT intact | P0 | Operator | .1/.4/.9 |
| EOS-032 | Synthetic tests, technical captures, repeated model evaluation and real employee feedback remain distinguishable | P0 | QA | .0/.9 |

## Open decisions and assumption register

- OQ-01: production department heads and exact R2/R3 approval chains; leave
  those effectful tools disabled until owners configure them.
- OQ-02: workspace memory retention period and data residency; development
  fixture policy only in the first build, with expiry required in contract.
- OQ-03: target concurrent employees and daily workflow volume; benchmark at
  documented 10/25/50 synthetic concurrent requests first, not an enterprise
  scale claim.
- OQ-04: monthly provider spend cap and approved finite live dataset; no new
  internal-content external calls are inferred from this research request.
- OQ-05: source applications' authoritative APIs and readiness dates; ready
  contracts remain useful without production connector activation.

No RRI question above blocks preparing or approving the local architecture.
They become explicit configuration gates at their associated implementation
milestones. Blueprint approval selects the direction; routine low-impact
implementation choices stay with Builder/Contractor.
