> [Cập nhật 27/07 · TIP-11] Gói hiện là 106 record: thêm 5 kernel-mirror L3R.K.001-005 vá coverage gap do test offline phát hiện. Verify dưới đây chụp trạng thái 101 record trước đó, vẫn đúng tại thời điểm chụp.

# VERIFY · API server pivot + 3 kernel facts (dấu vết QA session)

**Ngày:** 2026-07-27 · **Người kiểm:** QA session (Claude) · **Chuẩn:** hash + smoke test live, không tin trình tự.

## PASS (verify tận gốc)
- **3 fact mới nạp kernel đúng + trung thực:**
  - Blue UAS (l3_facts:1888): "hồ sơ đang trong quy trình xét duyệt dưới DoW Conditional..." — KHÔNG fact nào assert "cleared" (hit "cleared" duy nhất là note mô tả claim sai).
  - OC-001: "Tiến sĩ Kinh tế Phát triển tại UC Berkeley · Fulbright/Cornell/Berkeley", ghi rõ bản cũ "PhD engineer" là SAI.
  - HC-011 = "HeraSight LR (61T)", HC-056 = "MERGED về HC-011".
- **DISPUTED_QUEUE 11/11 đóng** (8 verified + 3 confirm).
- **Package tái lập từ kernel:** l3_facts 76 + 25 refs; `l3_export.py` chạy ra 101 record (76 approved + 25 kernel_confirmed), content == GOI_L3.yaml trên đĩa 100%.
- **Zip integrity:** SHA-256 `copilot_server.py` + `GOI_L3.yaml` zip↔đĩa MATCH; 8 file, self-contained (GOI_L3 + TIP7 co-located → find() chạy được cả khi unzip nơi khác lẫn khi chạy trong repo qua fallback ../l3_pipeline).
- **Server smoke test live (không set API key, 0 cost):** GET / →200 UI; /health →ok; POST /api/chat sai passcode →403; đúng passcode + no key →500 lỗi rõ. Zero-dependency stdlib xác nhận.
- **Tính chất an ninh mạnh:** API key không bao giờ ra client; L2 KHÔNG rò được vì L2 không nằm trong pack (đã audit 0 L2) — jailbreak cũng không moi ra cái không có trong context.

## FINDING A · HIGH · default model id nghi sai, 4 test KHÔNG bắt được
- `copilot_server.py` MODEL mặc định = **`claude-sonnet-5`**. Danh sách model hiện hành (authoritative): `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, `claude-fable-5`. KHÔNG có `claude-sonnet-5`.
- **Điểm mù:** cả 4 test (UI/health/passcode/missing-key) KHÔNG câu nào gọi API thật (test 4 lỗi TRƯỚC khi gọi). Nên model id sai vẫn pass 4/4, chỉ chết ở câu hỏi thật đầu tiên của nhân viên (API model-not-found).
- **Fix đề xuất:** đổi default sang id đã xác nhận (`claude-sonnet-4-6`, hoặc `claude-opus-4-8` nếu ưu tiên chất lượng) + THÊM một câu test end-to-end thật vào `03_Bo_Cau_Test_Acceptance.md` để đóng điểm mù. (Caveat: knowledge cutoff QA là 01/2026; nếu account có sonnet-5 thật thì bỏ qua — nhưng phải xác nhận bằng MỘT câu hỏi thật trước pilot.)

## FINDING C · MEDIUM (an ninh) · no-passcode + bind 0.0.0.0
- `PASSCODE` default rỗng; nếu operator quên `COPILOT_PASSCODE`, server vẫn bind `0.0.0.0:8787` → /api/chat mở cho toàn LAN (ai cũng query được tri thức + đốt API credit). Code chỉ in cảnh báo.
- **Fix đề xuất:** khi PASSCODE rỗng thì bind `127.0.0.1` (fail-safe), chỉ mở 0.0.0.0 khi có passcode.

## FINDING B · LOW (cosmetic) · /health đếm dư 1
- `records_loaded` = `GOI.count("record:")` = 102, do đếm cả dòng `tong_record:`. Thật là 101. Sửa: đếm entry dưới `records:` hoặc trừ key thống kê.

## Kết luận
Data + tooling + zip: PASS. Server: đúng kiến trúc, chạy được, an ninh nền tốt. Ba finding đều ở tầng cấu hình/vận hành, không phải data. Finding A là thứ duy nhất chặn "câu hỏi thật đầu tiên" — phải xử trước khi mời nhóm.

---

## VÒNG 2 · cả 3 finding ĐÓNG (verify tận gốc + smoke test live · 2026-07-27)
- **A · xử theo nguyên tắc (hay hơn đề xuất gốc của em).** Build session chỉ ra: hai session hai cutoff (QA 01/2026 vs product-info 07/2026), cả hai đều không phải trọng tài — **API mới là**. Fix 3 lớp: giữ default `claude-sonnet-5`; thêm error handling (HTTPError 400/404 + "model" → thông báo VN chỉ cách `export COPILOT_MODEL=...`, không sửa code); và thêm **Phần D · GATE BẮT BUỘC** vào test 03 (một câu hỏi thật qua API trước phần A) + setup guide trỏ tới. Đây là honest-null áp cho chính hệ. Verify: default + error branch + Phần D + guide đều có mặt.
- **B · ĐÓNG.** `/health records_loaded` = `len(re.findall(r'^- record:', ...))` = **101** (đếm đúng, hết lẹm `tong_record`).
- **C · ĐÓNG (smoke test live).** `HOST = "0.0.0.0" if PASSCODE else "127.0.0.1"`. lsof xác nhận: không passcode → bind **127.0.0.1** (fail-safe máy cá nhân); có passcode → bind **\*:port** (mở LAN). Console cảnh báo rõ khi không passcode.
- Zip cuối: SHA-256 `copilot_server.py` + `GOI_L3.yaml` zip↔đĩa MATCH.

**Bài học phương pháp (build session ghi nhận):** mọi hệ gọi dịch vụ ngoài phải có smoke test end-to-end THẬT trong bộ acceptance, không chỉ test biên — vì 4 test biên pass mà hệ vẫn chết ở giao dịch thật đầu tiên. Đã institutionalize thành Phần D.
