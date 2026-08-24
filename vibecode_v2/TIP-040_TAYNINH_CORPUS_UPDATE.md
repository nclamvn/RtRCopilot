# TIP-040 · Cập nhật tri thức Tây Ninh vào RtR Copilot

**Status:** Phase 1 + 2 DONE (24/08 · kernel f0ab59a · onboard rev3 activated 6/6 · reindex active, l3_facts 125 chunk, specs 11 chunk) · Phase 3 eval cases PENDING · Phase 4 chờ sau chuyến bay 29/8

## Completion Phase 1+2 (24/08/2026)

- Kernel commit `f0ab59a`: 4 file registry, 159 dòng thêm; backup `.bak-2026-08-24-tip040` cạnh từng file; nguồn copy vào `source_canonical/vanban_noibo/` + hash ghi sổ.
- Harness migrate thêm cờ `--revision` (`run_migration.py` + `kernel_adapter.py`) vì tooling gốc ghim revision=1 cho migration lần đầu; ordinal record đi theo revision.
- Onboard: dry-run 6/6 `planned_valid` → activate `revision 3`, `activated_count=6`, ledger `/tmp/tip040/ledger.json`. Revision 2 bị bỏ (tàn dư staged của lần apply fail đầu — vô hại, lifecycle staged).
- Reindex: 6 generation mới ACTIVE rev3. `rtr.l3_facts` 125 chunk (+9), `rtr.specs` 11 chunk (+1).

### Hai món nợ vận hành lộ ra (follow-up)

1. **TIP-040.1 · Worker poison-pill fix:** `ReindexService` bốc hàng outbox cũ nhất; hàng mồ côi (không khớp revision active) ném `ReindexError` nhưng KHÔNG được đánh dấu → chặn đầu hàng đợi vĩnh viễn. Đã gặp và vá thủ công 2 lần bằng SQL (đánh dấu dispatched các hàng test/mồ côi). Bản vá code: mark-dispatched + skip hàng `outbox_not_current_active_revision`, đúng cơ chế đã vá cho `reembed_corpus` hồi TIP-014RE.
2. **TIP-040.2 · Dev DB hygiene:** DB dev còn tàn dư nguồn integration-test 05/08 (outbox + generation active + record các nguồn `gapflip./eval./parity./bench.` v.v. — trước khi harness có clone DB cô lập). Dọn một thể trong gói hygiene riêng.
**Date:** 24/08/2026
**Nguồn mới:** `KnowledgeBase/TayNinh_UAV_2608/` (Bộ ghi hiện trường + khung báo cáo, bay thử nghiệm đợt 2, 25-29/8/2026)
**Nền đã có trong kernel (commit b1a8a62, nạp 24/08):** L3F.REG.001-006 (QĐ 15393 ngày 21/8 + KH 4002 ngày 22/8 + vị thế RtR + guard 100 km), OBLIG.VN.TAYNINH.CHIENLUOC_UAV (loại CƠ_HỘI), OBLIG.VN.TAYNINH.BAYTHUNGHIEM_DOT2 (loại NHIỆM_VỤ, nguồn DỰ THẢO KH của Sở KH&CN chưa số chưa ngày ký)

## 0. Hai phân xử Homeowner 24/08/2026 (ghi sổ)

1. **Tải trọng HERA = 14 kg là số chính thức mới** (spec-mới-thắng).
   `SPEC.HERA.PAYLOAD.MAX` sửa 15 → 14 kg; note ghi quyết định 24/8 + lịch sử
   (15 kg là số cũ, note 23/06 về "14 kg = trọng lượng mang vác" hết hiệu lực cho mục payload).
2. **Thời gian bay: 40 phút ở payload nhiệm vụ thường; 16 phút ở tải tối đa 14 kg — cùng đúng.**
   Record phải mang điều kiện đo tường minh, không để hai số trần cạnh nhau.

## 1. Phase 1 · Registry kernel (TRƯỚC 25/8 · Homeowner áp, dry-run trước theo registry-hygiene)

| # | Việc | Chi tiết |
|---|---|---|
| R1 | Sửa `specs.yaml` payload | `SPEC.HERA.PAYLOAD.MAX`: value 15 → 14, giữ status VERIFIED chỉ khi gắn nguồn quyết định 24/8 (bộ ghi hiện trường trang 1); note cũ 23/06 chuyển thành lịch sử trong note mới. Rà mọi record nhắc "15 kg/33 lb" (SPEC.HERA.SIGNATURE.*, l3_facts, capabilities) — đổi hoặc chú thích số cũ |
| R2 | Thời gian bay | Giữ 56 phút không tải (CAND.1.006 đã có); thêm record 40 phút @ payload nhiệm vụ thường; sửa note `SPEC.HERA.FLIGHT.14KG` (16 phút) ghi rõ "ở tải TỐI ĐA 14 kg" — ba số ba điều kiện, hết mâu thuẫn |
| R3 | Fact đợt bay 2 (L3F.REG.007+) | (a) 5 điểm bay + bài toán của tỉnh từng điểm: Đồng Rùm (nông nghiệp cao su), Cầu Khởi (lặp lại kiểm tính ổn định), Rạch Tây Ninh (trầm tích, lục bình), Trường Chinh (giám sát thi công, ATGT), Láng Sen (cháy rừng, xâm nhập); (b) 6 tiêu chí đánh giá theo mục II.3 KH của Sở; (c) nhiệm vụ RtR + Học viện KTQS theo mục VI.4; (d) khung báo cáo 9 mục theo tiền lệ PTC4 4/2026; (e) mapping sở chủ trì theo KH 4002. **Provenance: nguồn là DỰ THẢO chưa ký → `approved_internal`/`claim`, KHÔNG verified_primary; nâng cấp khi Sở ký bản chính thức** |
| R4 | Guidance nội bộ | Bảng "số liệu chuẩn" + "4 điều không viết vào báo cáo" (100 km; số cũ 15kg/10km/IP43; giá; cam kết chưa CEO duyệt) thành record `approved_internal` — để Copilot trả lời đúng khi nhân viên hỏi trước/trong chuyến đi. Guard 100 km đã có ở L3F.REG.006, thêm cross-ref |
| R5 | Ontology/entities | Alias mới: "Đồng Rùm", "Cầu Khởi", "Rạch Tây Ninh", "Trường Chinh", "Láng Sen", "bay thử đợt 2", "PTC4"/"Truyền tải điện 4", "Học viện Kỹ thuật Quân sự"/"HVKTQS" |
| R6 | source_canonical | Copy `BoGhiHienTruong...pdf/docx` vào `kernel/source_canonical/` + cập nhật `source_hashes.yaml`; khi Sở ký KH chính thức thì thay bản dự thảo |

## 2. Phase 2 · Đưa vào ứng dụng (trong tuần bay)

1. Ingest bộ ghi (docx + pdf) vào corpus Files của app (pipeline quarantine/AV/rendition — clamav đã healthy).
2. SOT publish revision mới từ kernel đã sửa (stage → validate → publish, 3 pha fail-closed).
3. Ontology revision mới với alias R5 → approve → activate; reindex/reembed các record đổi nội dung (generation mới, atomic flip).
4. Kiểm tay 3 câu trên UI: "tải trọng HERA?" (phải 14 kg), "bay thử Tây Ninh khi nào, ở đâu?", "HERA bay được 100 km không?" (phải trả 15 km chính thức + 100 km chỉ là ghi nhận trong văn bản tỉnh).

## 3. Phase 3 · Acceptance chống chép số cũ (cases mới, oracle cam kết trước)

| Case | Câu hỏi | Kỳ vọng |
|---|---|---|
| TN-001 | Đợt bay thử Tây Ninh diễn ra khi nào, ở những điểm nào? | grounded · 5 điểm + 25-29/8 |
| TN-002 | Tải trọng HERA là bao nhiêu? | grounded · **14 kg** · fail nếu trả 15 kg |
| TN-003 | HERA bay ngoài tầm nhìn được 100 km đúng không? | grounded · nêu 15 km là thông số chính thức, 100 km chỉ tham khảo nguồn văn bản tỉnh |
| TN-004 | Sáu tiêu chí đánh giá của Sở là gì? | grounded · đủ 6 tiêu chí mục II.3 |
| TN-005 | Kết quả bay đợt 2 thế nào? | **honest-null trước 29/8** (chưa có dữ liệu) → grounded sau Phase 4 |
| TN-006 | HERA chống nước chuẩn gì? | grounded · IP54 · fail nếu IP43 |

Chạy targeted (`E2E_CASE_IDS=TN-001..006`) — rẻ, không cần full campaign.

## 4. Phase 4 · Sau chuyến bay (từ 29/8)

1. Phiếu điểm bay điền tay → scan/nhập → fact kết quả với `verified_primary` (có dữ liệu bay chứng minh) vào kernel, đúng chỉ dẫn README của chính bộ ghi.
2. Báo cáo gửi Sở (khung 9 mục) → corpus Files + fact tổng hợp.
3. Nâng provenance các fact R3 từ dự thảo lên bản KH đã ký (nếu Sở ký).
4. Chạy lại TN-005 (giờ phải grounded) + TN-001..006 regression.
5. Số đo thực tế (thời gian bay, tầm điều khiển thực địa) đối chiếu bảng chuẩn — lệch thì mở phân xử mới, không sửa im lặng.

## 5. Nguyên tắc giữ xuyên suốt

- Dự thảo chưa ký không bao giờ mang `verified_primary`.
- Số 100 km không vào bất kỳ record spec nào — chỉ tồn tại trong L3F.REG.006 với ranh giới đã ghi.
- Mọi sửa registry: backup + dry-run trước (kỷ luật registry-hygiene), commit kernel repo riêng với message rõ.
