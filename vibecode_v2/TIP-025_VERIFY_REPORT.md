# TIP-025 Verify Report

**Date:** 2026-08-04
**Verdict:** PASS

## Automated gates

| Gate | Result |
|---|---:|
| Alembic chain + up/down revision fixtures | 12 / 12 PASS |
| Backend hermetic | 449 passed, 119 skipped |
| Data integration | 61 passed |
| Web unit/contracts | 169 passed |
| Browser, accessibility, responsive | 105 / 105 passed |
| Runtime denial probes | 27 / 27 denied as designed |
| Ruff | PASS |
| mypy strict (120 modules) | PASS |
| ESLint | PASS |
| TypeScript | PASS |
| Next.js production build | PASS |
| API/worker/web runtime health | PASS |

## Enterprise trust probes

| Probe | Expected | Result |
|---|---|---:|
| Curator self-approves a domain | separation-of-duties denial | PASS |
| Research source fingerprint matches | manifest validates | PASS |
| Evaluation includes query/retrieval/answer per domain | suite accepted | PASS |
| Approved LLM configuration absent | run is `incomplete` | PASS |
| Attempt release from incomplete run | release denied | PASS |
| Matching certified passed run | attestation + activation | PASS |
| Ask runtime reads active DB ontology | exact digest match | PASS |
| Source later suspended/drifted | readiness false | PASS |
| Runtime mutates evaluation history | privilege denial | PASS |
| DB owner mutates evaluation history | immutable trigger denial | PASS |
| Anonymous calls enterprise readiness | typed 401 | PASS |

## R/M/E review

### Risk

- No live corpus was silently onboarded.
- No LLM can approve fingerprints, ontology state, evaluation results or releases.
- No missing-provider fallback can create a passing answer-quality gate.
- One active ontology prevents nondeterministic selection between registries.

### Maintenance

- Domain expansion is data/configuration, not product-specific code.
- Corpus manifests reuse current SOT/Research fingerprints.
- Evaluation contracts are typed and immutable; release identity is digest-bound.
- Schema, restore and runtime-grant gates include the new ledgers.

### Edge cases

- Duplicate source and case identities fail validation.
- Unknown/inactive/drifted sources fail closed.
- Alias collisions require clarification coverage.
- Stale corpus, mismatched suite/run/revision and incomplete quality configuration
  all block activation.
- Packaged ontology fallback occurs only when there is no active revision; a DB
  failure is not concealed by fallback.

## Runtime state after verification

- UI: `http://127.0.0.1:3000/ask`
- Backend schema: `0012_enterprise_governance`
- Seven containers healthy.
- Grounded-answer capability remains `configuration_required` until the approved
  LLM credential and external-processing policy are supplied.
- No real TIP-025 release is active yet; Ask therefore uses the packaged bootstrap
  ontology while preserving all existing TIP-024.7 trust gates.
