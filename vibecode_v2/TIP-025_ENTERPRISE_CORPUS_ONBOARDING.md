# TIP-025 — Enterprise Corpus Onboarding, Ontology Governance & Domain-stratified Evaluation

## HEADER

- **TIP-ID:** TIP-025
- **Project:** RtR Copilot V2
- **Module:** Enterprise governance plane · corpus manifests · ontology revisions · evaluation/release gate
- **Depends on:** TIP-024.7
- **Priority:** P0
- **Approval:** Homeowner requested the named milestone on 2026-08-04. This
  preserves the approved TIP-024.7 trust boundary and makes it operational
  across the enterprise rather than adding product-specific exceptions.

## FOCUSED SCAN REPORT

### Existing assets to reuse

- PostgreSQL/Alembic with append-only audit, runtime-role denial probes and
  migration up/down/restore gates.
- Immutable SOT packages, active revisions, source/payload fingerprints,
  provenance, freshness and reindex boundary.
- Immutable Research packages with snapshot manifests, source ownership,
  fingerprints, tiers, corroboration and separation-of-duties graduation.
- Governance queues, owner reviews, versioned settings and Curator/Leader role
  policy.
- TIP-024.7 domain-neutral ontology schema, immutable QueryPlan and live corpus
  evaluator.

### P0 gaps

1. No governed enterprise domain registry with an accountable owner and minimum
   release-evaluation contract.
2. No manifest binds current SOT/Research source snapshots to a domain; there is
   no domain-level drift signal or corpus digest.
3. Ontology JSON is packaged data: no proposal, review, separation of duties,
   activation or immutable revision history.
4. Runtime cannot consume a newly approved ontology without rebuilding the
   image.
5. Evaluation sets are source-controlled scripts, not governed, versioned suites
   stratified by domain, risk and test kind.
6. No release attestation binds ontology digest + live corpus snapshot + suite
   digest + passed evaluation result.
7. Existing 37/37 and 9/9 gates are product-heavy. They prove a baseline, not
   minimum coverage for every active enterprise domain.

### Code health

- Python 3.12/FastAPI/Pydantic strict typing; Ruff and mypy strict.
- Next.js/React/TypeScript strict web shell.
- Current baseline: 445 backend hermetic tests, 60 data-integration tests, 168
  web tests, 105 browser/a11y tests; seven healthy containers.
- Eleven Alembic revisions; current head `0011_ingestion_pub_deferred`.

## RRI REPORT

The request and prior architecture answer the strategic questions. Questions
whose answers are already enforced by SOT/Research/Policy code are auto-answered.
A separate Blueprint checkpoint is skipped because the Homeowner explicitly
selected this TIP and delegated detailed API/LLM design; the decision is recorded
here to preserve the Vibecode audit trail.

### REQUIREMENTS MATRIX

| ID | Requirement | Priority | Persona |
|---|---|---:|---|
| REQ-025-01 | Curators can propose stable enterprise domains with owner, classification and minimum evaluation coverage | P0 | Business |
| REQ-025-02 | A Leader distinct from the proposer must approve a domain before it can become active | P0 | Compliance |
| REQ-025-03 | Corpus manifests bind each domain to active SOT or imported Research sources with exact current fingerprints | P0 | Operator |
| REQ-025-04 | Corpus validation must fail loudly on unknown, inactive, duplicate or drifted sources and must never publish facts itself | P0 | QA |
| REQ-025-05 | Ontology revisions must be schema-validated, digest-bound, append-only and reviewed under separation of duties | P0 | Curator |
| REQ-025-06 | Runtime Ask must consume the active governed ontology without image rebuild; packaged JSON remains a bootstrap fallback only | P0 | Developer |
| REQ-025-07 | Evaluation suites must be immutable/versioned and contain typed cases stratified by domain, risk and query/retrieval/answer kind | P0 | QA |
| REQ-025-08 | Suite approval requires a distinct Leader and active-domain coverage at or above each domain minimum | P0 | Compliance |
| REQ-025-09 | Evaluation execution must use the candidate ontology and caller ACL, record per-domain metrics and fail on any critical case | P0 | QA |
| REQ-025-10 | Answer cases must exercise the real grounded AnswerService; missing approved LLM configuration is a failed/incomplete quality gate, never a lower-quality pass | P0 | End user |
| REQ-025-11 | Ontology activation requires approved revision + approved suite + passed current-corpus run, and creates a cryptographic release attestation | P0 | Operator |
| REQ-025-12 | Any source drift, ontology/suite mismatch or superseding activation invalidates readiness immediately | P0 | Operator |
| REQ-025-13 | All propose/validate/approve/evaluate/activate operations must be policy-checked and audit-recorded without question/evidence plaintext | P0 | Security |
| REQ-025-14 | Existing SOT, Research, ACL, DLP, provenance, citation, budget, breaker and honest-null boundaries must not weaken | P0 | Developer |
| REQ-025-15 | Tests must prove non-product domains, separation of duties, mutation denial, drift invalidation and domain-stratified release gating | P0 | QA |

### AUTO-ANSWERED

- Authentication: company OIDC/session and persisted immutable subject id.
- Authorization: reuse `curate` for proposals/evaluation and `approve` for
  decisions/activation; Leader/Curator separation remains mandatory.
- Canonical truth: SOT and Research packages remain authoritative. Corpus
  onboarding references them; it never edits their content.
- LLM: optional interpretation/generation outside deterministic gates. It cannot
  approve domains, sources, ontology identity, evaluation results or releases.
- Failure mode: fail closed and return typed errors; no warnings-as-success.
- Storage: PostgreSQL immutable ledgers; no new external dependency.

### DECISIONS LOG

| ID | Decision | Options | Chosen / rationale |
|---|---|---|---|
| D-025-01 | Governance storage | File-only vs PostgreSQL | PostgreSQL ledger, because multi-user RBAC/audit already lives there; file JSON remains import/export format |
| D-025-02 | Corpus authority | Copy facts vs bind sources | Bind existing SOT/Research source fingerprints; avoid a third truth zone |
| D-025-03 | Approval model | Curator self-approve vs SoD | Curator proposes/evaluates, distinct Leader approves/activates |
| D-025-04 | Runtime ontology | Rebuild image vs DB active revision | Load active DB revision per Ask with packaged bootstrap fallback |
| D-025-05 | Evaluation structure | One global score vs domain/risk matrix | Per-domain minimums, all critical cases mandatory, overall run pass only when every domain passes |
| D-025-06 | Answer quality | Offline substitute vs real provider gate | Real AnswerService; configuration debt makes the run incomplete/failed |
| D-025-07 | Release identity | Mutable readiness flag vs attestation | Immutable digest over ontology, corpus, suite and evaluation result |
| D-025-08 | UI scope | Full authoring UI vs governed API/readiness | Typed governance API/readiness in TIP-025; rich authoring UI may follow after pilot workflows stabilize |

## VISION & BLUEPRINT

```text
                 EXISTING AUTHORITIES
   active SOT packages               imported Research packages
          │ exact digest                       │ exact fingerprint
          └──────────────┬─────────────────────┘
                         ▼
              governed CorpusManifest
              domain + owner + source refs
                         │ validate current snapshot
                         ▼
Domain proposal ─SoD─► active EnterpriseDomain
                         │ minimum eval coverage
Ontology proposal ─SoD─► approved OntologyRevision
                         │ candidate registry
Eval suite proposal ─SoD─► approved EvaluationSuite
                         │ query / retrieval / answer
                         ▼
                 immutable EvaluationRun
                 per domain + risk metrics
                         │ all critical + minimums
                         ▼
Leader activation ─────► ReleaseAttestation
      digest(ontology + corpus + suite + result)
                         │
                         ▼
          runtime Ask loads active governed ontology
```

### Data contracts

- **EnterpriseDomain:** stable key, display name, owner, classification,
  lifecycle, minimum case count, proposer/approver and immutable decision.
- **CorpusManifest:** one domain/version, canonical list of `sot` or `research`
  source refs, declared fingerprints, manifest digest and lifecycle.
- **OntologyRevision:** validated TIP-024.7 `OntologySpec`, digest, immutable
  proposal/decision/activation states.
- **EvaluationSuite:** typed cases with `domain_key`, `risk_class`, `kind`,
  original question and expected structural/retrieval/answer outcomes.
- **EvaluationRun:** immutable result and per-domain metrics bound to ontology,
  suite, corpus snapshot and evaluation subject digest.
- **ReleaseAttestation:** current activation token; any digest drift means
  readiness is false even before a new release is proposed.

### API surface

```text
POST /api/v1/enterprise/domains
POST /api/v1/enterprise/domains/{id}/decide
POST /api/v1/enterprise/corpus-manifests
POST /api/v1/enterprise/corpus-manifests/{id}/validate
POST /api/v1/enterprise/corpus-manifests/{id}/decide
POST /api/v1/enterprise/ontology-revisions
POST /api/v1/enterprise/ontology-revisions/{id}/decide
POST /api/v1/enterprise/evaluation-suites
POST /api/v1/enterprise/evaluation-suites/{id}/decide
POST /api/v1/enterprise/evaluation-suites/{id}/run
POST /api/v1/enterprise/ontology-revisions/{id}/activate
GET  /api/v1/enterprise/readiness
GET  /api/v1/enterprise/active-ontology
```

## ACCEPTANCE CRITERIA

1. A synthetic policy/customer/project domain can be proposed and approved only
   by distinct Curator/Leader subjects.
2. A corpus manifest validates only when every SOT/Research source is current
   and its exact fingerprint matches; an injected drift is detected.
3. Duplicate domain keys, source refs, ontology ids and evaluation case ids fail
   loudly with typed codes; deliberate cross-entity alias collisions require an
   approved clarification evaluation case before release.
4. An ontology proposal cannot be self-approved or activated without a passed,
   matching, current-corpus evaluation run.
5. Runtime query planning reads an active DB ontology revision and falls back to
   packaged bootstrap only when none exists.
6. Evaluation suite validation proves every active domain meets its minimum case
   count, includes a critical case and covers query, retrieval and grounded-answer
   behavior.
7. Query/retrieval cases run against the candidate ontology and real ACL-filtered
   corpus; answer cases use the real grounded service.
8. Every critical failure or missing LLM quality configuration prevents a passed
   run and release attestation.
9. A successful activation supersedes the prior active revision/attestation and
   a later corpus fingerprint change makes readiness false.
10. Database triggers/runtime grants reject mutation/deletion of immutable
    revisions, suites, runs and attestations.
11. Audit events contain ids/counts/digests/decisions but no question, evidence,
    ontology catalog or source content plaintext.
12. Full Ruff/mypy/unit/integration/web/browser/build/runtime gates pass with one
    Alembic head and backup/restore coverage for the new tables.

## CONSTRAINTS

- Never create a new truth zone or copy mutable fact content into corpus manifests.
- Never let an LLM validate fingerprints, approve governance state or compute a
  release decision.
- Never activate an ontology from a stale corpus snapshot or an incomplete
  domain/risk matrix.
- Never auto-create owners, domains or aliases from scraped text.
- Preserve all existing uncommitted TIP-024.5/024.6/024.7 work; do not commit or
  push unless the Homeowner requests it.

## IMPLEMENTATION STATUS — 2026-08-04

- **Status:** Implemented and verified in an isolated enterprise-governance
  integration environment.
- **Database:** Alembic head `0012_enterprise_governance`; six immutable ledgers,
  guarded transitions, separation of duties and runtime delete/update denial.
- **Runtime:** Ask loads the single active governed ontology at request time;
  bootstrap JSON is used only when the ledger has no active revision.
- **Evaluation:** Every active domain must cover query, ACL-filtered retrieval and
  grounded answer cases, meet its minimum and contain a critical case. Missing
  approved LLM configuration produces `incomplete`, never a lower-quality pass.
- **Release:** Activation binds ontology, corpus snapshot, suite and result
  digests in an immutable attestation; source drift invalidates readiness.
- **API:** 13 typed routes are exposed through the bounded same-origin governance
  proxy. Full ontology payload is restricted to Curator/Leader roles.
- **Local operational state:** schema and containers are current, but no real
  enterprise domain/manifest/release has been seeded. This is deliberate: the
  live directory currently has no approved Curator/Leader operating identities,
  and external LLM processing is still `configuration_required`.
