# PRD · RtR Copilot

## Trợ lý tri thức nội bộ trên nguồn sự thật duy nhất

**Phiên bản:** 1.1 · 27/07/2026 (v1.0 26/07 · v1.1 chốt tên sản phẩm + gắn Design DNA Playbook)
**Tên sản phẩm:** RtR Copilot (tên giao tiếp nội bộ: Trợ lý RtR)
**Product owner:** Nguyễn Cảnh Lâm · AI Officer · SOT curator
**Trạng thái:** Draft chờ duyệt
**Người đọc:** CEO/CTO (duyệt) · Leaders phòng ban (cung cấp fact) · Engineering (Phase 2)
**Tài liệu đi kèm:** `RtR_Copilot_UIUX_Design_DNA_Playbook_v1.0.md` (hợp đồng thiết kế Phase 2) · `RtR_Copilot_Mockup_Aligned_v2.html` (mockup canonical)

---

## 1. Vấn đề

### 1.1 Hiện trạng

Thông tin RtR đang phân tán theo phòng ban. Cùng một câu hỏi (spec Hera bản hiện hành, giá niêm yết, trạng thái chứng nhận, quy trình mua sắm nội bộ) nhận được câu trả lời khác nhau tuỳ hỏi ai và hỏi khi nào. Các phiên bản tài liệu không đồng nhất, không có cơ chế nào đảm bảo tính duy nhất của fact.

Hệ quả đo được:

- Spec cũ lọt vào tài liệu gửi khách (đã xảy ra: payload 15 kg cũ tồn tại song song 14 kg hiện hành trước khi SOT sync).
- Nhân viên mới mất nhiều tuần để biết hỏi ai về việc gì.
- Leader trả lời lặp lại các câu hỏi giống nhau thay vì làm việc chuyên môn.
- Không có audit trail: khi số sai lọt ra ngoài, không truy được nguồn phát.

### 1.2 Cái đã có

RtR đã có kernel SOT (v1.1+, EXECUTING từ 06/2026): registry capabilities có provenance, obligations pháp lý, decision log, spec changelog, publish gate hai-mặt-một-engine với access tier L1/L2/L4. Kernel đang phục vụ tốt cấp leadership và pursuit khách hàng.

Cái chưa có: kênh để toàn bộ nhân viên tiếp cận phần an toàn của kernel và cơ chế thu thập fact có khuôn từ leaders.

### 1.3 Phát biểu vấn đề

> Nhân viên RtR không có một nơi duy nhất để hỏi và nhận câu trả lời đúng, có nguồn, về thông tin chung của công ty. Leaders không có kênh có khuôn để đưa fact vào nguồn sự thật.

---

## 2. Sản phẩm

### 2.1 Một câu

Trợ lý RtR là chatbot nội bộ cho toàn bộ nhân viên: đăng nhập, hỏi bất kỳ thông tin chung nào của công ty, nhận câu trả lời duy nhất có citation từ SOT, đồng thời yêu cầu tạo file theo template chuẩn với preview trực tiếp trong giao diện.

### 2.2 Nguyên tắc kiến trúc bất biến

**NT-1 · Bot là VIEW của kernel, không phải kho mới.** Bot chỉ đọc từ gói tri thức do publish gate của kernel xuất ra. Không bao giờ đọc file thô, folder phòng ban, hay tài liệu upload trực tiếp. Vi phạm nguyên tắc này thì sản phẩm trở thành nguồn phân tán thứ N+1 có loa khuếch đại.

**NT-2 · Honest null.** Kernel chưa có fact thì bot trả lời "chưa có trong SOT" kèm đầu mối phụ trách, không suy đoán. Câu không trả lời được tự động thành gap signal.

**NT-3 · Mọi câu trả lời có citation.** Mỗi câu trả lời kèm mã record kernel (ví dụ HC-001 · SPEC-SYNC-02) để người nghi ngờ tra ngược được.

**NT-4 · Sinh file bằng script, không bằng LLM.** LLM extract tham số từ hội thoại, script deterministic render file từ template (pattern sales-brief-fill đã chứng minh). LLM không tự vẽ format.

**NT-5 · Một curator.** Chỉ SOT curator (Lâm) có quyền nạp fact vào kernel. Leaders đề xuất qua phiếu fact, không nạp trực tiếp.

### 2.3 Người dùng

| Persona | Nhu cầu chính | Ví dụ |
|---|---|---|
| Nhân viên mọi phòng ban | Hỏi thông tin chung, đúng, nhanh | "Spec Hera hiện tại?" · "Quy trình xin công tác phí?" · "FCC exemption là gì?" |
| Sales / BD | Tạo file theo template + fact đúng | "Tạo fact-sheet gửi khách X" · "Điền sales brief từ note này" |
| Leaders | Đưa fact vào SOT ít tốn công | Điền phiếu fact 5 phút hoặc voice note |
| SOT curator (Lâm) | Thu thập, kiểm, nạp, xuất bản | Vòng nạp 5 bước · gap list hàng tuần |
| CEO/CTO | Đảm bảo intel nhạy cảm không rò | Access tier enforce + audit log |

---

## 3. Kiến trúc tổng thể

### 3.1 Sơ đồ luồng dữ liệu

```
[Leaders] --phiếu fact / voice note--> [Curator (Lâm)]
                                          |
                                    gate kiểm (đối chiếu · provenance · tier)
                                          |
                                      [KERNEL SOT]
                                 (registry · obligations ·
                                  decisions · spec changelog)
                                          |
                                    publish gate (script)
                                          |
              +---------------------------+---------------------------+
              |                           |                           |
        [Gói L1/L2]                 [Gói L3 · MỚI]                [Gói L4]
     (leadership · như cũ)      (employee-safe pack)           (public · như cũ)
                                          |
                                   [TRỢ LÝ RTR (bot)]
                                          |
              +---------------------------+---------------------------+
              |                           |                           |
        Hỏi đáp có citation        Template service            Gap signals
        (RAG trên gói L3)       (script render file)         (câu chưa trả lời được)
              |                           |                           |
        [Nhân viên]                [File + preview]          --> quay về [Curator]
```

### 3.2 Tầng truy cập · thêm L3

| Tier | Ai | Nội dung | Ví dụ được / không được |
|---|---|---|---|
| L1 | CEO/CTO + curator | Toàn bộ, gồm INT nhạy cảm nhất | Mọi thứ |
| L2 | Leadership | L3 + pricing intel + pursuit detail + insight library | Deal USAFA, giá vốn: được |
| **L3 (mới)** | **Toàn bộ nhân viên** | **Fact chung đã kiểm: spec sản phẩm hiện hành, mốc pháp lý công khai, quy trình nội bộ, lịch sử công ty, org chart, chính sách** | Spec Hera 14 kg: được · Giá quote USAFA: KHÔNG · Contact BQP: KHÔNG · Pricing intel đối thủ: KHÔNG |
| L4 | Public | Chỉ tier A/B đã công bố | Như hiện tại |

Quy tắc xếp tier mặc định: fact mới vào kernel mặc định L2, curator chủ động hạ xuống L3 khi xác nhận an toàn cho toàn công ty. Không bao giờ tự động thăng tier.

### 3.3 Bốn khối chức năng

**Khối 1 · Hỏi đáp có căn (RAG trên gói L3)**

- Input: câu hỏi tự nhiên tiếng Việt (hoặc Anh).
- Retrieval trên gói L3 (fact đã đánh mã record).
- Trả lời kèm citation mã record + ngày hiệu lực của fact.
- Không tìm thấy thì honest null: "SOT chưa có thông tin này. Đầu mối: [owner theo domain map]. Câu hỏi đã được ghi nhận."
- Fact có ngày hiệu lực cũ hơn ngưỡng (ví dụ spec quá 90 ngày chưa reconfirm) thì kèm nhãn "cần xác nhận lại".

**Khối 2 · Template service (sinh file)**

- Danh mục template chuẩn: fact-sheet, sales brief, công văn nhà nước, đề xuất pilot, báo giá khung, biên bản họp. Mỗi template một cặp: schema tham số + script render (pattern fill_brief.py).
- Flow: người dùng yêu cầu → LLM extract tham số từ hội thoại → hỏi phần thiếu (fail-loud, không bịa) → script render docx/xlsx/pdf → preview trong giao diện → người dùng tải hoặc sửa tham số render lại.
- Số liệu trong file lấy từ gói L3, không cho phép người dùng inject số tự do vào field fact (ví dụ payload Hera là giá trị từ SOT, không phải tham số tự điền).

**Khối 3 · Vòng nạp fact (curator pipeline)**

- Phiếu fact chuẩn cho leaders: nội dung · nguồn (văn bản, quyết định, phép đo) · ngày hiệu lực · tier đề xuất · người chịu trách nhiệm. Dạng docx in được + form nhắn nhanh + voice note (skill extract theo pattern sales-brief-fill).
- Gate kiểm của curator: đối chiếu mâu thuẫn với record hiện có (mâu thuẫn thì đẩy ngược hai leader liên quan, không tự resolve) · đủ provenance · tier hợp lý.
- Nạp kernel có signoff (người nạp, người cung cấp, ngày).
- Publish gate chạy lại → gói L3 mới → bot cập nhật.

**Khối 4 · Vòng phản hồi gap**

- Mọi câu bot không trả lời được ghi vào gap log (câu hỏi, người hỏi, tần suất).
- Hàng tuần curator nhận gap list xếp theo tần suất: đây là lịch thu thập fact tiếp theo.
- Metric phụ: fact nào được hỏi nhiều nhất (biết cái gì đáng đầu tư viết kỹ), fact nào bị hỏi lại sau khi trả lời (dấu hiệu trả lời chưa rõ).

---

## 4. Lộ trình ba phase

### Phase 0 · Governance (tuần 1-2 · không code)

| Việc | Owner | Đầu ra |
|---|---|---|
| Định nghĩa tier L3 + duyệt danh mục nội dung employee-safe | Lâm + CEO | Văn bản 1 trang, CEO ký |
| Domain map: fact domain nào thuộc leader nào | Lâm + leaders | Bảng owner (sản phẩm: CTO · pháp lý: pháp chế · HR: HR lead · sales: Khanh Vo...) |
| Phiếu fact chuẩn | Lâm (em build) | Docx + form + skill voice extract |
| Đợt thu thập fact đầu tiên (ưu tiên: spec sản phẩm, quy trình nội bộ, chính sách HR, lịch sử mốc công ty) | Lâm đi gặp leaders | 50-100 fact L3 đầu tiên vào kernel |
| Script publish gate xuất gói L3 | Em build | l3_export.py · lọc tier + format có mã record |

**Gate ra Phase 1:** gói L3 đầu tiên tồn tại với tối thiểu 50 fact có provenance, CEO duyệt danh mục L3.

### Phase 1 · Pilot trên Claude Team (tuần 3-6 · gần như không code)

Setup:

- Claude Team workspace · Project "Trợ lý RtR" · gói L3 nạp vào project knowledge.
- Custom instructions của project = 5 nguyên tắc NT-1 đến NT-5 (bot behavior: citation, honest null, ghi nhận gap).
- 2-3 template skill đầu tiên (fact-sheet, sales brief đã có, công văn nhà nước đã có).
- Nhóm pilot 10-15 người trộn phòng ban, không chỉ người quen AI.

Đo trong 4 tuần:

| Metric | Ngưỡng đạt |
|---|---|
| Số câu hỏi / tuần | Tăng qua từng tuần (nhu cầu thật) |
| Tỷ lệ trả lời được từ gói L3 | Từ 60% tuần 1 lên 80% tuần 4 (nhờ vòng gap) |
| Tỷ lệ câu trả lời bị người dùng báo sai | Dưới 2% · mỗi ca báo sai là một sự cố phải trace |
| Số file sinh từ template / tuần | Có người dùng lặp lại (không chỉ thử một lần) |
| Thời gian curator xử lý mỗi fact | Dưới 5 phút |

**Gate ra Phase 2:** usage giữ được sau tuần 3 (không phải hiệu ứng đồ chơi mới), có tối thiểu 3 use case lặp lại hàng tuần, đồng thời giới hạn của Claude Team (quản lý user, audit, tích hợp) thực sự cản trở. Nếu Claude Team đủ dùng thì DỪNG ở đây, không build Phase 2. Tiết kiệm được là thành công, không phải thất bại.

### Phase 2 · Portal riêng (chỉ khi Phase 1 chứng minh cần · 2-3 tháng · 1-2 engineer)

Chỉ build khi có ít nhất một trong các lý do: cần SSO với hệ thống nội bộ, cần audit log chi tiết per-user, cần phân quyền theo phòng ban mịn hơn project membership, cần tích hợp CRM/ERP, hoặc số user vượt mức seat license hợp lý.

**Hợp đồng thiết kế đã sẵn:** `RtR_Copilot_UIUX_Design_DNA_Playbook_v1.0.md` là design contract pixel-precise cho Phase 2 (shell 236px sidebar + header 76px + evidence dock 356px · 6 màn hình: Overview, Copilot, Document Studio, Source of Truth, Knowledge Gaps, Audit Trail · trust states · deterministic document UX). Playbook tự xếp thứ tự ưu tiên: nguyên tắc sản phẩm đứng trên playbook, nghĩa là gate Phase 1 → 2 của PRD này vẫn quyết định KHI NÀO build, playbook chỉ quyết định build NHƯ THẾ NÀO. Playbook ghi "LOCKED FOR IMPLEMENTATION" hiểu là khoá spec thiết kế, không phải lệnh khởi công.

Kiến trúc:

| Thành phần | Công nghệ đề xuất | Ghi chú |
|---|---|---|
| Frontend | Web app (Next.js hoặc tương đương) · chat UI + file preview | Preview docx/xlsx: render server-side qua LibreOffice headless ra PDF/ảnh (pattern đã dùng nội bộ) hoặc embed OnlyOffice nếu cần sửa trực tiếp |
| Auth | SSO công ty (Google Workspace / Microsoft) | Map user → tier (mặc định L3, leadership L2) |
| Bot API | Claude API (Sonnet cho hỏi đáp · Haiku cho extract tham số) | System prompt = NT-1..5 + gói L3 làm context/RAG |
| RAG | Embedding store trên gói L3 (theo record, không theo trang) | Mỗi chunk giữ mã record để citation |
| Template service | Python service · registry template (schema + script render) | Tái dùng fill_brief.py pattern · queue render |
| Gap log + analytics | DB đơn giản + dashboard tuần | Đổ gap list cho curator |
| Audit log | Mọi Q&A + file sinh + user + timestamp | Yêu cầu của CEO/CTO cho intel control |

Estimate: 2-3 tháng MVP với 1-2 engineer + chi phí API (ước theo usage Phase 1, quy mô 50 nhân viên hỏi đáp hằng ngày ở mức vài triệu đồng/tháng, cần đo thật ở Phase 1 trước khi cam kết số).

---

## 5. Vòng đời một fact (ví dụ cụ thể)

1. CTO chốt spec màn hình VegaHub 2000 nits trong chat nhóm.
2. Curator nhận, điền phiếu fact (hoặc extract từ chính message), gate kiểm: có mâu thuẫn với HeraHub record cũ dùng chung → tách record, không tự resolve ẩn.
3. Nạp kernel: HC-019 mới, signoff, SPEC_CHANGELOG entry. Tier: L3 (spec sản phẩm an toàn công bố nội bộ).
4. Publish gate chạy → gói L3 bản mới có HC-019.
5. Nhân viên hỏi bot "VegaHub màn bao nhiêu nits?" → "2000 nits, LCD 1280×800, tách khỏi HeraHub từ 16/07/2026 [HC-019 · SPEC-SYNC-02]".
6. Sales dùng template fact-sheet → file sinh ra tự lấy 2000 nits từ gói L3, không ai gõ tay được số khác.

Đây chính xác là chuỗi đã chạy thật trong kernel tháng 7/2026, sản phẩm chỉ thêm bước 5-6 cho toàn công ty.

---

## 6. Rủi ro và giảm nhẹ

| Rủi ro | Mức | Giảm nhẹ |
|---|---|---|
| Bot thành kho phân tán N+1 (ai đó upload tài liệu riêng vào project) | Cao | NT-1 cứng: chỉ curator có quyền sửa project knowledge · kiểm tra định kỳ nội dung project |
| Lộ intel nhạy cảm qua đường hỏi đáp | Cao | Tier L3 duyệt bởi CEO · gói L3 sinh bằng script lọc tier (không lọc tay) · red-team thử moi intel trước khi mở rộng pilot |
| Curator bottleneck / single point of failure | Trung | Phiếu fact + AI extract giảm chi phí mỗi fact xuống dưới 5 phút · quy trình nằm trên giấy · đào tạo 1 backup |
| Hallucination trả lời sai | Trung | NT-2 honest null + NT-3 citation · metric báo sai dưới 2% · mỗi ca sai trace nguồn |
| Nhân viên không dùng (đồ chơi mới 2 tuần rồi bỏ) | Trung | Phase 1 đo usage thật trước khi đầu tư Phase 2 · chọn use case đau thật (spec, quy trình, template) thay vì "hỏi gì cũng được" |
| Fact stale (leader đổi số nhưng không báo) | Trung | Nhãn "cần xác nhận lại" theo ngày hiệu lực · quarterly drift review đã có trong kernel · gap log phát hiện gián tiếp |
| Chi phí API vượt dự kiến | Thấp | Phase 1 đo usage thật · Haiku cho tác vụ extract · cache câu hỏi lặp |

---

## 7. Những gì KHÔNG làm (non-goals)

- Không thay thế giao tiếp người với người cho quyết định. Bot trả fact, không trả lời "tôi nên làm gì".
- Không xử lý dữ liệu cá nhân nhân viên (lương thưởng, đánh giá) trong mọi phase.
- Không cho bot ghi vào kernel. Chiều ghi duy nhất là qua curator.
- Không ghi âm cuộc họp với khách hay với nội bộ để nạp SOT tự động.
- Không build UI custom ở Phase 1 dù rất muốn. Ngứa tay build sớm là rủi ro số một của dự án này.

---

## 8. Định nghĩa thành công

**3 tháng:** 80% câu hỏi thông tin chung được bot trả lời đúng có citation · leaders không còn trả lời lặp các câu hành chính · 100% file khách nhận sinh từ template lấy số từ SOT.

**6 tháng:** gap list hàng tuần dưới 10 câu mới (kernel đã phủ phần lớn nhu cầu) · nhân viên mới onboard tự phục vụ tuần đầu · quyết định Phase 2 có cơ sở dữ liệu thật.

**Thước đo tối thượng:** một con số sai không còn đường lọt vào tài liệu gửi khách, vì mọi con đường sinh tài liệu đều đi qua SOT.

---

## 9. Việc cần quyết để khởi động

| # | Quyết định | Người quyết | Deadline đề xuất |
|---|---|---|---|
| 1 | Duyệt PRD + mô hình curator | CEO | Tuần này |
| 2 | Duyệt danh mục L3 (1 trang) | CEO | Phase 0 tuần 1 |
| 3 | Chốt domain map fact owner | Lâm + leaders | Phase 0 tuần 1 |
| 4 | Chọn nhóm pilot 10-15 người | Lâm | Phase 0 tuần 2 |
| 5 | Claude Team seat cho nhóm pilot | CEO (chi phí) | Trước Phase 1 |
| 6 | Token màu signal: playbook dùng #F0C400 (dark) / #D5AD00 (light) trong khi RtR Executive Dark chuẩn deck dùng #FFD60A. Chốt một trong hai: (a) chấp nhận yellow riêng cho product UI vì màn hình khác in ấn, hoặc (b) thống nhất một token toàn brand | Lâm + design | Trước Phase 2 (không chặn Phase 0-1) |

---

*PRD này tuân theo nguyên tắc kernel: mọi con số trong tài liệu này là ước tính lộ trình (chưa phải cam kết), sẽ hiệu chỉnh bằng dữ liệu đo thật từ Phase 1. Cross-link: kernel `_dist/PROJECT_OVERVIEW.md` · `SALES_BRIEF_SYSTEM.md` · METHOD_SOT_EXTENDED.md.*
