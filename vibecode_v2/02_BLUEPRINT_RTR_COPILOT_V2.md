# BLUEPRINT · RtR Copilot V2

**Vibecode Kit:** v6.1
**Ngày:** 30/07/2026
**Trạng thái:** CHỜ HOMEOWNER APPROVED
**Supersedes:** Blueprint Phase 0-1 ngày 27/07/2026 cho phạm vi portal production

## 1. Product thesis

RtR Copilot là lớp giao diện thông minh, đa phương tiện và có phân quyền trên toàn
bộ Source of Truth của RtR. Người có danh tính công ty dùng một workspace để hỏi,
tìm, xem, kiểm chứng và tạo tài liệu; mọi fact quan trọng truy ngược được tới bằng
chứng, phiên bản và quyền truy cập.

Đây không phải kho tri thức mới và không phải chatbot “biết tuốt”. Nó là
**evidence operating system** của công ty.

## 2. Kiến trúc đích

```text
┌──────────────────────────── RTR COPILOT WEB ────────────────────────────┐
│ Ask │ Files │ Documents │ SOT │ Research │ Gaps │ Audit │ Admin       │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTPS / session / request ID
┌───────────────────────────────▼─────────────────────────────────────────┐
│ API GATEWAY + POLICY ENGINE                                             │
│ Identity · RBAC/ABAC · quotas · audit · DLP · download authorization    │
└──────┬──────────────────┬──────────────────┬──────────────────┬─────────┘
       │                  │                  │                  │
┌──────▼──────┐   ┌───────▼───────┐  ┌──────▼──────┐  ┌──────▼────────┐
│ Knowledge   │   │ File/Rendition │  │ Document    │  │ Governance    │
│ & Answering │   │ service        │  │ service     │  │ service       │
│ hybrid RAG  │   │ OCR/media      │  │ templates   │  │ gaps/approval │
└──────┬──────┘   └───────┬───────┘  └──────┬──────┘  └──────┬────────┘
       │                  │                  │                  │
┌──────▼──────────────────▼──────────────────▼──────────────────▼────────┐
│ PostgreSQL + vector index │ Object storage │ Job queue │ Audit events │
└───────────────────────────┬────────────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────────────┐
│ PUBLISH GATE                                                          │
│ validate → provenance → classification/ACL → DLP → chunk/index → swap │
└─────────────┬──────────────────────┬──────────────────────┬────────────┘
              │                      │                      │
       SOT TRUST ZONE       RESEARCH TRUST ZONE    PRIVATE CONTEXT ZONE
       verified RtR facts   ngành ngoài/refinery   user attachments
```

### Trust-zone invariants

1. SOT facts và research records không dùng chung nhãn tin cậy.
2. Attachment chỉ thuộc người dùng/workspace được cấp quyền; không tự nạp SOT.
3. Policy filter chạy trước retrieval và chạy lại trước khi dựng prompt.
4. Không có evidence được phép thì honest-null, kể cả model “biết”.
5. File gốc bất biến; rendition, chunk và transcript đều trỏ về checksum/version.
6. Tài liệu chính thức chỉ bind vào structured fact đủ provenance theo policy.

## 3. Tech stack

| Lớp | Lựa chọn |
|---|---|
| Web | Next.js/React + TypeScript strict |
| API | FastAPI/Python có schema validation và OpenAPI |
| Database | PostgreSQL; vector index dùng pgvector ở quy mô đầu |
| Object storage | S3-compatible; MinIO cho local/private deploy |
| Queue/cache | Redis + Python background workers |
| Search | PostgreSQL full-text + vector hybrid; tách search service khi tải chứng minh cần |
| Identity | OIDC qua Google Workspace; group mapping + break-glass admin |
| Document/media | LibreOffice headless, PDF.js, PyMuPDF, python-docx, openpyxl, python-pptx, OCR engine, FFmpeg |
| AI | Provider adapter; chat/extract/transcription không hard-code vendor |
| Runtime | Docker Compose trên private Linux VM sau reverse proxy HTTPS |
| Observability | Structured logs, metrics, traces, error tracking và alert rules |
| QA | Unit + API integration + browser E2E + axe + security regression + load tests |

Không pin version trong Blueprint. Builder phải dùng stable supported versions tại
thời điểm thi công và khóa toàn bộ dependency trong manifest/lockfile.

## 4. Canonical data model

Các entity tối thiểu:

- `users`, `groups`, `roles`, `policies`, `entitlements`
- `sources`, `documents`, `document_versions`, `renditions`
- `records`, `record_versions`, `evidence_spans`, `classifications`
- `chunks`, `index_jobs`, `ingestion_jobs`, `review_tasks`
- `conversations`, `messages`, `attachments`
- `templates`, `template_versions`, `render_jobs`, `generated_files`
- `gaps`, `issues`, `approvals`
- `audit_events`

Mọi object nghiệp vụ có UUID bất biến, owner, classification, created/updated,
version, checksum khi áp dụng và soft-delete/retention state. Quyền không được suy
từ tên hiển thị hoặc filename.

## 5. Primary user flows

### Ask with evidence

Đăng nhập → nhập câu hỏi/attachment → policy scope → hybrid retrieval → evidence
dock → trả lời/citation → mở đúng page/sheet/cell/timecode → báo sai hoặc dùng fact
trong tài liệu.

### Open and understand a file

Upload/chọn source → quarantine/scan → extract/render → preview trong app → search/
ask trong file → citation sâu → tải theo quyền. File lỗi có trạng thái rõ và retry.

### Create an official document

Chọn template → nhập yêu cầu tự nhiên hoặc form → extract parameter không suy đoán
→ bind verified SOT facts → preview → review/approve nếu cần → render tất định →
checksum/audit → download/issue.

### Curate knowledge

Source/crawler upload → quarantine → extraction + evidence → dedupe/conflict →
curator review → signoff/classification → atomic publish → incremental reindex →
coverage/freshness dashboard.

## 6. UI direction

Giữ hệ Design DNA hiện có, không thay bằng dashboard AI generic.

```text
┌──────────────┬──────────────────────────────────────┬──────────────────┐
│ RtR / Nav    │ Work surface                         │ Evidence Rail    │
│              │ Chat · File · Document · Governance │ source/version/ │
│ Ask          │                                      │ ACL/page/cell/  │
│ Files        │                                      │ timecode        │
│ Documents    │                                      │                  │
│ Knowledge    │                                      │                  │
│ Operations   │                                      │                  │
└──────────────┴──────────────────────────────────────┴──────────────────┘
```

**Signature:** Evidence Rail không chỉ dành cho câu trả lời; nó theo người dùng khi
xem file, điền form và preview tài liệu. Mỗi số liệu có thể “bật nắp” để thấy nguồn,
phiên bản, hiệu lực và quyền sử dụng.

Design tokens gốc tiếp tục là nguồn chuẩn. Màu signal dùng tiết chế cho trust state,
không làm accent trang trí. Font và mật độ ưu tiên đọc hồ sơ kỹ thuật, bảng dữ liệu
và văn bản hành chính. WCAG 2.2 AA và reduced motion là acceptance criteria.

## 7. Migration strategy

- Giữ `phase1_pilot` read-only làm legacy oracle.
- Dựng V2 song song; không sửa monolith ngoài TIP containment.
- Import 137/162 record qua adapter và so kết quả retrieval/citation.
- Import log chỉ sau khi có retention/redaction decision.
- KnowledgeBase đi qua catalog/quarantine theo batch; không index thẳng cả 1,19 GB.
- 587 research records đi qua research adapter/graduation gate, không nhập SOT.
- Cutover theo nhóm pilot, rollback về pilot chỉ khi dữ liệu/policy an toàn.

## 8. Milestones và acceptance gates

### M0 · Containment

Đóng hai P0, kiểm toàn bộ endpoint theo anonymous/staff/leader/admin, server fail-closed.

### M1 · Secure platform foundation

OIDC, policy engine, PostgreSQL, object store, audit, HTTPS, CI và deploy repeatable.

### M2 · Knowledge core

Publish gate nguyên tử, canonical catalog, provenance đầy đủ, hybrid retrieval, deep
citation và parity với 263 regression tests.

### M3 · Multimedia workspace

Upload/view/search ảnh, PDF, DOCX, XLSX, PPTX, video, audio; OCR/transcript/rendition
và ACL/download ownership được kiểm thử.

### M4 · Document operating system

Template lifecycle, structured fact binding, DOCX/XLSX/PDF/PPTX/forms, preview,
approval và issuance audit.

### M5 · Company rollout

Research adapter, admin/governance dashboard, accessibility/security/load gates,
backup/restore drill, staged pilot và production readiness review.

## 9. Requirement coverage dự kiến

Blueprint ánh xạ **34/34 REQ-ID (100%)** vào kiến trúc và Task Graph. “Implemented”
hiện vẫn là 0/34 cho V2; baseline pilot chỉ được tính là reusable asset, không được
đánh đồng với completion.

## 10. Checkpoint

- [ ] Kiến trúc đích đúng tham vọng
- [ ] Bốn default OQ-001..004 được chấp nhận hoặc sửa
- [ ] V2 được phép dựng song song, pilot chỉ sửa containment
- [ ] Mốc “mở file” V2.1 là view/search/cite, chưa collaborative edit
- [ ] Task Graph được phép phát hành cho Builder

**Homeowner trả lời `APPROVED` để Chủ thầu phát TIP-001 và bắt đầu BUILD.**
