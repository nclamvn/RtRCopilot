# COMPLETION REPORT — TIP-034

**STATUS:** IMPLEMENTED LOCALLY / PILOT NOT STARTED. The immutable campaign,
provenance evaluator, operator commands and anti-gaming regressions are complete.
No internal question or evidence was sent to an external LLM in this work session.

## Files changed

- Created `enterprise_corpus/pilot_campaign.py`: strict campaign/ledger models,
  source-suite validation, report binding, stratification gates and shared
  scorecard evaluation.
- Created `commands/evaluate_pilot_campaign.py`: content-free definition and
  final-evaluation command.
- Created `tests/test_pilot_campaign.py`: GO, cherry-pick, duplicate, digest,
  timestamp and runtime-build regressions.
- Created `eval/pilot/tip034_campaign.json`: immutable 27-case, seven-domain
  campaign selected from the governed real-world suite.
- Created `eval/pilot/tip034_observations.json`: honest empty ledger.
- Created `eval/pilot/tip034_campaign_result.json`: honest `not_started` result.
- Created `scripts/run-tip034-pilot-capture.sh`: exact-scope live wrapper with
  explicit external-processing gate.
- Modified `eval/run_real_world_acceptance.py`: future HTTP reports now include
  the runtime build identity returned by the application.
- Modified `Makefile`: added definition check, live capture and final evaluator
  targets.

## Verification results

- Focused campaign/scorecard/oracle suite: 27/27 PASS.
- Full backend: 635 PASS, 128 conditional SKIP.
- Ruff: PASS.
- mypy strict: PASS on 141 source files.
- Production-image `make pilot-campaign-check`: PASS; verdict `not_started`,
  sample 0.
- Refreshed local runtime: build `5c4049d17cd9+90cb5f148fbe`, provider
  external, OpenAI embedding 1536, routine reasoning low, grounded answering
  ready; UI status operational.
- External guard: PASS — exits 2 before network when approval is absent.
- `git diff --check`: PASS.

## Issues discovered

- The prior 77-turn E2E suite is broad enough for selection, but its reports did
  not identify the exact running build. That gap is now closed for future HTTP
  runs.
- The TIP-032 scorecard accepted manually entered technical fields. TIP-034 now
  derives citations, honest-null, false-grounded and latency from the bound E2E
  report.
- There is still no real pilot evidence. A green unit suite proves the campaign
  machinery, not employee usefulness.

## Deviations

- The minimum was strengthened from 20 observations to all 27 immutable cases.
- Live pilot capture was not run because the current instruction did not provide
  a new purpose-bound approval for exporting this larger internal campaign.
- TIP-033 recertification was not silently folded into TIP-034; the two scopes
  remain independently auditable.

## Next operator action

1. Obtain explicit approval for the exact 27-case manifest and configured LLM
   endpoint.
2. Run `TIP034_APPROVE_EXTERNAL=1 make tip034-pilot-capture`.
3. Have internal testers complete usefulness, clarification, authorization and
   cost attestations.
4. Run `make pilot-campaign-evaluate`; only a `go` verdict may advance the pilot.
