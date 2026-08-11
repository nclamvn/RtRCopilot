# TIP-031 · Pilot & Production Recovery

**Ngày:** 11/08/2026

**Ưu tiên:** P0 → P1 → P2

**Trạng thái:** IMPLEMENTED · LIVE RECERTIFICATION AUTHORIZATION PENDING

**Phụ thuộc:** TIP-014RE, TIP-025, TIP-029, TIP-030

## Context

X-Ray trực tiếp tại checkout `main` phát hiện nền tảng đã có kiến trúc enterprise và
campaign live gần nhất được lưu đạt 74/77 cases với false-grounded bằng 0, nhưng checkout/runtime hiện tại chưa thể phát hành
nguyên trạng: web unit regression, runtime evidence-only không cùng semantic profile với
vector đã lưu, database lẫn fixture, ClamAV unhealthy, governance ledger chưa active và
Documents OS chưa có lifecycle thực tế.

Yêu cầu của Homeowner: triển khai lần lượt các hạng mục cần làm, ưu tiên khôi phục tính
sẵn sàng pilot trước khi mở rộng connector.

## Requirements

| ID | Yêu cầu | Mức |
|---|---|---|
| REQ-P0-01 | Ask auto-scroll capability-safe; web unit không regression | P0 |
| REQ-P0-02 | Runtime quality profile và query embedding đồng nhất với stored vectors | P0 |
| REQ-P0-03 | Có đường tạo pilot database sạch, không phá database dev hiện tại | P0 |
| REQ-P0-04 | ClamAV healthy hoặc fail-loud trước upload/ingestion | P0 |
| REQ-P0-05 | Runtime công bố immutable build SHA của checkout | P0 |
| REQ-P1-01 | Governance domain/manifest/ontology/release có activation path kiểm được | P1 |
| REQ-P1-02 | Backfill file chunks dùng adapter embedding được cấu hình | P1 |
| REQ-P1-03 | Corpus inventory sinh từ database và có drift gate | P1 |
| REQ-P1-04 | Documents OS được kiểm chứng render → approve → issue → revoke | P1 |
| REQ-P1-05 | CRM quality-tail case được đóng và re-evaluate | P1 |
| REQ-P2-01 | Connector ecosystem/federated research giữ provenance, quyền và cost gate | P2 |

## Acceptance Criteria

```gherkin
Given Ask được render trong browser hoặc test DOM không có scrollIntoView
When transcript thay đổi
Then UI không crash và browser có capability vẫn auto-scroll

Given corpus đang lưu OpenAI 1536-dimensional vectors
When quality runtime khởi động
Then provider, dimension, policy và build SHA được preflight trước khi nhận truy vấn

Given database dev có fixture
When chuẩn bị pilot
Then có quy trình dựng database/volume pilot riêng và không xóa dữ liệu hiện hữu

Given file upload được bật
When scanner không healthy hoặc signature stale
Then ingestion fail-loud thay vì bỏ qua kiểm tra

Given một backfill được chạy
When embedding provider là OpenAI
Then command sử dụng cùng configured adapter, không sinh offline-hash vectors
```

## Constraints

- Không xóa hoặc reset database/volume hiện hữu nếu chưa có approval riêng.
- Không commit credential; chỉ kiểm tra sự hiện diện và policy.
- Research bên ngoài không được tự động thăng cấp thành company SOT.
- P2 không được làm suy yếu provenance, ACL/ABAC, DLP hoặc cost guard.

## Decisions Log

- Dùng một TIP gộp theo phase vì đây là một recovery chain có dependency tuyến tính.
- Bỏ checkpoint Blueprint riêng: Homeowner đã approve trực tiếp thứ tự P0 → P1 → P2.
- Mỗi phase chỉ được chuyển trạng thái sau khi gate phase trước có bằng chứng định lượng.

## Completion / Verify

### Phase P0 · Pilot runtime recovery — PASS

- Ask auto-scroll chỉ gọi `scrollIntoView` khi DOM/runtime thực sự hỗ trợ capability;
  web regression được khoá bằng test.
- `verify-answer-runtime.sh` fail-loud theo provider, credential, external-processing
  policy, build identity, embedding model và dimension đang lưu trong PostgreSQL.
- `reindex_file_chunks.py` dùng configured embedding adapter; không còn âm thầm tạo
  offline-hash vector khi runtime đang dùng OpenAI 1536 chiều.
- Build identity bao gồm tracked diff và untracked implementation files, sau đó được
  đưa vào API/worker/web bằng `RTR_BUILD_SHA`.
- Pilot dùng `.env.pilot`, compose project, port và volume riêng; không reset/xoá dev DB.
- ClamAV có healthcheck thực, upload/ingestion tiếp tục fail-loud nếu scanner không sẵn sàng.

### Phase P1 · Governance, corpus và Documents OS — PASS

- Enterprise release plan có 5 domain, 17 evaluation cases; bootstrap là resumable,
  local-only và chỉ activate release khi toàn bộ gate đạt. Kết quả: **17/17 PASS**, 5
  domain active, 1 ontology revision và 1 release attestation active.
- Runtime inventory lấy trực tiếp từ DB và có stable digest gate. Snapshot hiện ghi:
  219 canonical SOT records/chunks; 43 approved enterprise documents, 9.046 searchable
  chunks; 1.928 research records, trong đó TheSkyWatch chiếm 1.838; 73 open gaps.
- Physical schema drift của `document_publication_outbox` được sửa bằng migration tiến
  `0014_document_outbox_repair`; startup kiểm cả revision và các relation bắt buộc.
- Documents OS đã chứng minh chu trình render → approve → issue → revoke với checksum,
  audit và provenance thật; không còn chỉ là API/unit contract.

### Phase P2 · Connector/federation foundation — CONTRACT PASS, NOT CONNECTED

- Registry contract bắt buộc read-only, cấm direct DB, có deletion propagation,
  row/field/purpose policies, cursor, freshness SLA, provenance và cost budgets.
- Federation planner giữ nhãn `sot/private/research`; research không bao giờ tự thăng
  cấp thành company SOT.
- CRM, MRP và IP: repository được phát hiện, contract-ready nhưng chưa có approved
  endpoint/credential. HRM: blocked vì chưa xác nhận authoritative repository/owner.
- Số connector active production hiện là **0**. Đây là nền an toàn để tích hợp tiếp,
  không phải tuyên bố hệ sinh thái đã live.

### Verification snapshot

- `make verify`: PASS — Web lint/type/build, 182 web tests; Ruff, mypy trên 136 source
  files, 613 backend tests pass + 128 conditional skips; 69 data-integration tests;
  migration/image/Trivy/policy/data gates đều pass.
- Playwright mocked/browser/a11y/responsive: **125/125 PASS**.
- Database gate: revision `0014`, 7 required physical relations và 7 forbidden runtime
  operations được xác minh.
- Answer runtime preflight: external provider, OpenAI embedding 1536, credential,
  processing policy, schema và build identity đồng nhất.

### Deviation có chủ đích

Không chạy lại 5 live semantic tail cases qua LLM trong phiên này. Các case đó có thể
gửi câu hỏi và evidence nội bộ được cấp quyền tới endpoint ngoài; sandbox đã từ chối khi
chưa có ủy quyền rõ payload/destination. Campaign 74/77 được dùng như historical evidence,
không được trình bày như một lần recertification mới.

### Verdict

**GO có điều kiện cho pilot nội bộ trên company corpus hiện hữu.** Chưa GO production
ecosystem: cần (1) ủy quyền và chạy bounded live recertification, (2) cấu hình connector
read-only theo từng hệ thống, (3) xác nhận HRM source/owner, và (4) vận hành pilot trên
database cô lập trước rollout rộng.
