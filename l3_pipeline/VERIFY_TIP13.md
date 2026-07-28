# VERIFY_TIP13 · bộ vận hành 4 tuần (dấu vết QA session)

**Ngày:** 2026-07-27 · **Chuẩn:** chạy thật (test suite + weekly_review trên log mẫu + snapshot log), không đọc suông.

## PASS (đã chạy)
- **Bug log-pollution ĐÓNG (verify tận gốc):** snapshot `gap_log.jsonl`/`qa_log.jsonl` = absent TRƯỚC; chạy 30 test; SAU vẫn **absent** → test ghi vào `mkdtemp` (test l.26-29 monkeypatch `cs.GAP_LOG/QA_LOG`), production log không bị chạm. Test #30 "test KHÔNG làm bẩn log vận hành" khoá vĩnh viễn. Đây là bug build session tự bắt khi chạy preflight thật.
- **`start_copilot.sh` fail-closed:** `if ! python3 test_copilot.py; then exit 1` (l.38) TRƯỚC `exec server` (l.67). Preflight: python → .env → file → GOI → test (fail→dừng) → in địa chỉ LAN. Test fail thì KHÔNG phục vụ gói lỗi. ✓
- **`weekly_review.py` honest-null ops:** 3 ô người (unique users · ca báo SAI · fact nạp) để **trống kèm nhắc**, không đoán — honest-null áp cho báo cáo vận hành. Date-filter đúng. Chạy thật ra report OK.
- Sổ 04 hết "Claude Team". `06` 3 bản thư (chat/email/nhắc giữa kỳ) + lưu ý mời người-không-quen-AI. `plist` plutil OK. Zip **15 file**, hash mẫu MATCH. **30/30 test.**

## FINDING · MEDIUM · clustering GAP dưới-gom paraphrase thật (undercut giá trị headline)
Chạy thật `weekly_review.py` với **3 cách hỏi "nghỉ phép"** ("nghỉ phép mấy ngày" · "quy định nghỉ phép năm bao nhiêu" · "nghỉ phép có lương không") → báo cáo ra **"0 nhóm lặp + 3 câu lẻ"**, KHÔNG gom. Đúng kịch bản claim quảng cáo ("bốn cách hỏi khác nhau về nghỉ phép gom thành một mục").
- **Nguyên nhân:** `cluster()` dùng overlap-coefficient ≥ **0.6** (l.69-70). 3 câu chỉ chung `{nghi, phep}` = 2 token trên 4-7 token → overlap 0.4-0.5 < 0.6 → không gom. Ngưỡng 0.6 phạt câu dài; chỉ gom được câu gần trùng, KHÔNG gom được paraphrase đa dạng thật.
- **Hệ quả:** tool chạy tốt nhất đúng lúc ít cần nhất (câu gần trùng ngắn), hỏng đúng lúc cần nhất (nhiều cách hỏi cùng chủ đề). Curator vẫn thấy list "câu lẻ" phải tự gom tay — đúng việc thủ công mà tool sinh ra để bỏ. Không chặn go-live (tool vẫn đếm + liệt kê được) nhưng under-deliver giá trị chính.
- **Điểm mù:** KHÔNG test nào kiểm `cluster()` (grep test_copilot.py: 0 hit) → weakness lọt. Cùng lớp lỗi "test không đi hết hành vi thật" đã gặp ở TIP-11.
- **Fix đề xuất (build session cầm cursor, một búa một đinh):** đổi tiêu chí gom sang "chung ≥2 token nội dung (non-stopword)" hoặc IDF-weight (token hiếm như "phép" nặng hơn) thay vì ratio 0.6; + regression test với đúng 3 câu nghỉ-phép này assert gom thành 1.

## Kết luận
Bug an toàn (log-pollution) đóng chắc + khoá test. Ops toolkit chạy được, honest-null đúng, fail-closed đúng. Một MEDIUM: GAP clustering dưới-gom paraphrase thật, làm yếu giá trị headline của weekly_review — nên chỉnh ngưỡng + thêm regression trước khi dựa vào báo cáo tuần để quyết gate Phase 2.

---

## VÒNG 2 · MEDIUM clustering ĐÓNG (re-verify live cả hai chiều · 2026-07-27)
Build session sửa ngay (không hoãn — đúng: dụng cụ đo lệch thì 4 tuần dữ liệu mất giá trị). `cluster()` viết lại: content-token (bỏ từ khung) + gom khi chung ≥2 từ nội dung hoặc 1 từ hiếm + union-find lan truyền bắc cầu + từ điển đồng nghĩa hẹp (mang/nâng→payload). Hai chốt chặn over-group: (a) hai sản phẩm khác nhau không gom; (b) tên sản phẩm một mình không đủ.

**Verify LIVE adversarial (1 log trộn 4 ca):**
- PHẢI GOM ✓: 3 câu "nghỉ phép" → 1 nhóm; "Hera mang được" + "Payload Hera" → 1 nhóm (synonym).
- CẤM GOM ✓: "Payload VEGA" đứng lẻ (không nhập nhóm Hera dù cấu trúc "Payload X" giống hệt); "IP rating Hera" đứng lẻ (không nhập chỉ vì chung "hera").
- Chiều nguy hiểm (nới gom → gom nhầm) được chặn và giữ dưới áp lực. 38/38 test, 8 regression khoá cả hai chiều. Doc 05 có hướng dẫn operator tự nới `CANON` + cảnh báo "rộng quá hại hơn tách nhầm, test đỏ ngay nếu thêm sai".

**Meta-lesson đóng:** `cluster()` giờ CÓ test (trước 0 test dù sinh số quyết gate). Đúng câu build session chốt — "code không được test thì không tồn tại về mặt bảo đảm, dù nó chạy". Cùng lớp lỗi parser TIP-11; cả hai giờ có regression cố định.
