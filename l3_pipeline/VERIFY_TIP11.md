# VERIFY_TIP11 · server hai chế độ + máy tra cứu + 106 record (dấu vết QA/Thợ session)

**Ngày:** 2026-07-27 · **Chuẩn:** chạy thật (test suite + MOCK server live), không tin báo cáo.

## PASS (đã chạy, không chỉ đọc)
- `test_copilot.py`: **26 pass · 0 fail** (chạy thật). Leak scan: 0 nội dung L2 trong gói; Blue UAS không record nào nói "cleared" trần; mọi record 15kg gắn legacy.
- **106 record** (101 + 5 mirror `L3R.K.001-005`). 5 mirror là kernel_refs, KHÔNG fact mới — content trace về fact Lâm đã duyệt (signature 1-4-14, HERA 2.0 US 16kg, VegaHub 2000, legacy 15kg, văn phong NĐ 30/2020). 6 coverage gap đóng.
- **MOCK server chạy thật (không key, 0 cost):** health mode=MOCK 106 record; câu trong gói → record khớp + nhãn MOCK + citation; câu ngoài gói ("giá bán Hera") → honest null + `GAP:` ghi log; search API + record API (evidence dock) trả đúng; passcode sai → 403; bind fail-safe.
- Zip = 10 file, SHA-256 `copilot_server.py`/`GOI_L3.yaml`/`test_copilot.py` zip↔đĩa MATCH.
- Kiến trúc hai chế độ + tab Tra cứu SOT là bổ sung tốt: testable không cần key, và là tính năng production thật (tra số nguyên văn, 0 API cost).

## FINDING · MEDIUM · MOCK trả spec CŨ làm đáp án đầu cho câu spec hiện hành
Chạy thật câu **"HeraHub màn hình bao nhiêu nits?"** ở MOCK:
- Top hit = **CAND.1.007** = "HeraLink v2.0 ... **1200 nits**" — spec đã bị RENAME-01 thay thế. Record này KHÔNG có marker "spec cũ" trong content; dấu duy nhất là `kernel_ref: HC-017 + RENAME-01` (metadata, user không đọc).
- Đáp án hiện hành (**1800 nits**) nằm ở CAND.1.009 nhưng MOCK xếp hạng thấp hơn.
- Rủi ro: user MOCK copy "1200 nits" tưởng hiện hành — đúng loại stale-spec mà cả dự án SOT sinh ra để chặn.
- Chỉ ở **MOCK**. LIVE (LLM đọc cả gói, thấy CAND.1.009 giải thích correction) sẽ trả 1800 đúng. Nhãn MOCK có hedge ("record khớp nhất, không phải câu trả lời AI") nhưng chưa đủ cho câu spec.

**Fix đề xuất (một trong hai):**
1. **Data (cần curator/Lâm):** thêm marker vào content CAND.1.007 kiểu "[SPEC CŨ · HeraLink đã đổi tên HeraHub · độ sáng hiện hành 1800 nits — xem CAND.1.009]" — đúng kỷ luật legacy-marker đã áp cho 15kg (L3R.K.004) nhưng chưa áp cho HeraLink rename.
2. **Code (Thợ làm được ngay):** MOCK retrieval down-rank record có `kernel_ref` chứa `RENAME-01`/legacy, hoặc gắn cảnh báo "có thể là spec cũ — xác nhận bằng LIVE".

## FINDING PHỤ · LOW
- "VEGA nâng được bao nhiêu?" → MOCK honest-null dù record có (CAND.1.010) — từ điển đồng nghĩa thiếu "nâng"→payload/trọng lượng. An toàn (null, không sai) nhưng under-answer.
- "Payload Hera?" → top hit là record thời-gian-bay ("payload 5.7 lb"), 14kg nằm ở hit thứ 2. Ranking hơi thô.

## Kết luận
Data/tooling/test/zip: PASS, cắm key là LIVE done. Kiến trúc hai chế độ vững. Một finding MEDIUM: MOCK có thể phơi spec cũ (HeraLink 1200 nits) làm đáp án đầu cho câu HeraHub — nên áp legacy-marker discipline cho record rename trước khi dựa vào MOCK cho câu spec trong production. LIVE không dính.

---

## VÒNG 2 · cả hai finding ĐÓNG + phát hiện root-cause (re-verify live · 2026-07-27)
- **MEDIUM stale-spec ĐÓNG (re-probe live):** hỏi "HeraHub màn hình bao nhiêu nits?" ở MOCK → top hit giờ là L3R.K.003 hiển thị "HeraHub LCD 1280x800, **1800 nits**"; CAND.1.007 (1200) đã bị down-rank khỏi top + mang marker `[SPEC CŨ · RENAME-01 ... 1800 nits, xem CAND.1.009]` ở ĐẦU content. Fix hai lớp: data (marker, vá sót implementation DISP.002 đã ký) + code (down-rank `[spec cu`/`rename-01`, KHÔNG bắt "legacy" trần để record 15kg vẫn trả lời được).
- **LOW under-answer ĐÓNG:** "VEGA nâng được bao nhiêu?" → giờ trả CAND.1.010 "44 lbs payload" (trước honest-null). + neo entity: hỏi VEGA không còn trả record HERA lên đầu.
- **ROOT CAUSE (build session tự phát hiện, nặng hơn cả 2 finding):** parser gói (custom, vì server zero-dependency không dùng pyyaml) cắt content ở dòng wrap đầu → nội dung dòng 2 của MỌI record folded biến khỏi index. Đây là lý do gốc retrieval yếu, không chỉ 2 triệu chứng QA thấy. Vá: join continuation line vào `_blob`. Retrieval 16/20 → **19/20**. Re-verify live: search "2000 nits vegahub" (nội dung dòng 2) giờ index được.
- **29/29 test pass** (chạy thật), gồm 3 regression test mới khoá đúng 2 finding. Zip 10 file hash MATCH.

**Ghi nhận:** build session không dừng ở việc vá 2 triệu chứng QA báo mà truy ra root cause (parser truncation) — đúng văn hoá "sửa đường ống, không sửa triệu chứng". Finding của QA là cửa vào; root cause sâu hơn.
