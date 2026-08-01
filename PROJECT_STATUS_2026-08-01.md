# RtR Copilot — Tổng kết dự án đến ngày 01/08/2026

> **Loại tài liệu:** Project X-Ray / Executive Status / Handover  
> **Phương pháp:** Vibecode Kit v6.1  
> **Repository:** `nclamvn/RtRCopilot` (private)  
> **Nhánh chuẩn:** `main`  
> **Commit gần nhất khi lập báo cáo:** `a404a367b63c443f284f163716915727900c0993`  
> **Phạm vi kiểm chứng:** mã nguồn, lịch sử Git, Blueprint, Task Graph, TIP/Completion/Verify Report và trạng thái runtime local.

---

## 1. Kết luận điều hành

RtR Copilot đã vượt khỏi mức chatbot thử nghiệm và hiện có một **nền tảng V2 có kiến trúc production**, bao phủ ba năng lực lõi:

1. **Biết điều gì được phép coi là sự thật:** SOT Kernel, provenance, freshness, policy, publish gate và audit.
2. **Tìm, hỏi và xem bằng chứng:** Hybrid RAG có ACL/DLP, honest-null, deep citation và File Workspace đa định dạng.
3. **Biến sự thật thành đầu ra có quản trị:** Document Operating System với template bất biến, locked fact, render tất định, duyệt, phát hành và thu hồi.

Đến thời điểm lập báo cáo:

- **9/13 TIP đã VERIFIED · READY** — tương đương 69% số mốc kỹ thuật.
- **4 TIP còn lại:** Governance/Research, Unified UX, Production Hardening và Migration/Final Verify.
- **Không còn P0/P1 mở trong phạm vi TIP-001…009 đã nghiệm thu.**
- **Chưa đủ điều kiện rollout toàn công ty hoặc tuyên bố production-ready**, vì chưa hoàn thành TIP-010…013 và chưa kích hoạt dữ liệu công ty thật.
- Runtime local hiện **đang dừng**; cổng `3000` và `8000` không phục vụ tại thời điểm kiểm tra. Đây là trạng thái vận hành, không phải lỗi source.

Đánh giá khách quan:

| Trục | Mức hiện tại | Nhận định |
|---|---:|---|
| Nền tảng kỹ thuật V2 | 70–75% | Phần khó về security, dữ liệu, file và document đã có |
| Product experience hoàn chỉnh | 55–60% | Files và Documents đã có; Ask/Evidence Rail hợp nhất và Admin/Governance còn thiếu |
| Production readiness | 50–55% | Còn ingress/TLS, observability, quota, CI/CD, load, DR và final security gate |
| Rollout dữ liệu thật | 25–35% | Pipeline đã sẵn, nhưng kernel/template/corpus thật chưa được phê duyệt và migrate |
| Tầm nhìn dài hạn Intelligence & Action OS | 35–45% | “Truth + evidence + document” đã rõ; forecasting, partner/policy proposal và action integration còn ở giai đoạn sau |

Các tỷ lệ trên là **ước lượng kỹ thuật có chủ đích**, không thay thế Verify Report cuối của TIP-013.

---

## 2. Luận điểm sản phẩm

RtR Copilot không nên được định vị là “chatbot nội bộ”. Định vị đúng là:

> **Enterprise Intelligence & Action OS — cửa ngõ thống nhất để tìm, hỏi, kiểm chứng, xem, tạo và hành động trên sự thật có phân quyền của RtR.**

So với Spotlight của macOS:

- **Giống:** một điểm vào nhanh để tìm người, file, hồ sơ, record và nội dung.
- **Vượt xa Spotlight về tham vọng doanh nghiệp:** hiểu classification/ACL, provenance, version, fact/evidence, tạo tài liệu chuẩn, approval, issuance và audit.
- **Không nên sao chép Spotlight về bản chất:** Spotlight là universal search cá nhân; RtR Copilot là hệ điều hành bằng chứng và hành động của tổ chức.

Điểm riêng có khả năng trở thành “moat”:

- SOT Kernel nhiều tầng sự thật.
- Registry có provenance, owner, version, freshness và policy.
- Dữ liệu giao dịch từ MRP/CRM/HRM/IP.
- Corpus ngành từ TheSkyWatch và các dataset chuyên biệt.
- Kho đề án, đề tài, hợp tác và kinh nghiệm thực thi.
- Refinery cào–lọc–đối chiếu có chủ đích.
- Feedback loop nối dự báo/đề xuất với kết quả kinh doanh thật.
- Audit nhiều vai theo Vibecode thay vì tin một lần sinh của AI.

Model LLM có thể thay thế. **Ontology, provenance, governance, workflow và outcome history** mới là tài sản bền.

---

## 3. Hai thế hệ của dự án

### 3.1 V1 / Phase 1 Pilot

V1 là sản phẩm thử nghiệm có giá trị, không phải phần bỏ đi. Nó đã chứng minh:

- question answering trên gói tri thức được kiểm soát;
- doctrine kernel-wins và honest-null;
- phân tầng gói nhân viên/lãnh đạo;
- đăng nhập theo người và feedback “báo sai”;
- tạo tài liệu zero-dependency từ template;
- regression cho typo, CamelCase, spec cũ, dữ liệu nhạy cảm và câu hỏi cạnh tranh;
- bộ pilot kit, hướng dẫn vận hành và theo dõi bốn tuần.

Baseline được ghi nhận trong Scan:

- 263 test pass tại thời điểm V2 bắt đầu;
- 137 record gói nhân viên, 162 record gói lãnh đạo;
- 123 candidate fact card;
- 4 template;
- monolith chính `phase1_pilot/copilot_server.py`.

Vai trò hiện tại của V1:

- **Legacy oracle:** chuẩn hành vi để so parity.
- **Nguồn regression:** giữ các lỗi và tình huống thật đã từng phát hiện.
- **Không phải kiến trúc để mở rộng production:** auth, policy, data/object, ingestion và audit đã được tái thiết kế trong V2.

### 3.2 V2 / Production Platform

V2 kế thừa **tri thức, doctrine, UX DNA, regression và bài học** của V1 nhưng làm mới nền tảng kỹ thuật:

- Next.js/React/TypeScript strict;
- FastAPI/Python 3.12;
- PostgreSQL + migrations;
- MinIO/S3-compatible object storage;
- Redis worker/queue;
- OIDC, RBAC + ABAC;
- append-only/tamper-evident audit;
- quarantine, malware scan, extraction và rendition;
- SOT publish/reindex;
- Hybrid RAG;
- Files Workspace;
- Document Operating System.

Vì vậy, câu trả lời chính xác là: **V2 có kế thừa V1 về tài sản và chuẩn hành vi, nhưng không kế thừa monolith như nền kiến trúc production.**

---

## 4. Kiến trúc hiện tại

```text
RtR Copilot Web
├── Ask / grounded answer API foundation
├── Files Workspace + multi-format viewers
└── Documents Workspace + approval/issuance
        │ same-origin proxy / session / request ID
        ▼
FastAPI + Identity + Policy Engine
├── OIDC / immutable identity / session invalidation
├── RBAC + ABAC / effective principals / deny precedence
├── SOT publish / provenance / freshness
├── Hybrid retrieval / DLP / grounding / citations
├── Ingestion / quarantine / AV / OCR / transcript / renditions
├── Template / binding / deterministic rendering
└── Append-only audit / backup / restore
        │
        ├── PostgreSQL + vector/full-text foundation
        ├── MinIO private object storage
        └── Redis worker coordination
```

Ba trust zone được giữ tách biệt:

| Trust zone | Vai trò | Luật |
|---|---|---|
| SOT | Fact RtR đã kiểm chứng | Chỉ publish qua provenance/policy gate |
| Research | Nguồn ngành bên ngoài | Không được masquerade thành fact công ty |
| Private context | File/attachment theo người hoặc workspace | Không tự động nạp vào SOT |

Các invariant quan trọng:

- Policy filter trước retrieval và kiểm lại trước prompt/render/publication.
- Explicit deny thắng allow, owner và admin.
- Không có evidence hợp lệ thì honest-null.
- Original bất biến; rendition/chunk/transcript giữ lineage tới checksum/version.
- Tài liệu chính thức chỉ bind fact có provenance đạt policy.
- Không lộ object key, bucket URL, internal hostname hay credential qua UI/API.

---

## 5. Trạng thái TIP

| TIP | Trạng thái | Kết quả chính | Bằng chứng nghiệm thu tiêu biểu |
|---|---|---|---|
| TIP-001 Security Containment | ✅ READY | Đóng auth fail-open và API leak của pilot | 5/5 AC; 288 regression + 25 probe |
| TIP-002 Platform Scaffold | ✅ READY | Monorepo V2, Compose, API/web/worker, health | 12/12 AC; build/audit/browser pass |
| TIP-003 Identity & Policy | ✅ READY | OIDC, immutable identity, RBAC/ABAC, revoke session | 11/11 AC; 86 backend tests; 51 policy scenarios |
| TIP-004 Data/Object/Audit | ✅ READY | DB schema, object integrity, append-only audit, race-safe restore | 16/16 AC; 94 unit/API + 6 integration |
| TIP-005 Ingestion & Renditions | ✅ READY | Quarantine, MIME/AV, OCR, transcript, 14 input formats | 18/18 AC; 31 rendition artifacts; Trivy sạch |
| TIP-006 SOT Publish & Provenance | ✅ READY | Atomic publish, attestation, freshness, reindex outbox | 16/16 AC; 153 backend + 20 integration |
| TIP-007 Hybrid RAG | ✅ READY | ACL-filtered retrieval, DLP, grounding, citation, honest-null | 17/17 AC; Recall@5 1.000; MRR 0.900; leak 0 |
| TIP-008 Files Workspace | ✅ READY | Catalog/upload/view/download, 7 viewer families, Evidence Rail | 18/18 AC; 28 web + 15 browser; leak 0 |
| TIP-009 Document OS | ✅ READY | Template lifecycle, 4-format render, preview, approve/issue/revoke | 19/19 AC; 175 backend + 37 integration + 34 web |
| TIP-010 Governance/Research | ⏳ Chưa triển khai | Curator/admin, gaps/freshness, refinery adapter | Research không giả làm fact RtR |
| TIP-011 Unified UX | ⏳ Chưa triển khai | Ask + Files + Documents + Evidence Rail hợp nhất | E2E, axe, keyboard, responsive, i18n |
| TIP-012 Production Hardening | ⏳ Chưa triển khai | HTTPS, quotas, observability, CI/CD, load, DR | SLO/load/restore/rollback/security gates |
| TIP-013 Migration & Final Verify | ⏳ Chưa triển khai | Migrate dữ liệu thật, parity, pilot, go/no-go | 34 REQ; zero P0/P1; final report |

Tất cả TIP-001…009 đều có đủ audit trail tối thiểu:

- Task Instruction Pack;
- Completion Report;
- Contractor Verify Report.

Một số TIP từng bị trả về **NOT READY** khi audit độc lập phát hiện lỗi thật, sau đó mới được refine và nghiệm thu. Đây là tín hiệu tích cực về chất lượng quy trình, không phải thất bại của dự án.

---

## 6. Năng lực sản phẩm đã có

### Identity, security và policy

- OIDC production provider và dev OIDC tách biệt.
- Email domain công ty allowlist.
- Immutable user identity.
- Session security version; disable/downgrade/revoke làm session cũ mất hiệu lực.
- RBAC + ABAC theo user/group/role/department/project.
- Deny precedence và admin không bypass dữ liệu.
- Typed 401/403/404; ẩn sự tồn tại của resource không được phép.
- Audit allow/deny cho nội dung restricted/classified.

### Data, object và audit foundation

- Migrations `0001` đến `0008_document_operating_system`.
- Runtime DB least privilege.
- Resource/version/object checksum và lineage.
- Append-only audit có chain/anchor và kiểm tra tamper.
- Backup/restore có manifest, SHA-256, grant restoration và race-safe cleanup.
- Maintenance mode và mutation guard cho recovery.

### Ingestion và trình xem

Đầu vào hỗ trợ:

- ảnh: PNG, JPEG, WebP, TIFF;
- PDF;
- Office: DOCX, XLSX, PPTX;
- video: MP4, WebM;
- audio: MP3, M4A, WAV, OGG.

Năng lực:

- streaming upload;
- MIME/magic-byte validation;
- ClamAV fail-closed;
- archive/OOXML safety;
- extraction, OCR, transcript và WebVTT;
- PDF/text/grid/browser-safe media renditions;
- byte range cho media/PDF;
- deep locator page/sheet/cell/slide/timecode;
- quyền `view` và `download` tách riêng.

### SOT và RAG

- Adapter package có checksum, attestation và rooted parser.
- Fact/evidence/version/freshness/provenance được hash và khóa bất biến.
- Atomic activation và durable reindex outbox.
- Hybrid lexical/vector retrieval và reciprocal-rank fusion.
- ACL metadata filter trước content fetch.
- DLP cho cả câu hỏi và evidence.
- Grounding theo factual unit, không chỉ đoạn văn.
- Citation gắn source/version/locator/evidence.
- Honest-null và gap routing khi thiếu bằng chứng.
- Provider timeout, repair giới hạn và không để call treo request.

Giới hạn cần nói rõ:

- Embedding local 64 chiều hiện dùng để chứng minh functional contract, **không phải** tuyên bố chất lượng semantic production.
- Company SOT thật chưa được activate.
- Ask UI hoàn chỉnh và shared Evidence Rail thuộc TIP-011.

### Document Operating System

- Registry template và template version bất biến.
- Import chặn macro, OLE, ActiveX, executable, external relationship và ZIP abuse.
- Field typed/bounded; không eval và không expression tùy ý.
- Locked fact chỉ lấy từ SOT active, không fallback literal.
- Render manifest đóng băng template checksum, renderer version, input, SOT revision và evidence checksum.
- Render tất định DOCX/XLSX/PPTX/PDF.
- Output đi qua Files/rendition/policy plane hiện có.
- Preview, rerender và lịch sử generated version.
- Draft watermark cho official/legal.
- Separation of duties: requester không tự approve.
- Approval gắn exact checksum; issuance once-only; revocation giữ lịch sử.

---

## 7. Requirement coverage hiện tại

Blueprint có 34 REQ-ID. Trước TIP-013 chưa nên tuyên bố final coverage, nhưng tổng hợp hiện tại cho thấy:

- **23 yêu cầu lõi đã có implementation end-to-end đáng tin cậy:** REQ-001…004, 006…011, 013…019, 021…025 và 028.
- **9 yêu cầu đã có foundation nhưng chưa hoàn tất ở cấp product/production:** REQ-005, 012, 020, 026, 027, 029, 030, 031, 032.
- **2 yêu cầu còn chủ yếu nằm ở TIP tiếp theo:** REQ-033 Research Adapter và REQ-034 Coverage/Freshness/Gap Dashboard.

Các con số này là **cumulative engineering assessment** tại ngày 01/08/2026. TIP-013 phải lập lại matrix 34/34 bằng scenario thật trước go-live.

---

## 8. Dữ liệu và tài sản tri thức

Những tài sản đã được nhận diện:

- SOT/kernel registry, obligations, decision memo, changelog và legal stance.
- Gói L3/leader và disputed queue.
- KnowledgeBase quy mô scan ban đầu khoảng 1.454 file / 1,19 GB.
- Ít nhất 428 PDF, 238 PNG, 218 JPG, 193 Markdown, 71 DOCX, 58 XLSX, 11 PPTX và 38 WebP trong kho được scan.
- Kho research/kernel ngoài SOT có khoảng 587 record ngành.
- TheSkyWatch có hơn 500 UAV, gần 300 nhà sản xuất và hàng trăm bài báo theo mô tả của Homeowner.
- Hệ thống nghiệp vụ đã có hoặc được định hướng kết nối: MRP, CRM, HRM, IP, chat nội bộ và Google Workspace.
- Kho đề án, đề tài, hồ sơ hợp tác, proposal, báo cáo và template doanh nghiệp.

Trạng thái thực tế:

- Những tài sản trên **chưa được mass-index trực tiếp vào V2**.
- Live kernel đã được probe read-only và bị chặn publish khi thiếu điều kiện — đúng nguyên tắc fail-closed.
- Test V2 dùng synthetic fixtures; không “hợp pháp hóa” dữ liệu thật bằng test.
- TIP-010 và TIP-013 phải quản trị onboarding, classification, provenance repair, curator approval và regression parity.

---

## 9. Chất lượng kỹ thuật và bằng chứng

### Quy mô repository

- 26 commit trên lịch sử hiện tại.
- 250 file được Git theo dõi.
- Khoảng 15.801 dòng source V2 backend/web theo phép đếm file code hiện tại.
- Khoảng 6.393 dòng backend test và 654 dòng web/browser test.
- 27 artifact TIP cho TIP-001…009.
- Dependency và Docker artifacts làm working directory local lớn khoảng 1,6 GB; đây không phải kích thước source Git.

### Gate gần nhất của TIP-009

- ESLint, TypeScript, Next production build: PASS.
- Vitest: 34 pass.
- Ruff: PASS.
- Strict mypy: 68 source files PASS.
- Backend: 175 pass, 38 skip trong unit/API phase.
- Data integration: 37 pass.
- Policy scenarios: 48.
- Runtime DB denials: 18.
- Document browser flow: 2 pass.
- Container vulnerability scan: zero HIGH/CRITICAL trong phạm vi scan.
- Runtime khi nghiệm thu: migration 0008; API/web/worker/PostgreSQL/Redis/MinIO/ClamAV healthy.

### Trạng thái tại thời điểm viết báo cáo

- Git: `main` đồng bộ `origin/main` trước khi tạo file báo cáo này.
- Working tree ban đầu sạch.
- Docker stack local: không chạy.
- UI `http://127.0.0.1:3000`: không phục vụ.
- API `http://127.0.0.1:8000`: không phục vụ.

Không chạy lại full `make verify` trong lượt tổng kết này; số test phía trên lấy từ Verify Report đã commit của từng TIP. Khi tiếp tục build, TIP kế tiếp phải chạy lại gate phù hợp trên worktree mới.

---

## 10. Những gì chưa được phép tuyên bố

Hiện chưa được tuyên bố rằng:

- ứng dụng đã production-ready;
- toàn bộ nhân viên có thể đăng nhập bằng Google Workspace production;
- toàn bộ KnowledgeBase đã được catalog/index;
- dữ liệu MRP/CRM/HRM/IP đã kết nối live;
- real company SOT và template thật đã activate;
- RAG đã đạt chất lượng semantic trên corpus đại diện;
- hệ thống đã qua load test, DR drill, RPO/RTO và external penetration test;
- accessibility WCAG 2.2 AA và Việt/Anh đã đạt trên toàn sản phẩm;
- hệ thống đã có forecasting/partner recommendation/policy proposal tự động;
- agent đã được cấp quyền hành động vào ERP/CRM/chat/workspace.

Các nội dung trên là phần còn lại của roadmap, không phải lỗi che giấu.

---

## 11. Rủi ro lớn nhất từ đây tới đích

| Rủi ro | Mức | Kiểm soát cần có |
|---|---|---|
| Dữ liệu thật nhiều phiên bản, provenance không đồng đều | Cao | Curator queue, conflict/freshness policy, batch onboarding |
| Research lẫn với company fact | Cao | Trust-zone label và graduation gate trong TIP-010 |
| UX chia thành Files/Documents/API thay vì một cửa ngõ | Cao | TIP-011 unified shell + shared Evidence Rail |
| Production ingress, secret, quota và observability chưa đóng | Cao | TIP-012 hardening và SLO/load/security gate |
| Test synthetic không phản ánh ngôn ngữ/corpus thật | Cao | Representative evaluation set trong TIP-013 |
| Migration làm thay đổi kết quả so với pilot | Cao | Parity suite và rollback |
| Cấp quyền agent/action quá sớm | Cao | Approval, least privilege, idempotency, audit và rollback; action phase sau |
| Chi phí vận hành multimedia/LLM tăng khó kiểm soát | Trung bình–cao | Quota, routing, caching, job budget và metrics |
| Phụ thuộc knowledge owner/curator | Trung bình–cao | Ownership SLA, gap/freshness dashboard, escalation |

---

## 12. Kế hoạch tiếp theo

### TIP-010 — Governance & Research

Mục tiêu:

- Curator/Admin workflow.
- Gap queue, freshness, conflict và review SLA.
- Research registry và Refinery adapter.
- Graduation policy từ external evidence sang candidate claim.
- Dashboard coverage/freshness/gaps dựa trên dữ liệu sống.

Điều kiện thắng: **research có thể làm giàu suy luận nhưng không bao giờ tự biến thành sự thật RtR.**

### TIP-011 — Unified UX

Mục tiêu:

- Một shell cho Ask, Files, Documents, SOT, Gaps, Audit và Admin.
- Evidence Rail dùng chung.
- File-scoped Ask và citation mở đúng locator.
- Keyboard-first, responsive, axe/WCAG, reduced motion.
- Việt/Anh và trạng thái trust nhất quán.

Điều kiện thắng: người dùng cảm nhận đây là **một sản phẩm**, không phải ba module ghép lại.

### TIP-012 — Production Hardening

Mục tiêu:

- Reverse proxy HTTPS và security headers production.
- Secret management, quota, rate/body/cost limits.
- Metrics, trace, alert, audit export và incident runbook.
- CI/CD, migration gate, container/image policy.
- Load/performance test, backup/restore/rollback drill.
- SLO, RPO và RTO được đo.

Điều kiện thắng: hệ thống thất bại có kiểm soát, quan sát được và phục hồi được.

### TIP-013 — Migration, Pilot & Final Verify

Mục tiêu:

- Onboard SOT/template/dataset thật theo batch có curator.
- Regression parity với V1.
- Evaluation set đại diện cho nghiệp vụ RtR.
- Staged pilot theo nhóm quyền.
- Final 34/34 REQ matrix.
- Zero P0/P1, danh sách deferred P2/P3 minh bạch.
- Go/no-go và rollback decision.

Điều kiện thắng: **không chỉ chạy được, mà chứng minh được đúng, an toàn và hữu ích với dữ liệu thật.**

---

## 13. Timeline tổng

| Giai đoạn | Thời điểm | Trạng thái |
|---|---|---|
| Content pipeline, SOT packs, pilot V1 | 27–28/07/2026 | Hoàn thành baseline |
| Security containment và Blueprint V2 | 30/07/2026 | Hoàn thành |
| Platform, identity, data, ingestion | 30/07/2026 | TIP-002…005 VERIFIED |
| SOT publish, RAG, Files | 31/07/2026 | TIP-006…008 VERIFIED |
| Document Operating System | 31/07/2026 | TIP-009 VERIFIED |
| Enterprise Intelligence Atlas | 31/07/2026 | PDF 16 trang đã commit |
| Governance/Research | Sau 01/08/2026 | TIP-010 tiếp theo |
| Unified UX | Sau TIP-010 hoặc song hành có kiểm soát | TIP-011 |
| Production hardening | Sau TIP-010/011 | TIP-012 |
| Migration/pilot/final go-live review | Mốc cuối | TIP-013 |

Không nên hứa ngày go-live cố định trước khi TIP-010 xác định khối lượng dữ liệu phải curate và TIP-012 đo hạ tầng thật. Ước lượng hợp lý:

- **Bản pilot production-like:** 4–6 tuần nếu có data owner và hạ tầng sẵn.
- **Rollout nội bộ có kiểm soát:** 6–10 tuần.
- **Nền Intelligence OS kết nối ERP/CRM/HRM/IP và research loop:** roadmap nhiều quý, triển khai theo domain.

---

## 14. Giá trị doanh nghiệp nếu hoàn thiện

### Hiệu quả vận hành

- Giảm thời gian tìm file, đọc, đối chiếu và soạn lại.
- Giảm sai version, sai fact và dùng tài liệu không đúng quyền.
- Tạo report/form/hồ sơ từ fact chuẩn nhanh và lặp lại được.
- Giữ tri thức khi người thay đổi vai trò hoặc rời công ty.

### Quản trị và rủi ro

- Mỗi kết luận quan trọng truy được về evidence.
- Biết ai được xem, dùng, duyệt và phát hành.
- Giữ audit trail cho AI output và hành động.
- Phân biệt rõ fact, claim, research, forecast và private context.

### Tăng trưởng

- Nhận biết tín hiệu ngành và cơ hội sớm hơn.
- Kết nối sản phẩm/năng lực RtR với đối tác phù hợp.
- Rút ngắn account brief, proposal và policy/industry report.
- Tạo vòng lặp từ signal → hypothesis → evidence → opportunity → proposal → outcome → learning.

### Tài sản chiến lược

Nếu kết nối MRP, CRM, HRM, IP, Workspace và chat nội bộ, Copilot trở thành lớp trí nhớ và điều phối nằm **trên** các system of record:

- ERP giữ giao dịch.
- CRM giữ quan hệ.
- HRM giữ con người/năng lực.
- IP giữ tài sản trí tuệ.
- Chat giữ trao đổi.
- SOT giữ sự thật.
- Copilot thống nhất truy cập, suy luận, bằng chứng và workflow.

Đây là giá trị vượt xa tổng giá trị của từng ứng dụng riêng lẻ.

---

## 15. Quyết định khuyến nghị của Tổng công trình sư

1. **Tiếp tục đúng Task Graph, bắt đầu TIP-010.**
2. Không mở rộng thêm feature “hấp dẫn” trước Governance và Unified UX.
3. Chỉ onboarding dữ liệu thật theo batch có owner, classification và provenance.
4. Giữ V1 read-only làm oracle cho đến khi TIP-013 chứng minh parity.
5. Chưa cấp quyền agent ghi vào ERP/CRM/HRM/IP; chỉ thiết kế contract và approval.
6. Chọn một nhóm pilot có câu hỏi thật, hồ sơ thật và quyền khác nhau.
7. Đo năm chỉ số: time-to-evidence, answer grounded rate, honest-null quality, document cycle time và leakage/authorization failures.
8. Chỉ gọi sản phẩm “production-ready” sau TIP-012 và TIP-013.

**Kết luận cuối:** RtR Copilot hiện là một nền tảng có chiều sâu kỹ thuật và luận điểm sản phẩm khác biệt. Phần lõi khó nhất — sự thật, quyền, bằng chứng, file và tài liệu có quản trị — đã được dựng. Khoảng cách còn lại không nằm chủ yếu ở việc thêm code, mà ở governance dữ liệu thật, hợp nhất trải nghiệm, hardening vận hành và chứng minh giá trị qua pilot.

---

## 16. Bản đồ tài liệu chuẩn

- Product requirements: [`PRD_RtR_Copilot.md`](./PRD_RtR_Copilot.md)
- Kế hoạch V1: [`KE_HOACH_BUILD_RtR_Copilot.md`](./KE_HOACH_BUILD_RtR_Copilot.md)
- Scan/RRI V2: [`vibecode_v2/01_SCAN_RRI_REPORT.md`](./vibecode_v2/01_SCAN_RRI_REPORT.md)
- Blueprint V2: [`vibecode_v2/02_BLUEPRINT_RTR_COPILOT_V2.md`](./vibecode_v2/02_BLUEPRINT_RTR_COPILOT_V2.md)
- Task Graph: [`vibecode_v2/03_TASK_GRAPH.md`](./vibecode_v2/03_TASK_GRAPH.md)
- V2 operations: [`v2/README.md`](./v2/README.md)
- TIP audit trail: [`vibecode_v2/`](./vibecode_v2/)
- Enterprise Intelligence Atlas: [`docs/enterprise-intelligence-atlas/`](./docs/enterprise-intelligence-atlas/)

---

*Báo cáo này là snapshot tại ngày 01/08/2026. Khi một TIP mới được VERIFIED, cần cập nhật phần trạng thái, requirement coverage, risk và timeline; không sửa ngược Verify Report lịch sử.*
