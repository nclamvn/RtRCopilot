# Public enterprise-OS research cohort

Frozen primary-source documentation for 24 explicitly selected topics, captured
2026-10-06 UTC. The cohort denominator is 24 topics, not vendors, products, the
global market, or a completeness/performance score. All 24 requested pages yielded
usable evidence, with OpenTelemetry accepted only as a migration notice.

64 authored claims: category 24, capability 23, constraint 17. Values are short
paraphrases; exact raw evidence uses at most 24 words/page and 3 claims/page.
Category is an analyst taxonomy grounded in the named documentation topic.
Primary tier A means the provider/standards body describes its own material, not
independent efficacy validation. All 64 populated cells are sourced, not corroborated.
56 cells are honest-null, including all 24 performance_rtr and 24 license_rtr cells.
Verification currently passes 7/7 applicable Refinery bites (7 explicit N/A) and
11/11 independent tests (one positive control plus ten adversarial checks).

## Offline reproduction

Requires Python 3.10+ and PyYAML (available in the current environment). No requests,
HTML-parser package, network, API key, LLM, or embeddings needed for verification.
From this directory:

```sh
python3 research.py claims
python3 research.py verify
python3 research.py rebuild
python3 test_verifier.py
```

`claims` rebinds human-authored `claims-spec.json` to frozen capture metadata;
it does not invent extraction. `rebuild` runs the unmodified vendored engine,
its deterministic two-build check, auditor, and adversarial bites. Independent
verification checks exact UTF-8 raw spans (stricter than the engine's HTML-entity
normalization), raw/view SHA256, read-view regeneration, fixed cohort/schema,
capture origin, source-family identity, and quotation/claim budgets.

`output/registry.json`, `engine-verification.json`, `independent-verification.json`,
`independent-negative-tests.json`, `bites.txt`, `honest-null-log.json`,
`missing-entity-log.json` and `dead-link-log.json` are machine-readable audit outputs
(except the human-readable bites log). `captures/` holds per-page attempt ledgers;
`snapshots/` retains raw HTML bytes; `read_views/` is a separate derived reading aid.
Both views have one origin and must never count as independent corroboration.
`vendor/origin.json` records engine origin and expected hashes.

## Capture policy

```sh
python3 research.py capture
python3 research.py capture --retry-failed
```

Capture is restricted to the fixed manifest; <=3,000,000 bytes/page, 25-second
request timeout, <=4 concurrent requests. Redirects are limited to HTTPS hosts
already declared by the manifest. Selected snapshots are never refetched or
overwritten by these commands. A refresh should be a separately reviewed new
dataset, not mutation of this frozen cohort. Failed attempts remain in ledgers.
Initial sandbox DNS failures were retried with authorized public read-only network
access. `dead-link-log.json` is an attempt-failure log: DNS/network failures do not
establish that a public URL is dead. A successful HTTP response alone is insufficient: short/error/navigation
captures are rejected. One explicitly recognized short OTel migration notice is
accepted for its migration constraint only, never for a capability assertion.

## Decision limits

- Live documentation is not a pinned SDK/API compatibility matrix; compatibility
  with RtR's installed dependencies is unmeasured. No installation/runtime tests.
- Vendor durability statements do not establish exactly-once external API effects.
  DBOS distinguishes transaction commits from at-least-once step attempts;
  integrations still need separate idempotency/reconciliation design review.
- MCP optional authorization does not establish deployment protection. Annotations
  are not authorization. LangGraph resumed nodes may replay pre-interrupt effects.
- Microsoft functional workflows are explicitly experimental. Microsoft pages
  displayed a generic authorization banner but still returned substantial public
  article bodies; no authentication or private-source access was used.
- Pydantic durability is distinct from storing conversations. The short cohort
  extraction is not an exhaustive list of backend integrations or guarantees.
- OTel's captured page points to a moved specification. Its destination repository
  is not captured/evaluated here; current convention stability remains unmeasured.
- Source hashes show frozen-byte integrity, not truth or completeness of source
  prose. Human semantic review of each paraphrase/span remains necessary.
- Refinery's auditor checks entity set/aggregates and shares some builder functions;
  it is not a fully independent semantic auditor. The separate verifier and its
  mutation tests provide byte/origin/budget checks, not semantic proof.

TIP and Completion Report preserve the Vibecode audit trail. Refinery's exact
evidence and honest-null rules shaped the dataset; optional Jev seam remains OFF.
