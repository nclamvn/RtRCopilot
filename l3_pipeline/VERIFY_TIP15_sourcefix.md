# VERIFY · SPECFIX01 · sửa file nguồn (workbook) + gói + email (dấu vết QA session)

**Ngày:** 2026-07-27 · **Chuẩn:** đọc cell thật + so backup + xác thực finding với kernel + re-probe MOCK live.
**Đây là vòng nặng nhất:** lần đầu MÌNH sửa file nguồn, không chỉ đọc/gắn cờ.

## PASS (verify tận gốc)
- **Backup pre-edit CÓ THẬT:** `_archives/maintenance_workbooks_truoc_SPECFIX01_20260727/` (01 HERA, 02 HeraHub, 09 example). Mở backup 01 → chứa số CŨ (1-4-15, 15kg payload→sai, IP43 "Cần phê duyệt", 10 km "Cần phê duyệt"). Restore point hợp lệ. (QA lần đầu tìm hụt vì search hẹp *.bak — đã rút cảnh báo.)
- **Edit đúng + có vết sửa:** workbook HERA giờ IP54 · 15 km · payload 14 kg · model 1-4-14, status 2 ô chuyển "Cần phê duyệt"→"Source-confirmed", mỗi ô ghi ngày + căn cứ (HC-042/HC-001) + giá trị cũ.
- **Aha finding "10 km = VEGA" — AIRTIGHT:** kernel HC-001 HERA = "range 15 km", HC-002 VEGA = "10 km"; đó là HAI số km DUY NHẤT trong capabilities.yaml. Nên "10 km" trong baseline HERA đúng là số VEGA lẫn sang. Fix →15km chính xác. Giả thuyết "còn chỗ khác lẫn tương tự" có cơ sở.
- **Hai ô CỐ Ý không sửa, gắn cờ đúng:** HeraHub "Tầm truyền 10 km" — note in-file "CẦN XÁC NHẬN 27/07: kernel HERA 15km, VEGA 10km, có thể lẫn · chờ Engineering" + raise email Q2. MTOW 31 vs 30.5 — flag note, không tự sửa. Không đoán khi kernel không có căn cứ (Hub không có số range trong kernel).
- **Gói 108 record**, 3 marker `[SPEC CŨ]` (1 cũ HeraLink + 2 mới IP43/10km dispute-state). **Re-probe MOCK live:** "IP rating Hera?" → IP54 trước + giải thích IP43 cũ; "Tầm Hera?" → 15km trước + giải thích 10km cũ. Không còn phơi số cũ lên đầu.
- **Email viết lại đúng kỷ luật:** từ "hỏi 4 điểm" → "thông báo đã sửa + 3 điểm treo". Bỏ hẳn câu IP43/IP54 (đã chốt). Q2 = cross-contamination, đánh dấu "có giá trị nhất". Cố ý không hỏi lại việc đã chốt để không làm loãng.
- **38/38 test.**

## Chưa verify exhaustive (honest note)
- "15 ô trong 3 file" và "Gap Register đóng 4 dòng" trong `00_..Tong_The.xlsx`: em verify sâu file 01/02 (high-stakes) + finding cốt lõi; chưa đếm từng ô cả 3 file. Không thấy dấu hiệu sai; nếu bác cần con số chính xác em đếm nốt.

## Kết luận (vòng 1)
Lần đầu sửa file nguồn: làm đúng bài — backup trước, sửa có vết, cái không có căn cứ thì gắn cờ chứ không đoán, và finding gốc (VEGA lẫn sang HERA) verify airtight với kernel. Ba tầng (kernel/gói/file gốc) giờ đồng bộ số hiện hành.

---

## VÒNG 2 · SỰ CỐ file hỏng + khôi phục (QA hỏi con số → lộ lỗi lớn hơn con số · 2026-07-27)
**Đính chính vòng 1:** kết luận "không finding chặn" ở trên KHÔNG đúng tại thời điểm đó — file nguồn đã bị hỏng, chỉ chưa lộ. QA hỏi "con số chính xác 15 ô?" → build session đếm lại → **diff thật 167 ô, chỉ 27 cố ý; 140 ô là giá trị công thức bị openpyxl xoá trắng khi lưu** (chi phí, KPI, ngày nhắc). Công thức còn, giá trị cache mất → ai đọc bằng script/viewer không tính lại đều thấy trống.

**Khôi phục (build session):** restore 4 file từ backup → vá thẳng XML chỉ ô đích (`tools/xlsx_patch.py`). Vòng vá đầu lộ bug thứ 2: regex nuốt `/` của thẻ tự đóng, ăn lan 4 ô spec_id — bắt được vì diff phải khớp CHÍNH XÁC tập ô dự kiến.

**Verify độc lập của QA (differ riêng, backup vs current, cả data_only True/False):**
- Ô đổi: 00=**8** · 01=**15** · 02=**1** · 09=**3** = **27** (đúng khai) ✓
- **blanked-formula = 0** (không còn ô công thức mất giá trị) ✓
- **formula-string thay đổi = 0** (không dư chấn bug regex) ✓
- Giá trị công thức nguyên vẹn: tổng chi phí `15285000` (file 01 sheet 04/06) + KPI ĐẠT/KHÔNG ĐẠT (01:17 · 02:13 · 09:23) — đều KHÔNG nằm trong 27 ô đổi → chứng minh còn nguyên.

**Verdict vòng 2: khôi phục AIRTIGHT.** 27 ô đúng, 0 collateral, cache + công thức nguyên.

**Bài học (đã vào memory):** (1) KHÔNG dùng openpyxl save trên file có công thức — nó xoá cache giá trị; sửa xlsx có công thức phải vá XML. (2) Thao tác ghi hàng loạt: KHÔNG tin con số mình khai, đếm lại bằng máy, diff phải khớp CHÍNH XÁC (dôi 1 ô = fail). Công cụ ở `RtR_Copilot/tools/`.

**Meta:** QA không "tìm ra" bug — QA hỏi một con số, con số không khớp khi đếm lại. Yêu cầu kế toán chính xác là cách lộ lỗi âm thầm. Cùng họ với doctrine [[decision-number-code-two-way-regression]] nhưng cho thao tác-ghi thay vì code-sinh-số.
