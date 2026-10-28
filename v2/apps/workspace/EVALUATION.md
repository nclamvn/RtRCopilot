# AW-04 evaluation: useful output, not mock theatre

Status on 2026-10-28: offline guard/comparator contracts tested. **Real-model
quality, real provider latency/cost, user productivity and human acceptance are
NOT MEASURED.** No provider request, smoke, model listing, live search or account
connector is part of this evidence. A $10 total is a proposal until approved.

## Inputs and method

`tests/fixtures/aw04/campaign.json` contains twelve assistant-authored synthetic
journeys in two invented domains: a community garden and a makerspace. There is
no RtR data. Six development and six holdout assignments are frozen together with
source/case fingerprints in `manifest.json`, before provider results. Builders
can inspect these assignments: this is not a hidden independent benchmark.

The development split mostly contains content tasks; the holdout split mostly
contains operational faults. Do not compare their averages as a generalization
claim. Report individual outcomes and preserve failed cases/artifacts. Reusing
these inputs to repair a failure makes them development evidence; a later
generalization claim requires newly frozen variants, not cherry-picking.

The smallest meaningful comparator is a **direct tool-enabled agent**, not a
bare LLM. It uses the same PydanticAI/provider adapter, model/settings, source
parsers, file/artifact/memory/research/connection tool ports and per-run limits.
It does not use DBOS, Workspace UI, persistent agent history or automatic restart
recovery. The deterministic Store is deliberately shared for equal artifact
version/policy semantics; that is not a second durable agent runner. A pending
effect returns an approval receipt rather than duplicating Workspace's native
durable approval wait. Thus effects/recovery comparisons require operational
tests, not prose-quality scores. No special source answers enter production code.

L2 method clarification: code proves deterministic controls; a real model proves
language behavior. Cases AW04-10/11 (cancel/effect and forged approval/revocation)
do not need paid model calls to prove authority. The optional capture therefore
requires `--semantic-capture-only`, keeps all twelve records, skips those two
paid calls, and labels their operational evidence separately. Cases 08/09 may
capture natural language, but that does not inject timeout/429/restart faults.
`evaluation.cli.OPERATION_PROOFS` maps exact existing local tests to each facet.
References themselves are NOT pass receipts. The integrated report records the
actual executions and independent probes. No claim of a twelve-journey live E2E
campaign follows from running this natural-language capture.

## Reproduce the safe offline lane

From `v2/apps/workspace`, using the existing environment:

```sh
.venv/bin/python -m agent_workspace.evaluation.cli
.venv/bin/python -m pytest tests/test_aw04_evaluation.py -q
```

The default CLI validates the frozen manifest and prints a plan plus installed
direct Python dependency/license metadata. It does not read credentials or
construct a provider, regardless of any legacy environment variables. Nothing
starts a paid campaign on import. See the package README for the standalone
doctor/launcher; evaluation does not restart the user's runtime.

## Optional real capture, only after authorization and secure setup

The operator supplies a newly configured private Workspace profile (backend CLI
uses terminal getpass, mode0600) and an authority JSON. Never paste a key into
chat, prompts, shell arguments, browser storage or evidence. No legacy key is
discovered or reused. Authority is a record of actual user approval, not a magic
word or a generated approval. It must name the exact endpoint/model/manifest,
all twelve case IDs, data scope, finite expiry and limits.

Required authority fields (an example with `approved:false` is deliberately
non-executable):

```json
{
  "approved": false,
  "approval_reference": "reference to actual user scope/cost authorization",
  "data_scope": "synthetic-public-non-rtr",
  "endpoint": "https://api.openai.com/v1",
  "model": "openai-responses:gpt-6.1-sol",
  "manifest_digest": "5ac297f530c2a53720b856dbd350e4ea8894b9c5c24b88b36610efed53398667",
  "ledger_path": "/absolute/private/aw04-capture/budget.sqlite",
  "case_ids": ["AW04-01", "AW04-02", "AW04-03", "AW04-04", "AW04-05", "AW04-06", "AW04-07", "AW04-08", "AW04-09", "AW04-10", "AW04-11", "AW04-12"],
  "limit_usd": 10,
  "max_calls": 160,
  "max_input_tokens": 100000,
  "max_output_tokens": 2048,
  "concurrency": 1,
  "repair_rounds": 0,
  "expires_at": 0
}
```

After the relevant decision/setup, the operator can explicitly call:

```sh
.venv/bin/python -m agent_workspace.evaluation.cli --execute --semantic-capture-only \
  --authority /absolute/private/aw04-authority.json \
  --profile /absolute/private/workspace-profile.json \
  --output /absolute/private/aw04-capture
```

This command has **not been run**. It creates isolated synthetic Workspace and
direct-agent catalogues, one shared budget ledger, a start marker and preserved
`capture.json`. It fails closed before provider calls on missing/expired authority,
profile/readiness mismatch or changed corpus. It never loads environment keys.
Only an explicit opt-in profile selects Responses; no provider-hosted tools,
web search, embeddings, model judge, fallback provider or automatic retry exists.

One capture stops on the first execution failure; valid sources, versions and
failure records remain. A started capture directory cannot be replayed even
after lost ACK/restart. Do not remove its start marker or reset the ledger to
obtain a favorable score. Targeted repair is a separate future operator decision
within the same approved global cap, not a hidden retry button in this runner.

## Money and uncertainty

`CampaignBudget` is the SAME optional pre-dispatch interface for Workspace and
the direct comparator. Explicit run binding prevents ordinary Workspace UI
requests spending campaign money. SQLite `BEGIN IMMEDIATE` provides one active
dispatch across both arms using the same ledger. The real CLI requires the
authority to bind the exact absolute ledger path, preventing accidental fresh
output directories from resetting its cap. This is not an account-wide billing
firewall against a trusted operator deliberately issuing a new authority/file.
Any authorized smoke or repair must reuse the SAME existing ledger and original
overall cap; the runner does not offer reset/supersede authorization.
Worst-case input/output/call reservation is durable **before**
dispatch; an uncompleted/unknown request stays reserved and fences further calls
after restart. There is no refund/reset/expiry replay switch. If an operator
closes or supersedes a failed campaign, its historical unknown charge still
counts toward any applicable overall user cap; this code cannot authorize that.

Official [model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
and [pricing](https://developers.openai.com/api/docs/pricing) were fetched on
2026-10-28: Sol tools require Responses. Standard short-context rates are $2/M
input, $10/M output, with up to $5/M for 12h cache writes. This guard conservatively
uses $5/M for all input, does not assume cached discounts, bounds text input at
100k tokens, total reasoning-plus-visible output at2048 and excludes unpriced
tiers/native tools/images. Input reservation uses serialized UTF-8 bytes (one
byte per token) plus 8192 envelope tokens, including tool schemas. Reported usage
over that bound persists a STOP rather than silently exceeding the assumption.
Known settlement is a conservative token-cost estimate, not an invoice. Missing
usage/uncertain transport is not proof of zero charge.

## Quality and measurements

Deterministic rubrics check exact CSV cells, artifact existence, source literals,
word count and localized byte-preserving edits. A number rendered differently
(for example 1,850 versus 1850.00) becomes REVIEW_REQUIRED, not a false critical
failure. These checks do not certify factual context, useful reasoning or prose.
Simulation can only say contract PASS. Real outputs still require separate
semantic review; human acceptance remains NOT_REVIEWED until a person actually
uses/reviews them. No model judges are called to improve scores.

Capture records per-turn wall time, available text/artifact timestamps, requests,
tool calls, usage and conservative reservation/settlement. First text is NOT
first useful output. The latter, usable-artifact time, active human minutes,
manual effort and invoiced dollars remain null unless actually observed. The
direct nonstreaming baseline currently has no first-text measurement; do not
compare its null with Workspace streaming timestamps. Do not infer 0 human
minutes from an automated run. A small sample does not support p99/market claims.

The local ledger/fixture/comparator tests validate wiring, budgets, persistence,
fault stopping and no false semantic certification. The separate integrated
regression/browser/independent evidence validates the referenced controls. Mock
green cannot establish natural-language quality or product advantage over an
agent with the same model/tools.

## Packaging/license boundary

`evaluation.cli` inventories installed direct Python requirements, including the
pinned Responses SDK, with license metadata. The neutral runtime's retained Noto
font license is in `src/agent_workspace/assets/LICENSE-NOTO.txt`. The UI remains
in the existing web package and inherits its legacy dependency scope. This
narrow inventory is not a complete transitive SBOM, attribution distribution or
legal clearance for a standalone commercial product. No deployment is implied.
