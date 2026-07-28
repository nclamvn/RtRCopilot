# VERIFY_TIP9 · dấu vết của QA session (không phải shared state)

**Ngày:** 2026-07-27 · **Người kiểm:** QA session (Claude) · **Đối tượng:** TIP-9 (nạp batch vào kernel · thăng gói v1.0 · đóng vòng NT-1) + 2 fix của finding.
**Chuẩn kiểm:** hash + content, KHÔNG tin trình tự thao tác (bài học từ chính finding-2).

## Tự đính chính (ghi lại cho sòng phẳng)
Ở vòng trước em báo "73 approved record không truy được về kernel". SAI — do em so lệch khoá id (pack dùng `L3F.*`, kernel fact mang cả `id=L3F.*` lẫn `origin_card=CAND.*`). So đúng lại: 73/73 khớp id, content y hệt, origin_card đầy đủ. Đã rút lại trước khi báo cáo.

## TIP-9 gốc — verify tận gốc (PASS)
- `l3_facts.yaml`: 73 facts, domain 5/9/4/23/3/27/2=73, 0 thiếu evidence/source, origin_card 73/73, signoff có.
- `GOI_L3.yaml` v1.0: 98 record (73 approved + 25 kernel_confirmed), content 73/73 y hệt kernel fact, hết DRAFT/cho_Lam_verify.
- v0.9 archive `_archives/GOI_L3_DRAFT_v09_20260727.yaml` (một-bản-duy-nhất).
- DISPUTED_QUEUE: 8 `DA_XU_Lam_verified` + 3 mở (2 duyet + 1 KHAN).
- DECISION_LOG COPILOT-01 → EXECUTING.
- Em-dash: 29 cái, **29/29 trong evidence_span, 0 trong content/note** (đúng luật Refinery).

## Finding 1 · NT-1 tooling — RAISED rồi CLOSED
- **Raise:** state đúng nhưng không script nào tái sinh v1.0 từ kernel; `l3_export.py` cũ đọc `candidates/` → chạy lại ra 0.9/cho_Lam_verify. Vòng refresh trong checklist do đó sai.
- **Fix (build session):** l3_facts.yaml +25 kernel_refs (tự đủ). `l3_export.py` thay ruột đọc chỉ kernel, two-env fallback, bản cũ archive `l3_export_doc_candidates_20260727.py`.
- **Verify của em:** code body zero candidates read (grep); chạy 2 lần record-identical; tái tạo `GOI_L3.yaml` trên đĩa **98/98 record khớp content**; nguon=kernel; phien_ban 1.0. → NT-1 đóng ở mức reproducible, một lệnh tái lập được.

## Finding 2 · zip stale — RAISED rồi CLOSED
- **Raise:** zip rebuild 11:42 kèm v1.0 nhưng 4 file .md là bản 11:33; checklist trỏ `GOI_L3_DRAFT.yaml` (đã archive) + precondition "chưa duyệt". Nguyên nhân: sed checklist SAU khi zip.
- **Fix:** re-zip, đổi chuẩn verify sang SHA-256 từng file zip↔đĩa; zip là bước cuối luôn kiểm hash.
- **Verify của em:** SHA-256 `GOI_L3.yaml` + `TIP7` zip↔đĩa MATCH; checklist trong zip có "ĐÃ ĐẠT", 0 chữ "DRAFT", upload trỏ `GOI_L3.yaml`.

## Kết luận
Chuỗi data từ 8 thư mục phân tán → gói tri thức v1.0 giờ khép kín, kernel là SOT, tái lập bằng một lệnh `python3 l3_export.py`. Không còn việc máy cần chữ ký. Cửa còn lại thuần người: setup Claude Project (checklist 01), 3 dispute mở (Product · CEO ×2), escalation DISP.011.
