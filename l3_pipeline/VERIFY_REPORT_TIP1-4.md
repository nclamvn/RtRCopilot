# VERIFY REPORT · TIP-1..4 · Chủ thầu kiểm ngược

**Ngày:** 27/07/2026 · Chủ thầu Claude · 4 Thợ subagent thi công song song

## REQUIREMENT COVERAGE

4/4 TIP DONE (100%). Blueprint section 3 yêu cầu TIP-1..4 output candidates đúng schema về đúng vị trí: đạt cả 4.

## SCENARIO RESULTS (acceptance criteria từng TIP)

| TIP | AC chính | Kết quả |
|---|---|---|
| TIP-1 | 20-40 card · evidence verbatim · đối chiếu kernel · 3 nhóm output | PASS · 39 card · 0 thiếu evidence · 4 conflict có kernel_ref |
| TIP-2 | Như TIP-1 + flag derived artifact cho deck | PASS · 40 card · deck không bị cào số (đúng luật 6) |
| TIP-3 | Như TIP-1 + HOSO_CEO đánh dấu chờ xác nhận riêng | PASS · 29 card · 8 card HOSO đều L2 + note đúng |
| TIP-4 | Một card mỗi hệ thống · owner hoặc honest-null | PASS · 13 card (deviation +1 hợp lệ: tách mrp/mrp-v2) · 3 folder rỗng ghi trung thực |

## TECHNICAL HEALTH

- YAML parse: 4/4 pass · 121 card · 0 trùng id · 0 card thiếu evidence_span/source_path · 0 duplicate/conflict thiếu kernel_ref (kiểm bằng script, không bằng cảm giác)
- Phân bố kernel_check: new 82 · duplicate 21 · conflict 11 · legacy 4 · unsure 3
- Phân bố tier đề xuất: L3 100 · L2 18 · L4 3

## PHÁT HIỆN NGOÀI DỰ KIẾN (giá trị cao nhất của đợt cào)

1. **DISP.011 · KHẨN:** 6 đề án nhà nước đã nộp (24 file BM) chứa claim HERA "đã trên Blue UAS Cleared List" trong khi trạng thái thật là "listing in progress". Claim sai trạng thái trong hồ sơ nhà nước = đúng loại rủi ro client-risk audit doctrine. Cần escalate CEO.
2. **DISP.008:** Học vị CEO lệch giữa kernel ("PhD engineer") và hồ sơ 6 đề án ("Tiến sĩ Kinh tế Phát triển"). Fact-sheet báo chí may mắn chỉ ghi "Tiến sĩ tại UC Berkeley" không ghi ngành.
3. RtR_Company_Knowledge_Base.docx (18/05) tự nhận "Source of Truth" nhưng chứa 3 fact stale · đúng hiện tượng "kho phân tán N+1" mà PRD cảnh báo · bằng chứng sống cho lý do tồn tại của dự án này.
4. Cụm Control Tower 4 folder không phân định được danh tính · nhân viên hỏi là bot không trả lời được · cần owner chốt trước khi vào gói L3.

## OVERALL STATUS: READY-với-deferred

Sẵn sàng cho checkpoint C2 (Lâm duyệt). Deferred (không chặn C2):

- 3 card unsure chờ Product team (naming HeraSight)
- Mốc bảo dưỡng PROPOSED chờ Engineering (vào gói L3 phải giữ nhãn PROPOSED)
- 7 spec conflict trong sheet CONFLICTS_PENDING của Master Canonical (flag từ 05/2026) · đề xuất một pass verify riêng với Engineering, ngoài phạm vi đợt này

## PACKAGE CHO CHECKPOINT C2

1. `candidates/tip1..4.yaml` · 121 card
2. `DISPUTED_QUEUE.yaml` · 11 dispute (8 xử được theo lô "kernel thắng" · 3 cần người: DISP.008 CEO bio, DISP.011 Blue UAS khẩn, DISP.005-007 lô Engineering) + 6 action item
3. Manifest legacy đã bổ sung mục 5 (3 file phát hiện thêm)

**Đề xuất cách duyệt nhanh cho Lâm (~30 phút):**
- Lô 1 · duyệt nguyên tắc "kernel thắng" cho DISP.002/003/004 + 21 duplicate bỏ qua → một chữ ký
- Lô 2 · DISP.005/006/007 + ACT.005 gửi Engineering một email 4 câu hỏi
- Lô 3 · DISP.008/009/010 + 8 card HOSO_CEO · Lâm tự xử (biết CEO trực tiếp)
- Lô 4 · DISP.011 · escalate CEO riêng, khẩn
- Lô 5 · ACT.001-004, 006 · phân người
- Còn lại 82 card new: duyệt theo domain (product/process/company/system) · em đã sắp sẵn
