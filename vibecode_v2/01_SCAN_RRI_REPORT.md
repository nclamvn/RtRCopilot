# SCAN + RRI REPORT · RtR Copilot V2

**Ngày:** 30/07/2026
**Phương pháp:** Vibecode Kit v6.1
**Vai trò:** Nguyễn Cảnh Lâm = Homeowner · Codex = Contractor · Builder agents = SCAN/BUILD
**Trạng thái:** SCAN hoàn tất · RRI đề xuất chờ Homeowner xác nhận cùng Blueprint

## 1. Kết luận điều hành

RtR Copilot hiện là một pilot tốt, có 263/263 kiểm thử pass, cho bốn năng lực đã
chứng minh: hỏi đáp từ SOT, honest-null, citation bằng record ID, phân quyền thô và
sinh tài liệu tất định từ bốn template.

Nó chưa đạt mô tả “ứng dụng nội bộ toàn năng”. Kiến trúc hiện tại là Python
`HTTPServer` đơn tiến trình + HTML/JS thuần + YAML/JSONL. Không có database, object
storage, job queue, file ingestion, multimedia viewer, ACL cấp record, SSO, CI/CD,
observability hoặc backup/restore.

Trạng thái tổng thể: **NOT READY cho triển khai diện rộng**. Hai lỗ hổng P0 phải
được đóng trước khi mở lại trên LAN/VPN.

## 2. Baseline định lượng

| Hạng mục | Hiện trạng |
|---|---:|
| File Git theo dõi | 69 |
| LOC Python/HTML/shell/YAML | 16.660 |
| Runtime chính | `copilot_server.py` 1.396 LOC |
| UI | 1.892 LOC · 7 màn · 48 hàm JS |
| API | 24 method-route |
| Kiểm thử pilot | 263 pass · 0 fail |
| Candidate fact cards | 123 · 0 hard error · 5 warning |
| Gói nhân viên | 137 record |
| Gói lãnh đạo | 162 record |
| Template | 4 |
| KnowledgeBase chưa nối | 1.454 file · 1,19 GB |
| Record ngành trong kernel chưa nối | 587 |

Kho KnowledgeBase gồm ít nhất 428 PDF, 238 PNG, 218 JPG, 193 Markdown, 71 DOCX,
58 XLSX, 11 PPTX và 38 WEBP. Ứng dụng hiện không catalog, index hoặc preview kho này.

## 3. Tài sản phải giữ

- Doctrine kernel-wins, disputed queue và curator gate.
- Honest-null; câu ngoài SOT trở thành knowledge gap.
- Leader allowlist và tư duy fail-closed.
- Candidate fact card có evidence span.
- Refinery có snapshot, verbatim evidence, idempotence và auditor độc lập.
- Bộ regression retrieval cho typo, CamelCase, stale spec và rò dữ liệu.
- Rendering tất định; trường bắt buộc thiếu thì fail-loud.
- Design DNA hiện có: shell, evidence dock, trust state và provenance-first UI.

## 4. P0 findings

### SEC-P0-01 · API đọc bỏ qua đăng nhập

`/api/search`, `/api/templates`, `/api/download`, `/api/gaps`, `/api/usedby` và
`/api/record` không gọi `who()`. Người chạm được host LAN có thể dump SOT, gap,
used-by và tải tài liệu nếu biết tên file.

### SEC-P0-02 · Authentication fail-open

Kho account lỗi/hỏng bị coi như kho rỗng; server có thể rơi về passcode, users file
hoặc anonymous staff. Auth mode đang phụ thuộc vào việc có account active thay vì
configuration bất biến.

### DATA-P0-01 · Phân quyền ở cấp process, không ở cấp dữ liệu

`COPILOT_PACK` chọn một gói cho cả process. Ba role toàn cục không diễn tả được
phòng ban, dự án, khách hàng, hồ sơ, nguồn, field, thời hạn hoặc quyền tạm thời.

### DATA-P0-02 · Publish gate không khóa toàn chuỗi

Kernel đang có một fact thiếu provenance làm validator fail, nhưng exporter vẫn có
thể sinh serving pack. Exporter cũng bỏ evidence span, owner và signoff; citation ID
không đủ chứng minh trang/sheet/cell/timecode.

### DATA-P0-03 · Tài liệu locked có thể stale

Một số template dùng value hard-code rồi chỉ kiểm tra text xuất hiện trong record.
SOT thay đổi không bảo đảm template cập nhật, và fact loại `claim` vẫn có thể đi vào
tài liệu mang tính chính thức.

### AI-P0-01 · Toàn bộ pack được gửi ra model

Ở LIVE mode, toàn bộ `GOI_TEXT` được ghép vào system prompt mỗi request. Chưa có
ACL pre-filter, DLP/redaction, policy theo độ nhạy hoặc cost/context governance.

## 5. RRI Requirements Matrix

Các yêu cầu dưới đây được auto-answer từ tầm nhìn của Homeowner, PRD cũ, Design DNA
và SCAN. Chỉ những quyết định Level 3 ở mục 7 cần Homeowner xác nhận.

| REQ-ID | Yêu cầu | P | Persona |
|---|---|---:|---|
| REQ-001 | Mọi API dữ liệu fail-closed; anonymous chỉ được login/activation/health tối giản | P0 | Security |
| REQ-002 | Auth store lỗi/mất/corrupt làm service unhealthy, không fallback | P0 | Operator |
| REQ-003 | Đăng nhập bằng danh tính email công ty qua OIDC; hỗ trợ deprovisioning | P0 | End user |
| REQ-004 | RBAC + ABAC theo action, record, file, phòng ban, dự án và classification | P0 | Business |
| REQ-005 | HTTPS, session an toàn, security headers, rate/body/cost limits | P0 | Security |
| REQ-006 | Audit append-only theo immutable user ID; retention/redaction/export policy | P0 | Operator |
| REQ-007 | Chỉ gửi các evidence chunks đã được ACL-filter và DLP-check tới model | P0 | Security |
| REQ-008 | Trả lời từ SOT có citation tới evidence, version và trạng thái hiệu lực | P0 | End user |
| REQ-009 | Honest-null; tự ghi gap, owner và workflow bổ sung tri thức | P0 | Curator |
| REQ-010 | Hybrid retrieval: metadata ACL filter → lexical/vector → rerank | P0 | Developer |
| REQ-011 | Copilot là view read-only của SOT; mọi ghi phải qua curator/publish gate | P0 | Business |
| REQ-012 | Corpus ngành ngoài tách vùng, gắn nhãn rõ và không được giả làm fact RtR | P0 | Business |
| REQ-013 | Catalog tài liệu canonical có hash, version, owner, ACL, lifecycle | P0 | Curator |
| REQ-014 | Ingestion vào quarantine; MIME sniff, AV scan, dedupe và size quota | P0 | Security |
| REQ-015 | Publish transaction: validate → provenance → ACL/DLP → index → activate | P0 | Operator |
| REQ-016 | Freshness, expiry, supersedes, conflict và owner review có lịch | P1 | Curator |
| REQ-017 | Upload/mở ảnh, PDF, DOCX, XLSX, PPTX, video và audio trong app | P0 | End user |
| REQ-018 | Viewer citation sâu tới page, sheet/cell, slide và timecode | P1 | End user |
| REQ-019 | OCR ảnh/PDF scan, table extraction, audio/video transcription | P1 | End user |
| REQ-020 | Attachment theo hội thoại là context riêng, không tự thành SOT | P0 | Security |
| REQ-021 | Object storage có owner/ACL/classification/expiry và download kiểm quyền | P0 | Security |
| REQ-022 | Template registry có schema, version, owner, approval và locked fact binding | P0 | Business |
| REQ-023 | Sinh DOCX/XLSX/PDF/PPTX/report/form tất định từ template chuẩn | P1 | End user |
| REQ-024 | Preview thật, chỉnh tham số, rerender và lưu version trong app | P1 | End user |
| REQ-025 | Công văn/hồ sơ ràng buộc pháp nhân có review, approval và issuance trail | P0 | Business |
| REQ-026 | Unified workspace: Ask, Files, Documents, SOT, Gaps, Audit, Admin | P1 | End user |
| REQ-027 | Responsive, keyboard-first, WCAG 2.2 AA, Việt/Anh | P1 | Accessibility |
| REQ-028 | Database giao dịch, object store, background workers và search index | P0 | Developer |
| REQ-029 | CI: unit/integration/E2E/accessibility/security/load và migration gate | P0 | QA |
| REQ-030 | Metrics, tracing, alert, backup/restore, RPO/RTO và rollback runbook | P0 | Operator |
| REQ-031 | Quota/cost control theo user và workload; không để một model call chặn app | P1 | Operator |
| REQ-032 | Admin quản trị user/group/policy/source/template/job, không sửa SOT trực tiếp | P1 | Admin |
| REQ-033 | Refinery adapter đưa dataset ngành vào quarantine với graduation policy | P1 | Curator |
| REQ-034 | Coverage/freshness/gap dashboard tính từ dữ liệu sống, không snapshot tay | P1 | Leadership |

## 6. Decisions Log đề xuất

| ID | Quyết định đề xuất | Lý do |
|---|---|---|
| D-001 | Không mở rộng monolith; dựng V2 song song và giữ pilot làm oracle regression | Tránh rewrite phá bằng chứng đã có |
| D-002 | Một ứng dụng, một policy engine; không chạy process staff/leader riêng | Quyền phải áp theo request và record |
| D-003 | Tách SOT, external research và private attachment thành ba trust zones | Không trộn fact công ty với nguồn tham khảo |
| D-004 | File gốc bất biến; mọi preview là rendition có checksum và lineage | Truy vết và tái tạo được |
| D-005 | “Mở file” ở V2.1 là xem, tìm, trích dẫn, tải theo quyền; chỉnh Office trực tiếp là phase sau | Giữ scope release đầu kiểm soát được |
| D-006 | Mọi tài liệu chính thức lấy structured fact đã verified, không hard-code copy | Chặn stale value |
| D-007 | UI giữ Design DNA hiện có; signature mới là Evidence Rail đi theo chat/file/doc | Đặc trưng đúng bản chất RtR, không generic AI UI |

## 7. Level-3 decisions cần Homeowner xác nhận

Blueprint dùng default an toàn dưới đây. Trả lời `APPROVED` nghĩa là chấp nhận các
default; nếu khác, ghi rõ ID cần đổi.

| ID | Default đề xuất |
|---|---|
| OQ-001 | Identity: Google Workspace OIDC cho `rtrobotics.com` và `rtrobotics.me`; local admin chỉ là break-glass |
| OQ-002 | Deploy đầu: Docker Compose trên private Linux VM, HTTPS, chỉ qua VPN/LAN; kiến trúc giữ đường nâng lên managed cloud |
| OQ-003 | AI data policy: chỉ gửi evidence chunks đã ACL-filter; vùng leader/restricted mặc định không gửi ra provider nếu chưa allowlist |
| OQ-004 | V2.1 hỗ trợ xem/preview đa định dạng; collaborative Office editing được defer sau khi usage chứng minh cần |
