# TIP-013 · Migration, Pilot & Final Verify

## HEADER

- **TIP-ID:** TIP-013
- **Project:** RtR Copilot V2
- **Module:** Curator-gated data onboarding, V1 regression parity,
  representative evaluation set, staged pilot, final 34/34 REQ matrix,
  go/no-go decision
- **Depends on:** TIP-001…012 VERIFIED
- **Priority:** P0 (release gate)
- **Status:** ISSUED · phased (automatable phase runs now; real-data phase is
  Homeowner-gated)
- **Working directory:** `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2`
- **Requirements:** the FULL 34/34 REQ matrix (final verification of every
  REQ-ID, not new features)
- **Gate chính (Task Graph):** *34 REQ coverage; zero P0/P1 open; go/no-go
  report. Không chỉ chạy được, mà chứng minh được đúng, an toàn, hữu ích với
  dữ liệu thật.*

## CONTEXT

TIP-013 is not a feature TIP. Eleven TIPs built and hardened the platform on
synthetic fixtures; this one proves it is correct, safe and useful on RtR's
real data, then decides go/no-go. It has two natures that MUST stay separated:

**Phase A — automatable now (no real data, no Homeowner decision):**
the final-verification machinery itself. A code-audited 34/34 REQ coverage
matrix; curator-gated batch-onboarding tooling; a V1-parity harness against the
`phase1_pilot` oracle; a representative evaluation set and scorer — all built
and exercised with SYNTHETIC fixtures. This is real engineering that does not
touch company data and needs no human decision.

**Phase B — Homeowner-gated (cannot be automated, must not be faked):**
the actual cutover. Real Google Workspace OIDC tenant; real TLS certificates;
real SOT/template/KnowledgeBase/research batches curated and classified by
their owners; a real pilot group with real questions; the final go/no-go and
rollback decision. None of this may be fabricated. Phase A produces the
checklist and the decision framework that Phase B executes; Phase A does NOT
onboard real data.

This separation is the whole discipline of the release: **the machine can prove
readiness of the mechanism; only people can authorize the data and the launch.**

## DECISIONS LOG

| ID | Decision | Rationale |
|---|---|---|
| D-013-01 | Phase A ships now on synthetic fixtures; Phase B is a Homeowner-gated checklist, not code the agent runs | Real data/identity/certs are decisions and assets only the Homeowner holds |
| D-013-02 | The 34/34 REQ matrix is audited against ACTUAL code/tests with per-REQ evidence, not asserted from prior reports | Final verify must be independently grounded (X-Ray discipline) |
| D-013-03 | Batch onboarding runs through the EXISTING publish gate and Refinery/graduation gate — no new ingestion path; the tool orchestrates curator-approved batches, it does not bypass any control | TIP-006/010 gates are the safety; a migration tool that sidesteps them is a regression |
| D-013-04 | V1 parity compares V2 answers/citations to the `phase1_pilot` oracle on a fixed question set; divergences are triaged, not auto-accepted | Pilot is the behavioral contract; parity must be measured, not assumed |
| D-013-05 | The evaluation set is representative-by-construction (question types: fact lookup, honest-null, cross-version, ACL-restricted, research-vs-SOT) with synthetic ground truth; real-corpus re-baseline is a Phase-B step | Measure the mechanism now; measure the data later |
| D-013-06 | Go/no-go is a checklist with objective, checkable exit criteria + the five operating metrics; the Homeowner signs it, the agent does not | Launch authority is human |
| D-013-07 | Deferred items inherited through TIP-012 (file-version ask retrieval, DB-pool re-baseline, mc-mirror restore, CSP nonce, real-provider cost) are triaged HERE: each is fix-now, fix-in-pilot, or accept-with-owner | Final verify closes the deferred ledger explicitly |
| D-013-08 | No P0/P1 may be open at go; P2/P3 may be deferred only with a written owner + date | Zero-P0/P1 is the hard gate |

## TASK

### Phase A — automatable (runs now)

#### 1. Final 34/34 REQ coverage matrix (Builder — final X-Ray)
Audit the actual codebase/tests against every REQ-001…034 from
`vibecode_v2/01_SCAN_RRI_REPORT.md` §5. For each REQ: status
(`implemented | partial | deferred`), the concrete evidence (source files,
tests, ACs, gate results), and any gap. Produce
`vibecode_v2/TIP-013_REQ_MATRIX.md` — 34 rows, no "assumed", every claim
traceable to code or a committed gate. Flag every partial/deferred with a
disposition (fix-now / pilot / accept). This is the spine of the go/no-go.

#### 2. Curator-gated batch onboarding tooling (Builder)
A `scripts/onboard-batch.sh` (+ any thin backend command it needs, additive)
that takes a manifest of source items and drives them through the EXISTING
quarantine → publish gate (SOT) or Refinery adapter → graduation gate
(research) — with curator approval as a required step, dry-run by default,
idempotent, fully audited, and refusing to activate anything the gate would
reject. Prove it on synthetic batches: a clean batch onboards; a batch with a
provenance/classification/conflict defect is rejected with a typed, audited
reason and zero partial activation. NO real corpus is onboarded.

#### 3. V1 parity harness (Builder)
A harness that runs a fixed question set against both the `phase1_pilot` oracle
and V2 (synthetic SOT fixtures mirroring the pilot's known facts) and reports
per-question parity: answer agreement, citation presence, honest-null
agreement. Commit the question set + a parity report; triage any synthetic-set
divergence. This is the template Phase B re-runs on the real 137/162 records.

#### 4. Representative evaluation set + scorer (Builder)
`load`-style but for answer quality: a synthetic evaluation set covering fact
lookup, honest-null, cross-version/freshness, ACL-restricted (must refuse),
and research-vs-SOT labeling; a scorer producing grounded-rate,
honest-null-quality, leak count (must be 0), and citation-accuracy. Commit set
+ scorer + a baseline result. Real-corpus re-baseline is Phase B.

#### 5. Deferred-ledger triage (Builder → Contractor)
Take every deferred item from TIP-007…012 verify reports; for each, record
disposition (fix-now with a small in-scope fix / fix-in-pilot / accept with
owner+date). Any cheap, safe, in-scope fix (e.g. `stat -c%s`, mc-mirror
restore loop) MAY be done here; anything touching real data or app semantics
is Phase B or a later TIP.

### Phase B — Homeowner-gated (checklist only; NOT run by the agent)

#### 6. Go/no-go framework + Homeowner decision document (Contractor)
`vibecode_v2/TIP-013_GO_NO_GO.md`: the objective exit criteria (34/34 matrix
green or explicitly-deferred; zero P0/P1; parity acceptable on REAL records;
eval metrics above thresholds on the REAL corpus; drills re-run on the real
deployment; the five operating metrics instrumented), plus the explicit list
of inputs only the Homeowner can supply (real OIDC tenant + allowed domains;
real TLS certs; curated/classified real batches with owners; the pilot group
and their real questions; sign-off authority). The agent fills every row it
can from Phase A; the Homeowner-gated rows are marked `AWAITING HOMEOWNER`.

## ACCEPTANCE CRITERIA

### Phase A (verifiable now)
- **AC-A1** `TIP-013_REQ_MATRIX.md` exists with 34 rows, each carrying a
  status and code/test/gate evidence; no unsupported "implemented" claim (the
  Contractor independently re-checks a sample).
- **AC-A2** Batch-onboarding tool onboards a clean synthetic batch through the
  real gates and rejects a defective one fail-closed, audited, zero partial
  activation; dry-run default; idempotent.
- **AC-A3** V1 parity harness runs the fixed set against oracle + V2 and emits
  a per-question parity report; divergences triaged.
- **AC-A4** Evaluation scorer emits grounded-rate, honest-null-quality,
  leak-count (0), citation-accuracy on the synthetic set; committed baseline.
- **AC-A5** Deferred ledger complete: every TIP-007…012 deferred item has a
  disposition; in-scope safe fixes applied keep all gates green.
- **AC-A6** No regression: backend full suite, web, Playwright, probes,
  compose build, Trivy, data-integration all green (Contractor rerun).

### Phase B (Homeowner-gated — recorded, not executed by the agent)
- **AC-B1** Real batches onboarded by curators; zero unauthorized activation.
- **AC-B2** Parity acceptable on the real 137/162 records.
- **AC-B3** Eval metrics meet thresholds on the representative REAL corpus.
- **AC-B4** Real OIDC tenant + real certs live; hardened drills re-run on the
  real deployment (RPO/RTO, rollback).
- **AC-B5** Staged pilot completed; the five operating metrics collected
  (time-to-evidence, grounded rate, honest-null quality, document cycle time,
  leakage/authorization failures).
- **AC-B6** Go/no-go signed by the Homeowner; zero P0/P1 open; deferred P2/P3
  listed with owner+date; rollback decision recorded.

## OUT OF SCOPE (of the automatable phase)

- Onboarding, indexing or activating ANY real company data, kernel,
  KnowledgeBase, research corpus, MRP/CRM/HRM/IP.
- Real Google Workspace tenant, real certificates, real secrets.
- Running the real pilot or collecting real user metrics.
- Signing the go/no-go (Homeowner authority).
- New product features (forecasting, action integration — post-go-live
  roadmap).

## BUILDER HANDOFF

Phase-A builders work on branch `tip-013`; each must:
1. implement only inside `v2` + `vibecode_v2` evidence; keep kernel/
   KnowledgeBase/GOI/corpora and `phase1_pilot` strictly READ-ONLY (parity
   reads the oracle, never mutates it);
2. use SYNTHETIC fixtures only — no real corpus, ever, in this phase;
3. write `vibecode_v2/_tip013_builder{N}_report.md` mapping Phase-A ACs to
   evidence;
4. keep every existing gate green;
5. leave the working tree uncommitted for Contractor checkpoint.

Contractor independently re-checks a sample of the REQ matrix, reruns gates,
exercises the onboarding/parity/eval tools on synthetic input, writes
`TIP-013_VERIFY_REPORT.md` for Phase A, and produces the Homeowner go/no-go
document for Phase B. **The release is not declared GO by the agent — Phase A
proves the mechanism is ready; the Homeowner authorizes the data and the
launch.**
