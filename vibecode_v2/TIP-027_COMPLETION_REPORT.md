# TIP-027 — Completion Report

## STATUS

**IMPLEMENTATION COMPLETE · FINAL LIVE ACCEPTANCE PENDING** — TIP-027.1
Foundation and TIP-027.2 Company breadth are implemented and pass hermetic
local QA. The final external-LLM E2E campaign cannot yet be accepted because
the configured provider account exhausted its credit during verification.
TIP-027.3 live enterprise connectors and TIP-027.4 federated Research answers
remain explicit follow-on work; they are not represented as complete.

## COMPLETED OUTPUTS

### 1. Enterprise source inventory and trust zones

- Added a machine-readable source catalog that separates discovery inventory,
  active company SOT, approved private documents and labelled Research.
- Recorded source fingerprints, classification counts, ACL roles, admission
  gates and remaining blockers.
- Added a domain-stratified enterprise evaluation suite covering company,
  products, capability, projects, CRM/MRP operations, market/manufacturer and
  noisy ordinary Vietnamese questions.

### 2. TheSkyWatch Research adapter

- Built a deterministic adapter from the normalized TheSkyWatch registry into
  the existing Research package contract.
- Preserved field values, source tiers, confidence, upstream locators,
  evidence spans and corroboration state.
- Excluded null/unverified fields and unpublished/sample editorial content.
- Added fingerprint/tamper checks, parser compatibility and idempotence tests.
- Activated 1,838 labelled Research records with 8,162 admitted fields from
  518 UAV variants, 296 manufacturers and 68 published articles.

### 3. Approved company-document onboarding

- Added a dry-run-first, checksum-bound campaign for 13 current company files:
  three project documents, one project-control guide, seven CRM process/forms
  and two MRP operating/maturity documents.
- Enforced owner, checksum, current version, viewer-ready rendition,
  classification, source zone and role ACL before activation.
- Activated 12 internal documents for staff/leader/curator/admin and one
  restricted document for leader/curator.
- Default Ask now has 219 SOT chunks plus 3,866 approved file chunks from 43
  current documents: 4,085 company-searchable units in total.

### 4. Office extraction and provenance hygiene

- Upgraded structured DOCX extraction to preserve Vietnamese text and tables.
- Reprocessed the affected Office corpus with pipeline v4.
- Superseded prior rendition resources; retrieval counts only chunks whose
  rendition resource remains active.
- Kept original file/version/checksum/rendition provenance and document ACL.

### 5. General enterprise-query reliability

- Locked explicit deterministic intents so an external LLM can enrich an
  ambiguous lookup but cannot rewrite a clear procedure into a catalog query.
- Separated company scope/context from the canonical subject that must appear
  in the answer.
- Bound workflow rows to their governed document identity for relevance.
- Ranked process/procedure documents above adjacent forms for procedure intent.
- Reserved the complete numbered workflow from the strongest governing
  document before fusion padding, preventing intermediate steps from vanishing.
- Required the final grounded answer to name the confirmed canonical subject.
- Made curator-bound entity evidence the retrieval boundary for non-procedure
  questions, while retaining broad recall for genuinely open questions.
- Added governed maintenance-program aliases, technology-stack point lookup,
  direct-verdict guidance for enterprise yes/no questions and a narrow
  structural-heading allowlist that does not exempt factual claims from
  citation requirements.
- Added ontology profile facets as a scalable attribute index. HERA now routes
  battery, commercial, maintenance, warranty and naming lookups to curated
  records; company questions route identity, brand, contact, positioning,
  leadership and recognition independently.
- Changed independent LLM review from an availability veto to an internal audit
  signal. Deterministic citation, evidence-overlap, entity relevance, profile
  coverage and governed-collection coverage remain mandatory before grounding.
- Replaced the brittle “entity must occur in the first four words” answer gate
  with a bounded first entity-bearing-clause check that still rejects an
  adjacent product named as the primary subject.

### 6. Reproducible runtime and QA harness

- Runtime refresh now rebuilds and recreates API, worker and web together so a
  source change cannot be tested against stale images or mismatched build SHAs.
- Runtime verification retries startup health and checks both operational API
  readiness and the browser-facing status route.
- Local CI now uses an isolated backend environment, the full repository mount,
  production-compatible Vietnamese fonts and the Next standalone server.
- Full hermetic results: backend 555 passed / 127 conditional skips; integration
  68 passed; web 182 passed; browser/accessibility/responsive 125 passed; Ruff,
  mypy, ESLint, TypeScript and production build all pass.

## MAIN FILES

- `v2/apps/backend/src/rtr_copilot/enterprise_corpus/`
- `v2/apps/backend/src/rtr_copilot/commands/build_enterprise_corpus.py`
- `v2/apps/backend/src/rtr_copilot/commands/onboard_company_files.py`
- `v2/apps/backend/src/rtr_copilot/commands/activate_company_corpus.py`
- `v2/apps/backend/src/rtr_copilot/ingestion/extractors.py`
- `v2/apps/backend/src/rtr_copilot/commands/rerender_stale_office.py`
- `v2/apps/backend/src/rtr_copilot/rag/query_understanding.py`
- `v2/apps/backend/src/rtr_copilot/rag/relevance.py`
- `v2/apps/backend/src/rtr_copilot/rag/retrieval.py`
- `v2/apps/backend/src/rtr_copilot/rag/answering.py`
- `v2/eval/enterprise_corpus/`

## DEVIATIONS AND JUDGMENT

- The original plan kept all project/CRM/MRP material inventory-only. Approved
  immutable document snapshots were admitted because the existing resource
  lineage, checksum, viewer and ACL gates provide a safe useful path without
  granting direct access to live transaction databases.
- TheSkyWatch remains Research. No automatic promotion into company SOT was
  added, even though its data volume is substantially larger.
- No direct CRM, MRP, IP or HRM database connector was introduced. Those
  require owner-approved field/row policy, freshness and deletion contracts.

## REMAINING WORK

- Restore provider credit, first rerun the five targeted regressions (HERA,
  SkyWatch 360, The Sky Watch, approved origin response and company recognition),
  then rerun the complete 77-case enterprise campaign. The latest complete run
  was 71/77 with 0 false-grounded, 91.4% grounded success, 92.9% citation
  accuracy and 60.51 s p95; its five live browser scenarios passed. The final
  reviewer/relevance/company-facet remediation is hermetically verified but not
  yet live-certified.
- TIP-027.3: read-only connectors for live CRM, MRP and IP; authoritative HRM
  source discovery; field/row ACL, freshness SLA and deletion propagation.
- TIP-027.4: federated Ask routing and answer composition across SOT/private
  company evidence and visibly labelled Research.
- Expand approved project/capability manifests beyond the first 13 documents.

## DELIVERY STATE

Implemented and hermetically verified in the local workspace. Release status is
**CONDITIONAL / NOT FINAL READY** until the external-provider balance is restored
and the complete live E2E gates pass. Changes are not committed or pushed by
this report.
