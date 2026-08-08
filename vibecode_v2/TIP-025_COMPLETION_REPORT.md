# TIP-025 Completion Report

**Milestone:** Enterprise Corpus Onboarding, Ontology Governance &
Domain-stratified Evaluation
**Completed:** 2026-08-04
**Implementation state:** Code complete; live enterprise onboarding awaits
approved Curator/Leader identities and LLM external-processing configuration.

## Outcome

TIP-025 turns the general query-intelligence work of TIP-024.7 into an enterprise
operating system. It does not add HERA/VEGA-specific fixes. It adds a governed,
domain-neutral route for any future policy, customer, project, HR, MRP, CRM, IP,
industry or partner corpus.

The release chain is now:

```text
active SOT / imported Research fingerprints
                  ↓
approved domain + active corpus manifest
                  ↓
approved ontology + approved stratified suite
                  ↓
immutable evaluation run (query / retrieval / answer)
                  ↓
Leader activation + cryptographic release attestation
                  ↓
Ask consumes the active ontology at runtime
```

## Delivered

1. **Enterprise domain governance**
   - Stable domain key, accountable owner, classification and minimum case count.
   - Curator proposal and distinct Leader approval.
   - No automatic owners/domains from scraped text.

2. **Fingerprint-bound corpus onboarding**
   - Manifests reference existing SOT or Research authorities; no third truth zone.
   - Exact source fingerprint validation and canonical snapshot digest.
   - Unknown, inactive or drifted sources fail closed.

3. **Ontology revision ledger**
   - Strict TIP-024.7 `OntologySpec`, immutable digest and revision history.
   - One global active enterprise ontology at a time.
   - Deliberate alias collisions require an explicit ambiguity/clarification case.
   - Ask loads the active DB revision without image rebuild.

4. **Domain-stratified quality evaluation**
   - Immutable suites and runs.
   - Every active domain must meet its minimum, contain a critical case and cover
     query, ACL-filtered retrieval and real grounded AnswerService behavior.
   - Missing approved LLM configuration yields `incomplete`; it cannot pass by
     silently switching to a weaker answer path.

5. **Release and readiness**
   - Attestation digest binds ontology + current corpus + suite + evaluation result.
   - Activation requires an approved matching suite and passed current-corpus run.
   - Later source drift immediately changes readiness to false.

6. **Security and operability**
   - Curator/Leader policy checks and separation of duties on all decisions.
   - Audit stores ledger ids/counts/digests/decisions, not question or evidence text.
   - Database triggers preserve immutable history; runtime grants deny mutation of
     evaluation history and deletion across all six ledgers.
   - Full ontology payload is restricted to Curator/Leader roles.
   - 13 typed backend routes and a bounded same-origin `enterprise` proxy family.

## Principal implementation files

- `v2/apps/backend/migrations/versions/0012_enterprise_governance.py`
- `v2/apps/backend/src/rtr_copilot/enterprise/models.py`
- `v2/apps/backend/src/rtr_copilot/enterprise/repository.py`
- `v2/apps/backend/src/rtr_copilot/enterprise/service.py`
- `v2/apps/backend/src/rtr_copilot/enterprise/api.py`
- `v2/apps/backend/src/rtr_copilot/rag/ontology.py`
- `v2/apps/backend/src/rtr_copilot/rag/answering.py`
- `v2/apps/backend/tests/test_enterprise_governance_unit.py`
- `v2/apps/backend/tests/test_enterprise_governance_integration.py`
- `v2/apps/web/src/app/api/governance/[[...path]]/route.ts`

## Acceptance status

All 12 acceptance criteria are implemented and exercised. The integration proof
uses non-product `policy` data, verifies separation of duties, unavailable-LLM
incomplete behavior, release denial, certified-pass activation, runtime ontology
loading, source-drift invalidation, database trigger immutability and runtime
privilege denial.

## Deliberately not performed

- No live company domain, manifest, ontology or evaluation suite was created.
- No owner, Curator or Leader role was invented or assigned.
- No LLM credential or external-processing approval was assumed.
- No commit or push was performed.

These are governance/operational actions, not implementation gaps.
