# TIP-010 · Governance & Research

## HEADER

- **TIP-ID:** TIP-010
- **Project:** RtR Copilot V2
- **Module:** Curator/admin governance, gap/freshness/conflict queues, research
  registry, Refinery adapter, graduation gate and live coverage dashboard
- **Depends on:** TIP-003, TIP-004, TIP-005, TIP-006, TIP-007 VERIFIED
- **Priority:** P0
- **Status:** ISSUED · awaiting Builder
- **Working directory:** `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2`
- **Requirements directly implemented/advanced:** REQ-009, REQ-011, REQ-012,
  REQ-016, REQ-032, REQ-033, REQ-034
- **Gate chính (Task Graph):** *Research never masquerades as RtR fact.*

## CONTEXT

TIP-006 supplies versioned SOT facts with provenance, freshness metadata,
attestation and atomic activation. TIP-007 supplies ACL-filtered hybrid
retrieval, grounded answers, deep citations and honest-null with gap routing —
but a routed gap today is a dead end: nothing persists it as a governed work
item, assigns an owner or closes the loop back into the publish gate.

The pilot proved the doctrine this TIP industrializes:

- kernel-wins with a disputed queue and curator gate;
- honest-null questions becoming knowledge gaps with owners;
- the external Refinery pipeline producing packages with snapshot manifests,
  verbatim evidence spans, insight tiers (P/S/H/X), idempotent re-runs and an
  independent auditor.

What V2 still lacks, and TIP-010 must create:

- no persisted gap lifecycle: honest-null events are not yet a queue with
  owner, SLA and resolution trail;
- no freshness/conflict work queues: TIP-006 stores expiry/supersedes/conflict
  metadata but nobody is scheduled to act on it;
- no research trust zone implementation: the Blueprint mandates three zones,
  yet only SOT and private context exist as storage/retrieval realities;
- no adapter contract for Refinery output: the 587 industry records and future
  crawls have no governed entry path;
- no graduation mechanism from external evidence to candidate company claim;
- no admin/curator workspace and no coverage/freshness/gap dashboard computed
  from live data (REQ-034 explicitly forbids hand-made snapshots).

TIP-010 proves the governed mechanism with synthetic fixtures. It does not
mass-onboard the real research corpus, KnowledgeBase or company kernel — that
is TIP-013 work. Live corpora may be probed read-only, exactly as TIP-006
probed the live kernel.

## DECISIONS LOG

| ID | Decision | Rationale |
|---|---|---|
| D-010-01 | Reuse the already-approved Blueprint; no new Homeowner checkpoint | TIP-010 is the next node of the approved Task Graph (M5 scope) |
| D-010-02 | Research records live in a physically and logically separate trust zone with their own tables, index namespace and labels | The single non-negotiable gate: research must never be storable, retrievable or citable as RtR fact |
| D-010-03 | The Refinery adapter accepts only fingerprinted packages carrying a snapshot manifest, verbatim evidence spans and per-record tier (P/S/H/X); any contract violation rejects the whole package fail-closed | Mirror the TIP-006 SOT adapter discipline; no partially trusted import |
| D-010-04 | Gap lifecycle is an append-only state machine (`open → triaged → assigned → answered → published \| declined`) with immutable transition history, owner and SLA timestamps | An erasable queue is not governance; declined gaps are evidence too |
| D-010-05 | Freshness, conflict and owner-review queues are computed from live TIP-006 metadata at read time; no stored snapshot may serve dashboard numbers | REQ-034; hand-refreshed numbers rot silently |
| D-010-06 | Graduation produces a **draft candidate claim** that enters the existing SOT publish gate; nothing graduated ever activates automatically, and proposer/approver must differ | REQ-011; separation of duties consistent with TIP-009 approvals |
| D-010-07 | Admin governance surfaces manage users/groups/policies/sources/jobs but expose no path that mutates SOT record content directly | REQ-032; admins operate the system, curators operate the truth |
| D-010-08 | Dashboard aggregates are computed server-side under the caller's policy scope; restricted existence must not leak through counts, sums or timing | Aggregate leak is still a leak (TIP-007/008 probe standard) |
| D-010-09 | Tests use synthetic research packages and synthetic SOT fixtures only; live kernel and refinery corpora are probed read-only | Same rule as D-009-09; tests must not launder real data |

## DESIGN DIRECTION

**Subject:** the governance desk of the company's evidence system — where a
curator turns unanswered questions, aging facts and external research into
verified truth, and where an admin sees the health of the whole knowledge
plane.

**Single job:** open a queue, understand exactly why an item needs work, act on
it through a gate — never around one — and leave an audit trail a verifier can
replay.

### Token and layout continuity

Inherit TIP-008/009 graphite, steel, RtR signal orange and locator cyan tokens,
type stacks and responsive breakpoints. No remote fonts, no new design system.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ RT ROBOTICS / KNOWLEDGE OPS      queue search      identity / activity   │
├──────────────────┬───────────────────────────────┬───────────────────────┤
│ Queue ledger     │ Work surface                  │ Evidence & provenance │
│ Gaps · Freshness │ gap detail / research record  │ rail: zone chip,      │
│ Conflicts        │ graduation proposal / admin   │ snapshot, tier,       │
│ Research · Admin │ action with typed states      │ evidence spans, SLA   │
└──────────────────┴───────────────────────────────┴───────────────────────┘
```

At mobile width the queue ledger becomes a drawer and the rail a bottom sheet;
the work surface stays dominant.

### Signature element

The **trust-zone chip**: every record, citation, queue row and dashboard tile
carries a persistent, non-decorative label — `SOT`, `RESEARCH`, `PRIVATE` —
with the research chip visually distinct at a glance. Graduation is presented
as a **gated crossing**: the UI shows the proposal moving *toward* the SOT
zone and stopping at the publish gate, never a drag-and-drop that implies
direct transfer. Respect reduced motion; convey the same states in accessible
text. Vietnamese verbs: “Nhận xử lý”, “Giao cho”, “Đề xuất nâng cấp”,
“Từ chối”, “Đưa vào cổng phát hành”.

## DATA MODEL AND INVARIANTS

Add migration `0009_governance_research` with tenant-safe UUID/FK/check
constraints, indexes, least-privilege grants and backup/restore coverage for:

- `research_sources`: stable key, display metadata, origin (refinery, manual,
  partner), owner, classification, lifecycle state;
- `research_packages`: source, package fingerprint/checksum, snapshot manifest
  (capture time, scope, adapter version), tier composition summary, import
  state, importer subject and timestamps;
- `research_records`: immutable version rows carrying package linkage, tier
  (`P|S|H|X`), normalized content, verbatim evidence spans with source
  URL/locator/checksum, dispute/corroboration state and zone label
  (constant `research`, enforced by check constraint);
- `gaps`: origin (honest-null question hash, manual entry), policy-safe
  question digest, requester scope, state, owner, priority, SLA timestamps
  (`opened/triaged/assigned/due/answered/closed`) and resolution linkage
  (published record version or immutable decline reason);
- `gap_transitions`: append-only state history with actor, timestamp, reason;
- `review_tasks`: computed-queue materialization for assignment only —
  freshness expiry, conflict, scheduled owner review — each row pointing at
  the live SOT record version it concerns; queue *membership* is always
  recomputed from live metadata, never trusted from this table;
- `graduation_proposals`: research record version(s), proposed candidate claim
  draft, proposer, curator decision, rationale, attestation hash, resulting
  publish-gate submission ID and timestamps;
- `governance_settings`: bounded, typed admin-editable operational values
  (SLA windows, queue thresholds) with version history.

Required invariants:

- no update/delete may mutate imported research record versions, gap
  transition history, graduation decisions or attestation hashes;
- `research_records` and SOT record tables share no index namespace; the
  retrieval layer cannot join them into one unlabeled result set;
- a graduation proposal cannot reference an unimported, quarantined or
  policy-denied research record;
- proposer ≠ decider on every graduation decision (server-enforced);
- explicit deny wins over allow across all governance queues and dashboards;
- gap/queue APIs never disclose restricted question content or record
  existence outside the caller's scope — typed 403/404 discipline as in
  TIP-003;
- append-only audit covers package import/reject, record disclosure,
  gap transitions, queue assignment, graduation propose/decide, admin setting
  change and every dashboard export.

## TASK

### 1. Gap intake and lifecycle

Wire TIP-007 honest-null gap routing into a persisted, governed queue:

- automatic gap creation on honest-null with policy-safe digest and dedupe
  (same normalized question → one open gap with an occurrence counter);
- `GET /api/v1/gaps` policy-filtered with stable cursor pagination and state/
  owner/priority filters;
- transitions: triage, assign (owner + due date from `governance_settings`
  SLA), answer (link a published SOT record version), decline (immutable
  reason);
- answering a gap requires the linked record to have reached activation
  through the TIP-006 publish gate — a gap cannot be closed by prose.

### 2. Freshness, conflict and owner-review queues

Compute from live TIP-006 metadata:

- **Freshness:** effective/expiry windows produce `expiring` and `expired`
  entries with the responsible owner; thresholds come from
  `governance_settings`;
- **Conflict:** records in disputed/superseded-ambiguous state surface with
  both sides' evidence; resolution actions route to the publish gate
  (supersede, retire, re-attest) — never in-place edits;
- **Owner review:** scheduled review dates generate assignable tasks.

Queue reads are recomputed live; `review_tasks` only records assignment and
completion. Completing a task without the underlying metadata actually
changing (via publish gate) reopens it on next computation.

### 3. Research registry and Refinery adapter

Implement the research trust zone entry path:

- package upload lands in TIP-005 quarantine (size/MIME/archive safety, AV);
- adapter validates the package contract: fingerprint matches content,
  snapshot manifest present and internally consistent, every record carries
  tier, verbatim evidence spans with source locator and checksums; any
  violation rejects the entire package with a typed, audited error;
- accepted records become immutable `research_records` with zone label
  `research`, indexed in a research-only namespace;
- re-import of an identical package is idempotent (same fingerprint → same
  result, no duplicates);
- read-only probe of the live refinery corpus is permitted to validate the
  contract shape; no live record may be imported in this TIP.

### 4. Graduation gate

Implement the only path from research to company truth:

- an authorized curator drafts a `graduation_proposal` from one or more
  research record versions: proposed claim text, mapped evidence, target
  SOT record shape;
- a different authorized curator approves or rejects with reason;
- approval submits a **draft candidate claim** into the TIP-006 publish
  pipeline carrying full lineage: research record versions, package
  fingerprint, snapshot manifest reference and verbatim evidence checksums;
- the candidate then lives or dies by the existing publish gate (provenance,
  classification, DLP, activation); TIP-010 adds no bypass;
- rejection is immutable; a re-proposal is a new proposal referencing the old.

### 5. Retrieval and citation separation

Enforce the gate chính at the retrieval layer:

- SOT-scoped ask/search never returns research content;
- research-scoped queries are an explicit, separately authorized scope; every
  returned chunk and citation carries the `research` zone label and tier;
- no API response, prompt assembly or citation path may present a research
  record without its zone label; grounding metadata distinguishes
  research-supported statements from SOT-grounded facts;
- DLP and ACL filters run on research content with the same order guarantees
  as TIP-007 (policy before content fetch, recheck before prompt).

Full Ask-UI blending and the unified Evidence Rail remain TIP-011; this TIP
delivers the backend contract plus the governance-workspace views.

### 6. Admin governance surfaces

Extend the API and workspace for REQ-032 within strict boundaries:

- manage `research_sources`, `governance_settings`, queue assignments and
  user/group/role/policy *bindings* (creation of policy objects stays within
  the TIP-003 model);
- inspect ingestion/render/index job health (read-only over existing job
  tables);
- no endpoint mutates SOT record content, research record content, audit
  events or issued documents; attempts fail with typed errors and are audited;
- break-glass and destructive operations (none in this TIP) remain out of
  scope.

### 7. Knowledge Ops workspace

Add a “Vận hành tri thức” workspace alongside Files and Documents:

- queue ledger with counts, filters and SLA badges for gaps, freshness,
  conflicts, reviews and research packages;
- gap detail with occurrence history, assignment, SLA state and resolution
  actions;
- research package/record browser with tier, snapshot and evidence rail;
- graduation proposal flow with side-by-side research evidence and proposed
  claim, gated-crossing state visualization and decision actions;
- dashboard: coverage (SOT records by domain/owner/classification), freshness
  (expiring/expired), gap flow (opened/closed/aging), research intake and
  graduation funnel — all computed live and policy-scoped;
- empty, loading, denied, expired and partial states; keyboard-first primary
  flows; semantic landmarks, one H1, visible focus, WCAG 2.2 AA contrast; no
  layout overflow at 360×800, 768×1024, 1440×900, 1920×1080;
- URL-restorable queue/record/proposal views without restricted metadata in
  browser storage.

### 8. Tests, QA, recovery and documentation

Backend unit/integration tests for: adapter contract violations (missing
manifest, tier, evidence, fingerprint mismatch, oversized, traversal),
idempotent re-import, gap dedupe/lifecycle/SLA, live-computed queue
correctness, graduation separation of duties, publish-gate submission lineage,
zone-separation of indexes, policy/DLP races, audit coverage and
backup/restore of migration `0009` tables.

Frontend tests and Playwright flows for: queue triage, gap assign/answer/
decline, package import success/reject, graduation propose/approve/reject,
dashboard rendering, keyboard and responsive behavior.

Mandatory leak probes:

- anonymous/cross-owner/denied probes over gaps, research records, proposals
  and dashboard aggregates leak zero restricted existence or content;
- **masquerade probes:** every retrieval/citation/API path is probed for a
  research record appearing without its zone label or inside an SOT-scoped
  result — zero tolerance, P0 on any hit.

Update README/API/operator documentation and the backup/restore manifest.
Keep `make verify` as the concurrency-safe full gate and preserve all
TIP-001…009 tests.

## ACCEPTANCE CRITERIA

### AC-01 · Honest-null becomes a governed gap
An honest-null answer creates or increments exactly one policy-safe gap;
duplicate questions dedupe; restricted question content never leaks to
unauthorized viewers.

### AC-02 · Gap lifecycle is append-only and SLA-tracked
Every transition is recorded immutably with actor and reason; SLA timestamps
derive from settings; closing requires an activated SOT record or an immutable
decline; history cannot be rewritten.

### AC-03 · Freshness queue is live and actionable
Expiring/expired facts surface from live metadata with correct owners and
thresholds; a stale materialized row cannot mask a live expiry; resolution only
via publish gate.

### AC-04 · Conflict queue exposes both sides and resolves through the gate
Disputed/superseded-ambiguous records appear with evidence for each side; every
resolution action is a publish-gate operation; no in-place mutation exists.

### AC-05 · Research import is fail-closed
Packages violating the contract (fingerprint, manifest, tier, evidence,
size, traversal, malformed archive) are rejected whole, audited, and leave no
partial records; valid synthetic packages import idempotently.

### AC-06 · Research records are immutable, tiered and evidence-linked
Every imported record carries tier, verbatim evidence spans with checksums and
the constant `research` zone label; no update path can alter imported content.

### AC-07 · Zone labels are unforgeable end-to-end
No API, retrieval, prompt-assembly or citation path returns research content
without its zone label; SOT and research indexes are provably disjoint.

### AC-08 · SOT-scoped retrieval excludes research
SOT-scoped ask/search returns zero research chunks under adversarial probing;
research-scoped queries require explicit authorization and label every result.

### AC-09 · Graduation cannot bypass the publish gate
Approval of a proposal produces only a draft candidate in the TIP-006
pipeline with full lineage to research evidence; nothing activates
automatically; the publish gate can still reject it.

### AC-10 · Separation of duties holds under races
Proposer cannot decide their own proposal; concurrent, duplicate, stale and
unauthorized decisions fail closed and are audited.

### AC-11 · Admin cannot touch truth
No admin endpoint mutates SOT content, research content, audit events or
issuances; attempts produce typed errors and audit entries; permitted
governance settings are bounded, typed and versioned.

### AC-12 · Dashboard is live and leak-safe
All tiles compute from live data under the caller's policy scope; denied
existence does not leak through counts, aggregates, cursors or timing.

### AC-13 · Knowledge Ops UX is operable
An authorized curator completes triage → assign → answer, package import →
inspect, and propose → decide flows keyboard-only across required responsive
sizes, with correct empty/denied/expired states.

### AC-14 · Policy and DLP survive races
Revocation or classification change mid-workflow (import, graduation, queue
action) yields no disclosure and no published artifact; recheck-before-commit
is proven by test.

### AC-15 · Recovery covers governance
Backup/restore retains packages, records, gaps, transitions, proposals,
settings, grants and audit lineage; restored state passes the same integrity
checks.

### AC-16 · Full verification passes
`make verify`, backend/frontend/integration/Playwright suites, masquerade and
leak probes all pass with zero P0/P1; all TIP-001…009 gates remain green.

## OUT OF SCOPE

- Unified application shell, blended Ask UI and shared Evidence Rail (TIP-011).
- HTTPS ingress, quotas, observability, CI/CD, load/DR (TIP-012).
- Mass onboarding of the live 587 research records, KnowledgeBase or company
  kernel; any live-corpus import (TIP-013).
- In-product web crawling or scheduling of Refinery runs; the Refinery remains
  an external pipeline whose *output packages* are imported.
- Forecasting, partner recommendation, policy proposal generation.
- New policy-model primitives beyond TIP-003 (bindings only).
- Electronic notification/email delivery for SLA breaches (surface in-app
  only; delivery channels are a later phase).

## BUILDER HANDOFF

Builder must:

1. implement only inside `v2` plus TIP completion evidence;
2. keep `/Users/os/RtR/kernel`, KnowledgeBase, GOI, refinery corpora and
   `phase1_pilot` strictly read-only;
3. create `vibecode_v2/TIP-010_COMPLETION_REPORT.md` mapping every AC to code,
   tests, commands, counts, screenshots/artifacts and deviations;
4. run `make verify` plus the masquerade/leak probe suite before declaring
   complete;
5. leave the working tree uncommitted for Contractor verification.

Contractor will independently inspect zone separation at the schema, index,
API and citation layers, rerun gates, execute adversarial masquerade probes,
verify graduation lineage end-to-end, then write
`TIP-010_VERIFY_REPORT.md`. Any research record surfacing as RtR fact is an
automatic P0 and returns the TIP to BUILD.
