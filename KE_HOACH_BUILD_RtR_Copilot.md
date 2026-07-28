# Kế hoạch build RtR Copilot

## Vibecode Blueprint · Phase 0-1 · content pipeline trước, code sau

**Phiên bản:** 1.0 · 27/07/2026
**Vai trò:** Lâm = Homeowner (quyết) · Claude Chủ thầu = thiết kế + điều phối · Claude Thợ = thực thi từng TIP
**Phương pháp áp:** Vibecode Kit v6.1 (workflow) + Refinery v1.2 (cào lọc nguồn phân tán) + registry-hygiene v1.2 (tổ chức SOT)
**Cross-link:** PRD_RtR_Copilot.md v1.1 · Design DNA Playbook v1.0 · kernel DOCTRINE_1PAGE v1.5
**Trạng thái:** BLUEPRINT chờ Homeowner APPROVED

---

## 1. SCAN REPORT · bản đồ toàn bộ nguồn thông tin RtR

Khảo sát 8 thư mục được cấp quyền ngày 27/07/2026. Kết quả phân thành bốn vùng theo độ sạch:

### Vùng A · SOT chuẩn đã có (nguồn vàng · dùng ngay)

| Nguồn | Nội dung | Trạng thái |
|---|---|---|
| `RtR/kernel/registry/` | 76 capabilities có provenance (HC/SC/OC/STRAT) | Sạch · có provenance_level |
| `RtR/kernel/obligations/` | 21+ obligations pháp lý VN + standards | Sạch |
| `RtR/kernel/_dist/decisions/` | 17 decision memo có signoff (D3..COPILOT-01) | Sạch |
| `RtR/kernel/_dist/SPEC_CHANGELOG.md` | Lịch sử spec change có ngày | Sạch |
| `RtR/kernel/_dist/legal/` | CEO stance · AI high-risk · procurement framework | Sạch · tier A |
| `RtR/kernel/insights/` | 6 insight tier P (L2 · KHÔNG vào L3) | Sạch · access-controlled |
| `RtR/kernel/signals-pipeline/` | ~640 records JSONL 10 pipeline (đa số INT · lọc kỹ) | Sạch · phần lớn L2 |

### Vùng B · tài liệu sống chưa vào kernel (mỏ fact L3 · cần cào lọc)

| Nguồn | Nội dung ước tính | Fact L3 tiềm năng |
|---|---|---|
| `rtr-website/` (Product description, Branding, brochures) | Mô tả sản phẩm public, brand assets, media | Cao · gần như toàn bộ là L3/L4 |
| `XPO26/` (Product description V2, booth handbook, equipment list) | Spec sản phẩm bản triển lãm, company card, team profiles | Cao · cần đối chiếu kernel vì có thể stale |
| `KnowledgeBase/` decks + factsheet + hồ sơ | Deck EVN/QN/HP/DN/BQP, fact-sheet báo chí, hồ sơ CNCL/Vinatea | Trung · số đã có trong kernel, deck là derived |
| `KnowledgeBase/Sales_Brief_System/` + `RtR_Maintenance_CRM/` | Quy trình sales + chương trình bảo dưỡng 8 sản phẩm | Cao · quy trình nội bộ là đúng loại fact L3 |
| `rtr-news/` (The Sky Watch) | Báo cáo golive, hợp đồng CMS, dự toán hạ tầng | Trung · project delivery facts |
| `_output/` (project_HaiPhong) | Deck các phiên bản | Thấp · derived artifacts, không phải nguồn fact |
| `RtR/SOT/HOSO_CEO_TRICH_TU_6DA.xlsx` | Hồ sơ CEO (1 file lạc chỗ) | Cao cho mục "về công ty" · cần Lâm xác nhận rồi nạp kernel |

### Vùng C · sản phẩm phần mềm nội bộ (fact hệ thống · mỏ riêng)

`RtR/crm` · `RtR/ip` · `RtR/rtr-mrp` · `RtR/rtr-pm` · `RtR/rtr-simulator` · `RtR/rtr-twin` · `RtR/controltower` · `RtR/rtr-quanlyduan` · `RtR-QA/`

Điểm quý: hầu hết có sẵn `PROJECT_XRAY.md` (chuẩn Vibecode). Nhân viên sẽ hỏi "công ty có tool gì, ai phụ trách, dùng thế nào" nên mỗi hệ thống cần đúng MỘT fact card L3: tên, mục đích, trạng thái, owner, link hướng dẫn. Không cần cào sâu code.

### Vùng D · loại khỏi phạm vi

`_archive-vieterp-fork` · `_server-backup` · các bundle git · file .bak · `Lâm/` (trống) · `Logs/`. Không cào. Ghi rõ để khỏi ai thắc mắc.

**Phát hiện quan trọng từ SCAN:** nguy cơ lớn nhất không phải thiếu thông tin mà là THỪA phiên bản. Cùng spec Hera tồn tại ở kernel (chuẩn, 14 kg), XPO26 Product description V2 (chưa rõ ngày), brochure website cùng các deck cũ (15 kg). Pipeline vì vậy phải là pipeline ĐỐI CHIẾU chứ không phải pipeline GOM: kernel luôn thắng, mọi nguồn khác chỉ được bổ sung fact kernel chưa có hoặc bị đánh disputed.

---

## 2. VISION · kiến trúc content pipeline

```
       Vùng B + C (phân tán · nhiều phiên bản)
                      |
        [TIP-1..4 · CÀO LỌC theo Refinery discipline]
        snapshot path + evidence verbatim + tier
                      |
              so khớp với KERNEL (Vùng A)
             /                |               \
   trùng kernel          kernel chưa có      mâu thuẫn kernel
   → bỏ (kernel thắng)   → fact ứng viên     → DISPUTED queue
                              |                    |
                    [TIP-5 · registry-hygiene]   đẩy leader/Lâm
                    guard → fill → split         xác nhận từng ca
                    6 cổng + access check        (không tự resolve)
                              |
                    Lâm duyệt batch (curator)
                              |
                       NẠP KERNEL (fact mới tier L3)
                              |
                    [TIP-6 · l3_export.py · publish gate]
                    lọc tier L3 · gắn mã record · format
                              |
                        GÓI L3 v1.0
                              |
                    [TIP-7 · Claude Project setup]
                    system prompt NT-1..5 + gói L3
                              |
                    [TIP-8 · red-team + pilot]
```

Ba nguyên tắc vay từ ba phương pháp:

- **Refinery cho Vùng B/C:** mỗi fact trích ra phải kèm đường dẫn file nguồn + đoạn verbatim (evidence_span). File nội bộ nhiều phiên bản được đối xử đúng như nguồn web độ sạch thấp: không tin file nào tự nhận là mới nhất, mâu thuẫn giữ disputed. Điểm khác duy nhất so với refinery web: có trọng tài là kernel.
- **registry-hygiene cho khâu nạp:** fact ứng viên đi qua guard/fill/split + 6 cổng trước khi vào kernel. Access check chặn field L2 lọt vào L3 (chặn kiểu USAFA pricing lọt vào gói nhân viên).
- **Vibecode cho toàn cục:** mỗi khối việc là một TIP có acceptance criteria đo được, Thợ nộp Completion Report, Chủ thầu VERIFY, Homeowner chỉ quyết ở 4 checkpoint.

## 3. TASK GRAPH · 8 TIP

```
TIP-0 ──> TIP-1 ──┬──> TIP-5 ──> TIP-6 ──> TIP-7 ──> TIP-8
          TIP-2 ──┤        ^
          TIP-3 ──┤        |
          TIP-4 ──┴────────┘
(TIP-1..4 chạy song song sau TIP-0)
```

| TIP | Việc | Acceptance criteria chính | Ước lượng |
|---|---|---|---|
| **TIP-0** | Khung L3 + schema fact card + DISPUTED queue format. Draft danh mục L3 1 trang trình CEO | Schema YAML có đủ field (id, content, source_path, evidence_span, tier đề xuất, owner, effective_date) · danh mục L3 draft xong | 0,5 ngày |
| **TIP-1** | Cào lọc `rtr-website/` + `XPO26/` (product + brand + company facts) | Mỗi fact có evidence_span verbatim + source_path · 100% đối chiếu kernel · output 3 nhóm: trùng/mới/disputed | 1 ngày |
| **TIP-2** | Cào lọc `KnowledgeBase/` (quy trình sales, maintenance program, hồ sơ, fact-sheet) | Như TIP-1 · thêm flag "derived artifact" cho deck (không cào số từ deck, chỉ cào quy trình) | 1 ngày |
| **TIP-3** | Cào lọc `rtr-news/` + `_output/` + file lạc `RtR/SOT/` | Như TIP-1 · HOSO_CEO đánh dấu chờ Lâm xác nhận riêng | 0,5 ngày |
| **TIP-4** | Fact card 9 hệ thống phần mềm nội bộ (Vùng C, từ PROJECT_XRAY.md) | 9 card đúng schema · mỗi card có owner (hoặc honest-null chờ điền) | 0,5 ngày |
| **TIP-5** | Chạy registry-hygiene trên toàn bộ fact ứng viên · trình Lâm duyệt batch + DISPUTED queue | guard exit 0 sau fill/split · access check exit 0 · DISPUTED queue có căn cứ hai phía cho từng ca | 1 ngày + thời gian Lâm duyệt |
| **TIP-6** | Script `l3_export.py` + sinh gói L3 v1.0 | Export chỉ chứa tier L3 · 0 field cấm (access check pass) · mỗi fact có mã record · chạy lại cho kết quả y hệt (deterministic) | 1 ngày |
| **TIP-7** | Setup Claude Project "RtR Copilot" · system prompt NT-1..5 · nạp gói L3 · gắn 2 skill template (fact-sheet, sales-brief-fill) | 20 câu hỏi thử: đúng có citation ≥ 16 · honest null đúng cách khi hỏi ngoài gói · 0 câu bịa | 0,5 ngày |
| **TIP-8** | Red-team + mở pilot | Red-team 15 câu moi intel L2 (pricing, USAFA, BQP): 0 câu lộ · nhóm pilot 10-15 người nhận hướng dẫn 1 trang | 0,5 ngày + 4 tuần pilot đo metric PRD |

Tổng công Chủ thầu + Thợ: khoảng 6-7 ngày làm việc rải trên 2 tuần (vì có các điểm chờ Homeowner).

## 4. Checkpoint Homeowner (chỉ 4 điểm cần bác quyết)

| # | Checkpoint | Sau TIP | Bác quyết gì |
|---|---|---|---|
| C1 | Duyệt Blueprint này + danh mục L3 draft | TIP-0 | APPROVED để chạy TIP-1..4 · danh mục L3 trình CEO |
| C2 | Duyệt batch fact mới + xử DISPUTED queue | TIP-5 | Fact nào vào kernel · ca mâu thuẫn nào theo bên nào (có thể uỷ quyền từng phần cho leader) |
| C3 | Duyệt gói L3 v1.0 trước khi nạp bot | TIP-6 | Soi lần cuối: có gì trong gói mà bác không muốn toàn công ty thấy không |
| C4 | Kết quả red-team + go/no-go mở pilot | TIP-8 | Mở cho nhóm pilot hay siết thêm |

## 5. Rủi ro riêng của pipeline này

| Rủi ro | Giảm nhẹ |
|---|---|
| Cào từ deck cũ nhiễm số stale vào L3 (vd 15 kg) | Luật kernel-thắng: số nào kernel đã có thì nguồn khác không được ghi đè, chỉ được vào DISPUTED nếu nghi kernel sai |
| DISPUTED queue phình to làm C2 nặng | Ước trước: phần lớn mâu thuẫn là phiên bản cũ, xử theo lô "kernel thắng trừ khi có bằng chứng mới hơn" · chỉ ca thật sự khó mới lên bàn bác |
| Fact L2 lọt gói L3 | access check của registry-hygiene chạy máy, không lọc tay · red-team TIP-8 là lớp thứ hai |
| Hồ sơ CEO trong file lạc nhạy cảm | Xử riêng ngoài batch, bác đọc trước, quyết tier từng dòng |
| Pilot dùng thử rồi bỏ | Đã có metric + gate trong PRD section 4 · không lặp lại ở đây |

## 6. Điều kiện bắt đầu

Blueprint này cần một chữ **APPROVED** từ Homeowner. Sau đó Chủ thầu phát TIP-0 ngay, TIP-1..4 chạy song song từ ngày hôm sau. Điểm chờ ngoài tầm kiểm soát duy nhất: CEO duyệt danh mục L3 (checkpoint C1, quyết định số 2 trong PRD).

---

*Tuân thủ Vibecode v6.1: Blueprint là khế ước, sau APPROVED không đổi kiến trúc pipeline, muốn đổi quay lại Vision. Mọi TIP nộp Completion Report, sàn audit trail giữ nguyên.*
