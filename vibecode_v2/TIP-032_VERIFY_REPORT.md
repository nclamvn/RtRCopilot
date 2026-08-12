# VERIFY REPORT — TIP-032

**Ngày:** 12/08/2026

**Environment:** Local quality runtime · Docker Compose · `.env.demo`
**Build:** base `7383c80127ae` + content-addressed working-tree identity; final runtime
gate yêu cầu container khớp chính xác identity này.

**Live evidence:** `v2/eval/real_world/tip032_bounded_recertification.json`

## Summary

| Tier | Passed | Failed | Conditional/Pending | Status |
|---|---:|---:|---:|---|
| Core logic/unit | 625 functional + focused final-diff suites | 0 | 128 conditional backend skips | PASS |
| Data integration | 69 | 0 | 0 | PASS |
| Web unit/build | 182 | 0 | 0 | PASS |
| Browser/a11y/responsive | 125 | 0 | 0 | PASS |
| Runtime/build health | 7 services | 0 | 0 | PASS |
| Bounded live quality | 5 | 0 | p95 45.086s > target 25s | PASS QUALITY / DEFER LATENCY |
| Pilot observations | 0 | 0 | minimum 20 stratified observations | NOT STARTED |
| CRM active canary | 0 | 0 | endpoint + credential + enabled lifecycle | BLOCKED SAFE |

## Requirement Traceability

| Requirement | Evidence | Verdict |
|---|---|---|
| REQ-032-01 | Grounding/entity/relevance/coverage/lineage/ACL tests; integration 69/69 | PASS |
| REQ-032-02 | `on_demand` and rollback `always`; call-count unit tests | PASS |
| REQ-032-03 | embedding-start-before-metadata regression; content remains post-ACL | PASS |
| REQ-032-04 | page-size setting + paging integration with explicit small pages | PASS |
| REQ-032-05 | deterministic, semantic accept/reject và missing-citation cases | PASS |
| REQ-032-06 | exact Compose project/build/runtime/connector-zero gate | IMPLEMENTED; pilot run pending |
| REQ-032-07 | scorecard schema/evaluator; anti-gaming tests; honest `not_started` output | PASS; campaign pending |
| REQ-032-08 | exact five-case isolated run: 5/5, citation 100%, false-grounded 0 | PASS |
| REQ-032-09 | contract/readiness/digest/freshness/canary tests; real CRM blocked report | PASS SAFE; connection pending |
| REQ-032-10 | CRM-only command and active-connectors-zero pilot check | PASS |

## Performance Proof Boundaries

- Proved structurally: deterministic-supported answer removes one reviewer call; maximum
  metadata authorization trips fall from 25 to 5 at defaults; independent embedding and
  final lineage reads overlap.
- Live bounded result: p50 15.177 giây, p95 45.086 giây. Ba case operations/systems/methods
  hoàn tất trong 5.486–15.177 giây; hai product enumeration/exhaustive với 13–14 citation
  mất 44.419–45.086 giây. Không đạt scorecard target 25 giây.
- Usefulness và provider cost/query vẫn chưa được chứng nhận vì scorecard observation
  campaign chưa bắt đầu.
- Quality safeguard: semantic paraphrase, reviewer error/reject and all non-semantic trust
  failures retain repair/honest-null behavior; reviewer cannot grant authorization or waive
  a citation.

## Security / Governance

- No credential or live prompt/evidence was written to reports.
- CRM canary is GET-only, approved-host only, HTTPS except localhost, read-only and
  content-free; direct database access is forbidden by schema.
- Pilot recertification uses isolated database, exact immutable case list, concurrency 1
  and explicit export acknowledgement.
- Research and other ERP connectors are not auto-activated.

## Final Verdict

**READY-WITH-DEFERRED FOR BOUNDED PILOT QUALITY; NOT A PILOT GO.** Code, regression,
browser, local runtime và five-case quality gate đều healthy. Production-like pilot GO
được giữ lại tới khi: (1) latency tail của enumeration/exhaustive đạt ngưỡng được duyệt,
(2) scorecard có ít nhất 20 valid stratified observations và mọi gate pass, và (3) CRM
canary có approved source-side contract.
