# R22 — Independent offline diagnosis review

2026-10-09 · Reviewer `/root/r13_checkout_scan` · Vibecode Kit v6.2.

Verdict: **ACCEPT scoped offline diagnosis and conditional next-design recommendation**. No measured root cause or product repair is established. R21 qualification remains FAIL/P1; EXE-009 OPEN, candidate NOT_READY, serving executor OFF, TIP-054.5 BLOCKED. No new capture or implementation is authorized by this review.

## Independent evidence checks

Read the full TIP, frozen analyzer/control sources, SCAN/source map, Completion, complete R21 journal/final JSON/logs and Main records. Independently reconstructed with read-only stdlib arithmetic/parsing; did not import or execute analyzer/helpers/product/tests, SQL, Docker, signals, providers or Git. Only this new report was written.

Input binding SHA256 `1ae53ce15d2bab4f76df11dd9297640cda2e6af9477b116fd7664d78104e93ab`: deduplicated linked union **1,722 pins / 13,274,883 bytes**, independently rehashed with no mismatch, below32MiB. Current complete product204/tests192 inventory sets and declared content digests match; R21 source/raw/markers and downstream closure/Verify/review/publication-check bytes remain intact. Linked counts are not additional unique tests. Initial binding/output/feedback remain separate from final author state; no invented prior code snapshot is claimed.

Independently reproduced **every analysis field**, including16 nearest-rank cells/cohorts, exact failed/missing case IDs, ordinal-bin counts, deterministic worst-five selection, server distributions, paired response-boundary distributions, threshold counters and preservation/cap metadata. Analysis SHA256 `d54c7c9cfb028e02212475f6244c9a65cced2ad2bd5f5586ca3202abdebd869d`, **30,897 bytes**, below128KiB. Main analysis is byte-identical; all shared Main independent reconstruction fields agree.

Conservation remains1,600 requested /1,440 unique observed /1,353 successful /87 HTTP503 `action_operation_timeout` /160 missing /10-of-16 passing cells. All1,440 middleware IDs/statuses match uniquely. Missing slots are exactly status/cancel descendants of80 failed concurrency50 submits. C25 cancel failures70/72/74; c50 status31; cancel14/31/33. C50 submit failure bins over case IDs0–19…80–99 are19/18/19/17/7, not measured time windows. C50 status/cancel20-sample quantiles never certify missing populations; failures remain in all distributions.

Distinct predicates matter: c25 admission79 and c50 admission97 observations exceed500ms; c50 submit67 exceed1000ms yet80 are timeout outcomes; c25 submit3 exceed900ms with zero errors. Endpoint/client timers cannot identify where .9s was spent or subtract an alleged pool/audit overhead. No absolute request starts or internal phase timestamps exist.

## Source and design assessment

The source map is materially correct, with these required distinctions:

- Admission `actions/api.py:103–113` has no executor .9 timeout. Execution `execution_api.py:25–40` starts timeout after dependency resolution. Client `latency_probe.py:54–65` wraps request completion and stops before JSON decode/retention; middleware `api/main.py:88–113` ends at its response-return boundary and rounds durations.
- Eligible admission/submit have two physical leases and three fresh logical phases (`service.py:546–699`; `execution.py:160–259`; `request_connection.py:563–635`). Retained mutation carrier is transaction-free; post-commit authority/disclosure is fresh, not a reusable permission cache. Exact R21 fallback frequency/counts are unobserved.
- Standard status nominal3 explicit application SQL/1 checkout; queued cancel10/4 (`execution.py:97–113,331–409`, `policy.py:122–127`, `db/uow.py:14–34`). Excludes driver/pre-ping/transaction protocol. Cancel uses ordinary contexts, not RequestConnection terminal machinery, and does not append audit. Initial owner-read Session fusion alone would preserve10 SQL and reduce4→3 checkouts, not invent9 SQL.
- Audit fence precedes the new post-wait checkpoint (`service.py:330–352`); repository107–140 and migration0004:97–104 reacquire the same transaction lock/anchor. Reentrancy is not three independent waits. Cleanup joins/shields do not imply COMMIT acknowledgement is shielded or replay-safe (`request_connection.py:348–381,399–428`).

Four options are compared; minimal experiment-only phase attribution is the justified next **design**, while cancel fusion and audit reduction remain unmeasured alternatives. Selected design must leave identity-gated `ActionPolicy.current`, exact service/factory origin/options and status admission untouched (`execution.py:349–386`); prove original status3/1 and queued cancel10/4 topology. Preserve actor/source/ACL freshness after waits, atomic audit/idempotency, commit/final-read separation, exact generation ownership, cancellation/error propagation and restoration/default-OFF fallback. Acquisition includes pre-ping/physical connection/scheduling, not pure queue; nested spans need unions/residuals, not inclusive summation. Existing regression sources are witnesses only, not fresh R22 runs.

Future64-record ceiling is **not**10MiB fit proof. Main's downstream decision must require exact worst-case serialized aggregate, including framing/IDs and reserved original stderr/output (proposed2MiB). A proposed32 records/request×128B is only a candidate schema budget until essential complete entry/exit/error/cancel pairs fit; no dropping failed/incomplete pairs to meet cap. No timeout/pool increase or admission500ms abort qualifies as an SLA fix: fast503 still violates zero-errors/full100. New TIP/source/transparency controls and explicit allowance precede any capture.

## Health, limitations and disposition

Builder final five unique pure controls PASS0.047s, two-source syntax PASS, analyzer0; Main same five PASS0.048s, syntax/import-surface2PASS and analyzer0. Earlier same-five0.061s is overlap. Main actual feedback SHA256 `eb144eda63169d944a4d0711c5b507ce5101171aa619b04b46e9782d065249b2`; reproduction check `5880765f66d48ce14639d477546fe3fd02513faf8e85165caaf4a26d2f6d9869`. No new broad build/types/lint/runtime proof; Ruff unavailable and not installed. No Docker operation/cleanup was needed.

Nonblocking review notes: SCAN's timer citation60–65 should be54–65. Pure log parser treats whitespace-prefixed JSON as non-JSON; its standalone control seam would not reject a whitespace-prefixed duplicate. Current sealed raw has none, and changed raw fails pin verification before analysis, so current results remain accepted. A future arbitrary-log observer parser must not inherit that leniency. Reviewer's first independent inline arithmetic had a syntax typo before execution, corrected read-only; no source/raw/workload retry.

R22-001…005 supported; independent review/reproduction part of006 supported. Main owns final quantified Verify/seal/current-status publication to close006. Accept diagnostic closure once those downstream artifacts are recorded; never translate this into R21 SLA success, EXE-009 closure or permission for R23.
