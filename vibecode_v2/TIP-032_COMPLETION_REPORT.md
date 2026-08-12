## COMPLETION REPORT — TIP-032

**STATUS:** PARTIAL — implementation, local quality runtime và bounded quality
recertification đã hoàn tất; latency tail chưa đạt mục tiêu 25 giây, pilot observation
campaign và CRM source activation còn chờ hoàn thiện.

**FILES CHANGED:**

- Created: `apps/backend/src/rtr_copilot/enterprise_corpus/pilot_scorecard.py` —
  scorecard usefulness/trust/latency/cost chống làm đẹp số liệu.
- Created: `apps/backend/src/rtr_copilot/commands/evaluate_pilot_scorecard.py` —
  operator gate chỉ trả GO khi campaign hoàn tất và mọi ngưỡng đạt.
- Created: `apps/backend/src/rtr_copilot/commands/probe_crm_canary.py` — canary CRM
  content-free, read-only, host allowlist và fail-closed.
- Created: `apps/backend/tests/test_pilot_scorecard.py` — regression cho GO/NO-GO,
  minimum strata và honest-null precision/recall.
- Created: `scripts/run-tip032-recertification.sh` — đúng 5 case, isolated database,
  concurrency 1 và explicit external-export acknowledgement.
- Created: `eval/pilot/tip032_scorecard.json` và kết quả `not_started` — template
  observation thật, không seed điểm giả.
- Created: `eval/enterprise_corpus/crm_canary.json` — bằng chứng CRM hiện bị chặn
  trước network vì chưa có endpoint/credential được phê duyệt.
- Created: `eval/real_world/tip032_bounded_recertification.json` — report content-free
  cho đúng 5 case live được phê duyệt, gồm quality gates và latency từng case.
- Modified: `rag/answer_llm.py`, `rag/answering.py` — reviewer chuyển sang on-demand;
  deterministic trust proof chạy trước, semantic gap mới gọi reviewer; mode `always`
  giữ làm rollback.
- Modified: `rag/retrieval.py`, `config.py` — overlap embedding với metadata ACL scan,
  metadata page size độc lập final candidate budget và chạy song song final lineage checks.
- Modified: `enterprise_corpus/connectors.py` — contract digest và canary attestation
  bắt buộc ACL, denied row, field mask, provenance, deletion và freshness cùng đạt.
- Modified: `verify-answer-runtime.sh`, `verify-pilot-database.sh`, `compose.yaml`,
  `.env.example`, `Makefile` — runtime/build/profile gate, operator targets và rollback config.
- Modified: `verify-scaffold.sh`, `verify-data-integration.sh` — retry/timeout có giới hạn
  cho dependency bootstrap nhằm giảm false failure do mạng package host.

**TEST RESULTS:**

- Acceptance criteria implemented: 10/10; exercised end-to-end: 8/10. Isolated pilot
  campaign và CRM active canary còn phụ thuộc môi trường/contract chưa được cấp.
- Deterministic fast path: PASS — ordinary grounded answer uses one answer-stage provider
  call instead of generator + reviewer; semantic paraphrase still invokes reviewer.
- Trust invariants: PASS — citation, output safety, entity, relevance, coverage, lineage,
  ACL/ABAC and persistence reauthorization remain fail-closed.
- Retrieval fast path: PASS — default worst-case metadata pages reduce 25 → 5 while
  final content candidate limit stays 200; embedding overlaps policy-only metadata scan.
- Web unit/build: 182/182 PASS; ESLint, TypeScript và production build PASS.
- Backend baseline suite: 623 PASS, 128 conditional SKIP; hai ca phụ thuộc production
  font/mount PASS khi chạy lại trên đúng image/profile, tạo kết quả chức năng 625/625.
- Final-diff focused suites: 72 PASS trước integration; sau các chỉnh sửa cuối,
  retrieval/integration 22 PASS + 22 conditional SKIP và scorecard/retrieval 28 PASS.
- Data integration: 69/69 PASS; migration/rollback/restore/policy probes PASS.
- Browser/accessibility/responsive: 125/125 PASS.
- Ruff: PASS; mypy: PASS trên 139 source files.
- Runtime: provider external, OpenAI semantic embedding 1536, policy/credential loaded,
  build identity matched; 7/7 containers healthy.

**ISSUES DISCOVERED:**

- Live bounded recertification: 5/5 PASS, citation accuracy 100%, false-grounded 0,
  p50 15.177 giây. Tuy nhiên p95 là 45.086 giây; hai truy vấn product enumeration/exhaustive
  lần lượt 45.086 và 44.419 giây, chưa đạt scorecard target 25 giây.
- Pilot scorecard: P1 — đúng trạng thái `not_started`, sample 0; tuyệt đối chưa đủ điều
  kiện GO.
- CRM: P2 — registry còn `contract_ready`; endpoint và credential chưa cấu hình, canary
  trả `blocked_not_connected` trước mọi network call.
- Orchestrated `make verify`: P3 — một lượt bootstrap `uv` timeout tại package host;
  mọi gate thành phần sau đó PASS và bootstrap đã có retry/timeout hữu hạn.

**DEVIATIONS FROM SPEC:**

- Bounded harness lịch sử dùng p95 gate 60 giây nên trả PASS; TIP-032 scorecard dùng
  target chặt hơn 25 giây và vì vậy latency vẫn là deferred P1, không được diễn giải là đạt.
- Isolated pilot stack chưa dựng — checkout không có `.env.pilot`; tác động: pilot gate
  đã có code/test nhưng chưa cấp chứng nhận cho một pilot database cụ thể.
- CRM chưa activate — đúng fail-closed contract; không đổi lifecycle để tạo PASS giả.

**SUGGESTIONS FOR CHỦ THẦU:**

- Mở TIP latency-tail riêng cho truy vấn enumeration/exhaustive: đo time-to-first-token,
  provider generation và output size; ưu tiên streaming/sectioned synthesis thay vì giảm
  reasoning hoặc cắt evidence mù quáng.
- Thu tối thiểu 20 observation pilot đã phân tầng trước khi GO; giữ reviewer `on_demand`,
  rollback `always` nếu semantic false-negative tăng.
- Chỉ chuyển CRM sang `enabled` sau khi source owner cấp HTTPS canary endpoint, secret
  store credential và attestation khớp exact contract digest.
