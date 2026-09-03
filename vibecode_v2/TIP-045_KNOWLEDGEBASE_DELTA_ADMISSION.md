# TIP-045 — KnowledgeBase Delta Admission

## Kết quả

Đã rà soát delta nguồn trong `/Users/os/RtR/KnowledgeBase` so với snapshot
enterprise corpus ngày 11/08/2026. Có 75 tệp được thay đổi ngoài repository
`RtR_Copilot`; phần lớn là bundle, archive, UI output, bản sao hoặc tài liệu làm
việc chưa đủ điều kiện trở thành bằng chứng trả lời.

Đối chiếu database local hiện hành cho thấy 6 nguồn canonical có 235 SOT
record/chunk (snapshot cũ ghi 219), còn 43 tài liệu enterprise vẫn có 9.046 file
chunk. Lineage test/integration trong primary đã được retire bằng transaction có
fingerprint: từ 49 active generation còn đúng 6, từ 285 retrievable SOT chunk
còn đúng 235 canonical chunk. Không xóa chunk/citation lịch sử.

Hai tài liệu mới có giá trị và có thể đi qua pipeline tài liệu hiện hành đã được
khóa checksum trong manifest:

1. `RtR_Khung_Cam_Ket_Theo_Cong_v1.xlsx` — phương pháp vận hành bán hàng theo
   cổng, phân loại `restricted`.
2. `CaoLocMatch_PoC/CaoLocMatch_TrangThai_16082026.pdf` — báo cáo trạng thái có
   chữ ký, nêu rõ cả năng lực lẫn giới hạn, phân loại `restricted`.

Audit cũng phát hiện ATOM-025 trong `_Architecture` đang gộp ba trạng thái khác
nhau: NDAA compliance, candidate/submission và Blue UAS list membership, trong
khi chưa có snapshot sơ cấp khóa checksum cho membership. Đã mở `CONF-11` ở
queue HIGH; chưa tự ý sửa atom trước quyết định owner.

Chưa kích hoạt hai tài liệu vào runtime. Cấu hình chất lượng yêu cầu OpenAI,
nhưng active canonical index hiện chỉ còn profile local
`rtr-offline-hash-embedding:1536`. Re-embedding 235 canonical record hoặc kích
hoạt hai tài liệu mới đều gửi nội dung ra endpoint external. Yêu cầu hiện tại
cho phép xử lý local nhưng chưa cấp quyền xuất phạm vi này, nên gate dừng đúng
trước external processing.

## Những gì không được nạp thô

- `RtR_Company_Knowledge_Base.docx`: giàu thông tin nhưng trùng phần company
  kernel, trộn contact/pricing/compliance và có claim cần kiểm tra độ mới.
- `RtR_Ma_Tran_Nang_Luc.xlsx`: tự khai báo P2 Confidential, có các dòng P3 và
  giá trị sản phẩm xung đột/cũ; cần tách ACL theo sheet/record.
- Các workbook bảo dưỡng 01–08: lẫn thông số có nguồn với giá, warranty,
  interval đang ghi `Đề xuất` và dữ liệu khách hàng giả lập. Nạp nguyên file sẽ
  làm tăng recall nhưng giảm độ tin cậy.
- Brief pháp lý AI rủi ro cao: chưa khóa kèm văn bản pháp lý sơ cấp chính thức.
- Bộ ghi hiện trường Tây Ninh: là mẫu chuẩn bị trước chuyến đi, không phải kết
  quả bay đã điền và ký.
- `Dataset_CongNgheChienLuoc`: giữ ở Research vì README hiện ghi chưa chạy
  `bites`; không nâng ngầm thành SOT.
- Kho DCMA: không bulk-ingest do độ nhạy, bản sao và yêu cầu matter ACL.
- Archive, bundle, ZIP và HTML sinh tự động: không phải nguồn canonical.

## Bằng chứng máy đọc được

- Manifest admission:
  `v2/eval/enterprise_corpus/knowledgebase_delta_manifest.yaml`
- Delta/disposition registry:
  `v2/eval/enterprise_corpus/knowledgebase_delta_2026-09-03.json`
- Primary cleanup/rollback evidence:
  `v2/eval/enterprise_corpus/primary_runtime_cleanup_2026-09-03.json`

Dry-run đã PASS với 2/2 file, tổng 97.616 byte, fingerprint
`7ff5f5bfbcde411c0585bcd4333ddba5540eec2dbcf899800e495914e277366b`.
Dry-run chỉ đọc schema/path/checksum, không tạo embedding và không gọi external.

Verifier hermetic cũng PASS cả ba phép thử âm: nội dung trùng, checksum drift và
path escape đều bị chặn. `external_calls = 0`.

Primary cleanup PASS với fingerprint
`c71db1e4d0ac35fe7f27e63a10f832138326aee5d1b886b8af3e7efbeae74d6a`
và audit event `d76e2e8b-adfc-4bca-93a0-a7181d9b126d`. Hậu kiểm độc lập xác nhận
mọi active state ngoài allowlist canonical bằng 0; audit chain hợp lệ với 3.915
event. Unit test 4/4 và Ruff PASS. Không có external call.

Release verification toàn repository cũng PASS sau khi khóa `libexpat1` ở bản
Debian đã vá `2.5.0-1+deb12u3`: ESLint, TypeScript và production web build
PASS; web test 209/209; backend unit 726 PASS, 132 conditional skip; integration
73/73; Ruff và mypy PASS trên 151 source file; Trivy ghi nhận 0 HIGH/CRITICAL
trên Debian và Python; migration/data-integration gate PASS.

Quan sát vận hành chưa được che giấu: 7/7 primary container healthy; pilot có
6 service healthy nhưng ClamAV đang unhealthy. `answer-runtime-check` còn fail
ở build binding vì checkout đang có thay đổi chưa commit và ở semantic profile
vì canonical index vẫn là offline. Đây là hai gate riêng, không phải lỗi cleanup.

## Gate tiếp theo

1. Sau phê duyệt external riêng, re-embed đúng 6 canonical source/235 record
   sang `text-embedding-3-small:1536`; không reindex fixture đã retire.
2. Sau phê duyệt xuất đúng hai tài liệu restricted, ingest với concurrency 1.
3. Xác minh checksum, current version, viewer-ready rendition, source zone,
   classification và ACL.
4. Chạy retrieval/E2E cho câu hỏi phương pháp bán hàng và CàoLọcMatch; yêu cầu
   không trình bày con số ngoài ngày snapshot như trạng thái hiện hành.
5. Xây adapter status-aware cho maintenance và record-level ACL cho capability
   matrix trước batch tiếp theo.

## Trạng thái

`LOCAL SOURCES CURATED · PRIMARY RUNTIME CLEAN · EXTERNAL SEMANTIC RE-EMBEDDING
AND TWO-DOCUMENT ACTIVATION AWAIT SEPARATE APPROVAL`
