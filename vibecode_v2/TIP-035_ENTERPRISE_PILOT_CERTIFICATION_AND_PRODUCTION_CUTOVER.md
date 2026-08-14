# TIP-035 — Enterprise Pilot Certification & Production Cutover

**Status:** Implemented locally · release not yet certified
**Date:** 12/08/2026
**Priority:** P0
**Depends on:** TIP-033, TIP-034
**Owner:** RtR Copilot
**Method:** Vibecode Kit v6.1 — Contractor / Builder / Homeowner

## 1. Objective

Convert the current feature-complete local product into an auditable enterprise
pilot release, then promote only the certified core to a staged company rollout.
The target is a useful internal Copilot — Ask, Files, Documents and governed
SOT/research — on one exact build, with measured quality, latency, security,
rollback and operational ownership.

This TIP does not call a local development stack “production” and does not let a
large green unit-test count substitute for real employee usefulness evidence.

## 2. Release decision

### Included in the first company release

- Grounded Ask and multi-turn conversation.
- Evidence/provenance rail and honest-null behavior.
- Governed internal Files and Documents workspaces.
- Canonical company SOT plus approved research corpus.
- Corporate OIDC, authorization, audit, backup, restore and rollback controls.

### Feature-off until independently certified

- CRM, MRP and IP connectors remain `contract_ready`, not active.
- HRM remains blocked until its authoritative repository and owner are confirmed.
- No connector may be activated merely because its source repository is visible.
- External research ingestion beyond the governed corpus remains a separate
  onboarding and policy decision.

The rollout sequence after the core is stable is CRM → MRP → IP → HRM, with one
canary, owner, credential boundary, freshness SLA and rollback decision per
connector.

## 3. Requirements

| ID | Requirement |
|---|---|
| REQ-035-01 | The candidate runtime must report the exact clean committed build; stale or dirty build identity blocks release. |
| REQ-035-02 | TIP-033 must pass its immutable five-case live recertification: 5/5, false-grounded 0, citation accuracy 1.0, p95 ≤ 25 s and max < 45 s. |
| REQ-035-03 | TIP-034 must complete all 27 immutable cases and satisfy usefulness, clarification, citation, honest-null, authorization, latency and cost gates. |
| REQ-035-04 | The pilot database must be isolated, contain at least 219 canonical active records, contain no non-canonical active SOT source and have zero active enterprise connectors. |
| REQ-035-05 | Production configuration must pass the application fail-closed validator with HTTPS public/OIDC endpoints, corporate identity, secure cookies and non-default separated secrets. |
| REQ-035-06 | Hardened ingress, migration gate, load/SLO probe, backup/restore and versioned rollback must pass on the target deployment. |
| REQ-035-07 | Release scope is the certified core only; connector feature activation is denied by default. |
| REQ-035-08 | Rollout uses three explicit cohorts: 5–10 champions, 20–30 cross-functional users, then company-wide, with stop/rollback criteria at every transition. |
| REQ-035-09 | Reports may contain digests, counts, timings and verdicts, but never credentials, prompts, answer plaintext or evidence plaintext. |
| REQ-035-10 | No P0/P1 defect is open and the Homeowner records an explicit GO before production cutover. |

## 4. Acceptance criteria

| ID | Gate |
|---|---|
| AC-01 | Runtime verifier and UI status agree on the clean Git build identity. |
| AC-02 | TIP-033 has a fresh passing report bound to that same build. |
| AC-03 | TIP-034 has 27/27 bound observations and a final `go` verdict. |
| AC-04 | Isolated pilot database verifier passes all SOT and connector invariants. |
| AC-05 | Production configuration validation passes without exposing secret values. |
| AC-06 | Hardened deployment and ingress probes pass on the release target. |
| AC-07 | Migration, backup/restore and versioned rollback drills pass and retain their ledgers. |
| AC-08 | Load and SLO probes pass at the agreed pilot concurrency. |
| AC-09 | Cohort owner, support owner, incident path, stop criteria and rollback owner are named. |
| AC-10 | Homeowner signs GO; otherwise the truthful result remains `not_ready`. |

## 5. Purpose-bound external processing

TIP-033 and TIP-034 are separate disclosure purposes. Local validation, runtime
refresh and pilot database creation do not authorize external processing.

- TIP-033 may send only `OPS-010,SYS-007,MTH-004,PRD-001,PRD-023` and the
  evidence required for those cases to the configured approved endpoint.
- TIP-034 may send only its committed immutable 27-case manifest and the
  required evidence to the configured approved endpoint.
- Creating the quality pilot index may export the canonical pilot corpus to the
  configured embedding endpoint and therefore requires the independent
  `PILOT_APPROVE_EXTERNAL_CORPUS=1` purpose gate.
- Approval for one campaign does not authorize the other.

## 6. Staged rollout and stop conditions

### Cohort A — 5–10 champions

Run for two working days across product, operations, commercial and leadership.
Stop on any authorization leak, false-grounded answer, unavailable core journey,
or repeated p95 breach.

### Cohort B — 20–30 cross-functional users

Advance only after Cohort A incidents are closed and the scorecard remains GO.
Measure task usefulness, clarification recovery, support load and cost per answer.

### Cohort C — company-wide core

Advance only with stable SLOs, named support coverage, successful backup/restore
and a tested rollback. Connector activation is not bundled into this transition.

## 7. Verification ladder

1. Static and contract checks.
2. Exact-build local runtime verification.
3. Isolated canonical pilot database verification.
4. TIP-033 live latency recertification after its explicit approval.
5. TIP-034 live capture and human usefulness ledger after its explicit approval.
6. Production configuration and hardened deployment preflight.
7. Load/SLO, backup/restore and rollback drills on the target environment.
8. Homeowner GO/NO-GO review.

## 8. Rollback

- Before production cutover: stop; keep the current production state unchanged.
- During a cohort: disable new access, retain evidence/incident ledgers and use
  the versioned rollback target.
- Never auto-downgrade the database schema; schema rollback is a separate
  reviewed decision.
- Never discard a failed live campaign or human observation to improve a later
  score.

## 9. Decision log

- The Homeowner approved implementation of the proposed TIP-035 sequence.
- The approved implementation scope covers local gates, runtime synchronization,
  isolated pilot preparation and release preflight.
- No new architecture was introduced; this TIP assembles existing production,
  campaign and rollback controls into one fail-loud cutover contract.
- The general instruction to implement does not replace the purpose-bound
  approvals required by TIP-033 and TIP-034.

## 10. Current truthful status

`NOT READY` until all acceptance criteria are evidenced. The local candidate
runtime is exact and operational, the migration graph and connector boundary
pass, and all automated code/UI gates are green. The current preflight remains
blocked by the uncommitted candidate, absent isolated pilot, unrun TIP-033,
zero-observation TIP-034, absent production environment, absent target drills
and absent Homeowner GO. Each blocker is independently sufficient to stop the
release.

## 11. Governance amendment — TIP-035.12

On 14/08/2026 the Homeowner authorized an AI-surrogate operator campaign to
replace the manual pre-release tester step. AC-03 may therefore be satisfied by
either:

1. the original governed human observation ledger with a 27-case `go`; or
2. an exact-build TIP-035.12 result combining the real TIP-034 technical
   capture and 27-case persona browser E2E, with
   `TIP035_AI_SURROGATE_APPROVED=1` set for the cutover session.

The second path must say `human_usefulness_measured=false`, preserve the human
ledger, record residual risk and execute zero external calls. It is an explicit
Homeowner risk acceptance, not a human attestation. Production configuration,
target operational drills, cohort stop/rollback controls and final Homeowner GO
remain mandatory and cannot be bypassed by the surrogate result.

## 12. Local remediation note — TIP-035.13

On 14/08/2026, `CHAT-004-T1` from the build-bound TIP-034 capture was traced to
answer-shape variance: a natural draft named the already-planned company scope
but omitted the canonical CRM subject label, disabling the existing local
stabilizer and ending in `called_answer_irrelevant`. TIP-035.13 corrects the
generic query-plan invariant while retaining marker-to-record proof, grounding,
authorization, DLP and foreign-entity rejection.

The remediation is locally verified only. It does not alter the historical
campaign evidence and does not satisfy an exact-build gate until committed,
rebuilt and bound to a new candidate. Any external recertification on that new
candidate requires a new purpose-bound approval.

## 13. Release recovery amendment — TIP-035.14

The release recovery drill found that restore validation treated private-file
citations as canonical SOT citations and that historical disposable uploads
had left some `available` object metadata without physical bytes. TIP-035.14
adds provenance-aware citation verification, manifest-v2 private-chunk
attestation and an explicit maintenance-only quarantine workflow. The
remediation must be committed and rebuilt before release certifications can be
renewed for the resulting exact candidate.
