# TIP-032 · Bounded Pilot, Latency Recovery & CRM Canary

**Ngày:** 12/08/2026

**Ưu tiên:** P0 → P1 → P2

**Trạng thái:** IMPLEMENTED · QUALITY RECERTIFIED · LATENCY/PILOT/CRM PENDING

**Phụ thuộc:** TIP-024.7, TIP-025, TIP-027.5, TIP-029, TIP-030, TIP-031

## Context

TIP-031 đã khôi phục runtime cùng semantic profile, dựng pilot database cô lập,
activate governance release và chứng minh Documents OS. Tuy nhiên ba khoảng cách còn lại
trước pilot có kiểm soát là: live semantic tail chưa được tái chứng nhận trên đúng build;
đường găng Ask vẫn trả thuế reviewer/metadata tuần tự không cần thiết; và connector CRM
mới ở mức contract-ready, chưa có canary read-only fail-loud. Homeowner đã phê duyệt triển
khai thứ tự này và bổ sung yêu cầu tăng tốc phản hồi mà không đánh đổi chất lượng.

## Requirements

| ID | Yêu cầu | Mức |
|---|---|---|
| REQ-032-01 | Giữ nguyên mọi ACL/ABAC, DLP, lineage, citation, relevance, coverage và deterministic-grounding gate | P0 |
| REQ-032-02 | Reviewer LLM chỉ chạy khi cần phân xử semantic support mà deterministic verifier chưa chứng minh được; có mode rollback `always` | P0 |
| REQ-032-03 | Chồng lấp query embedding với metadata authorization scan; không tải content trước policy | P0 |
| REQ-032-04 | Metadata page size độc lập với final candidate budget để giảm round-trip DB nhưng giữ scan bound/deadline | P0 |
| REQ-032-05 | Có regression chứng minh fast path giảm call mà semantic paraphrase vẫn được reviewer kiểm và mọi lỗi trust vẫn fail-closed | P0 |
| REQ-032-06 | Có operator gate cho pilot database cô lập, đúng build/runtime, không lẫn fixture và không connector ngầm active | P1 |
| REQ-032-07 | Có scorecard pilot đo usefulness, clarification recovery, citation accuracy, honest-null precision, false-grounded, authz leakage, p95 và cost/query | P1 |
| REQ-032-08 | Live recertification chỉ chạy exact bounded cases, isolated DB, explicit external-export acknowledgement và budget cap | P1 |
| REQ-032-09 | CRM canary chỉ active khi read-only contract, approved endpoint/credential, source health, ACL, provenance, deletion và freshness probes đều pass | P2 |
| REQ-032-10 | Research vẫn opt-in và phân vùng; MRP/IP/HRM không tự kích hoạt theo CRM canary | P2 |

## Acceptance Criteria

```gherkin
Given một answer candidate vượt deterministic grounding ngay lần đầu
When review mode là on_demand
Then không gọi reviewer và mọi trust gate còn nguyên

Given candidate là semantic paraphrase không có lexical overlap
When deterministic grounding trả evidence_unsupported
Then reviewer xem đúng question, evidence và marker; chỉ accepted review mới được kiểm lại

Given reviewer timeout, reject hoặc candidate vi phạm citation/entity/coverage
When AnswerService xác minh
Then answer không được bypass deterministic gate và repair/honest-null vẫn hoạt động

Given corpus có tối đa 5.000 metadata rows
When retrieval chạy
Then embedding và metadata scan chồng lấp, content chỉ được tải sau ACL, scan/deadline vẫn bounded

Given pilot operator chưa cung cấp external-export acknowledgement hoặc CRM probe còn thiếu
When chạy activation/recertification
Then command fail-loud và không gửi dữ liệu/không activate connector

Given pilot đã có quan sát thật
When scorecard được chấm
Then GO chỉ khi false-grounded=0, authz leakage=0 và toàn bộ ngưỡng usefulness/trust/latency/cost đạt
```

## Constraints

- Không commit credential, PII hoặc evidence/prompt live.
- Không xóa/reset database hoặc volume dev; pilot luôn dùng project/volume cô lập.
- Không giảm reasoning/output budget một cách mù quáng; chỉ bỏ công việc dư thừa khi
  deterministic proof đã đủ.
- Reviewer không bao giờ thay thế citation, lineage, entity, relevance hoặc coverage gate.
- CRM canary là read-only; cấm direct database access và cấm tự kích hoạt connector khác.
- Research không được tự động thăng cấp thành company SOT.

## Decisions Log

- Bỏ checkpoint Blueprint riêng vì Homeowner đã approve trực tiếp kế hoạch trước đó.
- Tối ưu theo `fast when provable`: deterministic pass bỏ reviewer; semantic gap mới
  gọi reviewer; mode `always` là rollback vận hành.
- Tăng metadata page size, không tăng final content candidate budget.
- Pilot scorecard chỉ ghi số đo thật; trạng thái ban đầu là `not_started`, không dùng số
  giả để tuyên bố GO.
- Scorecard cần tối thiểu 20 quan sát, trong đó có ít nhất 3 ca cần làm rõ, 3 ca
  honest-null và 20 citation đã kiểm; precision và recall honest-null được tính riêng
  để không thể đạt GO bằng cách từ chối mọi câu hỏi.

## Traceability

| Requirement | Implementation | Verification |
|---|---|---|
| REQ-032-01..05 | Answer/retrieval critical path + settings | Unit, integration, enterprise E2E |
| REQ-032-06 | Pilot readiness command/report | Isolated runtime checks |
| REQ-032-07 | Pilot scorecard schema/evaluator | Valid/invalid fixture tests |
| REQ-032-08 | Bounded recertification wrapper | Dry-run + authorized live run |
| REQ-032-09..10 | CRM canary admission command | Missing/invalid/ready probe tests |

## Completion / Verify

- [TIP-032 Completion Report](TIP-032_COMPLETION_REPORT.md)
- [TIP-032 Verify Report](TIP-032_VERIFY_REPORT.md)
