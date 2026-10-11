# Completion Report — TIP-RESEARCH-01

STATUS: DONE (bounded public research artifact; not product implementation).

FILES CHANGED: New files only under this research directory: manifest/config,
human-reviewed claim spec and bound JSONL, 24 capture ledgers/raw snapshots/read
views, unmodified vendored engine + origin hashes, capture/rebuild/verifier script,
negative-test script, machine-readable audit outputs, README, TIP and this report.

TEST RESULTS:

- AC-1 PASS: 24/24 requested public pages accepted, including 1 explicit migration
  notice; 3 MB/request bound, 25-second timeout, HTTPS/allowlisted redirect hosts;
  raw bytes and read views separately hashed. Initial DNS failures retained.
- AC-2 PASS: 64 claims, 24 entities; 0 exact-span/hash/origin errors; max 24 quoted
  words/page, <=3 claims/page; no unsupported performance/license claims.
- AC-3 PASS: Refinery deterministic two-build check and auditor; 7/7 applicable
  adversarial bites, positive control; 7 domain-irrelevant gates explicitly N/A.
  Independent test suite 11/11 PASS (1 positive + 10 adversarial checks).
- AC-4 PASS: 24-topic denominator; family collapse across mirrors; 64 sourced,
  0 corroborated, 0 disputed, 56 honest-null cells. Runtime/API compatibility,
  RtR performance, and product licensing are unmeasured.

ISSUES/LIMITS: No pinned SDK compatibility, integration tests, benchmarks, license
validation or claims of complete market coverage. OTel migration destination was
not evaluated. Microsoft generic authorization banners noted; article bodies
were public. Category is analyst taxonomy, not a provider's product classification.
Builder/source-semantic review completed on the short paraphrases; Contractor
review remains separate. A research-scoped
ignore exception keeps public `claims.jsonl` deliverable despite the repository's
global runtime-log JSONL ignore; no runtime ignore or product configuration changed.

DEVIATIONS: Generic short-page filter initially rejected OTel; exact migration
marker was reviewed and explicitly declared, without changing raw bytes or adding
capability claims. Raw HTML evidence sometimes includes short markup because exact
source-byte spans are stricter than cleaned prose. No engine modifications.

SUGGESTIONS: Contractor should review paraphrase semantics and decide architecture
separately. These documentation assertions must not replace failure-injection,
side-effect/idempotency and SDK-version compatibility tests before production.
