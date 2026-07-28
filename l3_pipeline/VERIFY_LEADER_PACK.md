# VERIFY · Gói lãnh đạo (L1-L4, chứa L2 giá) — vòng nhạy cảm nhất (dấu vết QA session)

**Ngày:** 2026-07-27 · **Chuẩn:** đập từng ràng buộc bằng code chạy thật, quét gói bằng máy. Rò ở đây = hại thật.

## PASS (proof, không nhận trên lời)
- **Allowlist fail-closed:** quét GOI_LEADER — **0 id cấm** (16 BOM giá vốn + 5 margin/DRAFT đều KHÔNG có), 0 giá trị cost. Sell-price allowlisted (MSRP US/VN, discount tier, FX) đều CÓ. Staff pack GOI_L3: 0 giá thật (1 hit "PRICE.*" là nhắc quy ước ID, không phải số).
- **RB.1 MOCK-lock (LIVE test):** leader + no key → server **TỪ CHỐI KHỞI ĐỘNG** ("chỉ chạy được LIVE"). sys.exit ở module-load, TRƯỚC khi đọc gói → không thể bypass runtime. Đây là rào quan trọng nhất: MOCK nhả nguyên văn record, chạy gói giá ở MOCK = ai gõ "giá" thấy bảng giá.
- **RB.2 passcode (LIVE test):** leader + key + no passcode → từ chối. Control: leader + key + passcode → bind OK (mode LIVE, 128 record) → ràng buộc không over-block.
- **Cổng tự chứng minh:** `leader_export.py --selftest` tiêm BOM.HERA.AIRFRAME=35000 giả → cổng CẮN. Sau khi thu hẹp scan (chữa false-pos 35000=mAh, 400=voice-doc) vẫn bắt được BOM thật → không mở lỗ false-negative.
- **Không-trong-zip:** GOI_LEADER.yaml KHÔNG có trong zip (0). Zip chỉ mang recipe (leader_export.py + allowlist, hash MATCH) — output nhạy cảm sinh tại chỗ.
- **Pending price gắn nhãn:** PRICE.VEGA.MSRP.VN hiện "verify_pending · chưa chốt, không dùng để cam kết" (doctrine A3).
- **46/46 test** hai chiều: staff cấm-có-giá · leader phải-có-giá nhưng cấm-giá-vốn.
- Hai báo động trong scan của em đều là nhầm, đã phân biệt: "260512"=ngày trong tên file nguồn (Almo pricing 260512.xlsx), "PRICE.*"=nhắc quy ước.

## Em tự nhận điểm sót
Vòng trước em nêu được "đảo tính chất an toàn: L2 vào gói → passcode là rào duy nhất", nhưng **MISS cơ chế sắc hơn**: ngay cả có auth, **chế độ MOCK tự nó là đường rò** — MOCK không có LLM nên nhả record verbatim, một lãnh đạo gõ "giá" cũng được bảng giá không qua lớp xét. Đó là rủi ro build session/Lâm nêu, không phải em. Em nói về rào auth mà bỏ sót cơ chế MOCK. Ghi lại để lần sau soi "chế độ suy biến khi thiếu điều kiện" chứ không chỉ soi rào truy cập.

## Ranh giới giữa "verify được" và "quyết định của người"
Em chứng minh được: **gói khớp CHÍNH XÁC allowlist** (không dư, không thiếu). Em KHÔNG chứng minh được: **allowlist có phải ranh giới đúng chính sách** — đó là quyết của Lâm. Đặc biệt `PRICE.*.BUNDLE.DIST` (giá cho nhà phân phối) là dòng gần biên nhất, build session tự đánh dấu cho Lâm duyệt.

## Mâu thuẫn "API hoãn" được giải quyết đúng
Kiến trúc hoà giải: **gói leader BẮT BUỘC LIVE (key bắt buộc, MOCK cấm)**; "API hoãn đến bước cuối" chỉ còn đúng cho **gói nhân viên** (MOCK chạy được, key tuỳ chọn). Hai gói, hai yêu cầu key — khoá trong RB.1.

## Điều code KHÔNG khoá được (dặn Lâm)
RB.2 ép CÓ passcode, nhưng nếu staff và leader chạy hai tiến trình riêng thì "passcode leader KHÁC staff" là kỷ luật người vận hành — code một tiến trình không thấy tiến trình kia. Lâm đặt hai mã khác nhau + đọc allowlist từng dòng (nhất là DIST).

## Verdict: AIRTIGHT. Vòng nhạy cảm nhất, mọi rào an toàn cắn khi thử phá.
