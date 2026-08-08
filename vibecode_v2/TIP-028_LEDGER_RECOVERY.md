# TASK INSTRUCTION PACK — TIP-028 · Ledger Recovery (docs-only)

**Role cycle:** Thầu (author + verify) → Thợ (docs slice) → Thầu-verify.
**Ngày:** 08/08/2026 · **Nhánh đích:** `agent/tip-024-5-ux-recovery` (cùng PR #7).
**Bối cảnh:** X-Ray delta 08/08 phát hiện `03_TASK_GRAPH.md` dừng ở TIP-024.5
trong khi chiến dịch đã chạy tới TIP-027.5 với đầy đủ hồ sơ per-TIP. Sổ cái là
xương sống truy vết của phương pháp — drift phải vá bằng một slice có kiểm chứng,
không vá tay ngoài luồng.

## Task

1. Bổ sung các hàng còn thiếu 024.6 → 027.5 (21 hàng) vào bảng task graph, mỗi
   hàng đối chiếu trực tiếp với VERIFY report gốc của TIP đó (verdict + số gate),
   không suy diễn từ trí nhớ.
2. Audit tính đầy đủ bộ hồ sơ (packet + Completion + Verify) của từng TIP trong
   dải; TIP nào thiếu → đánh dấu ◐ kèm ghi chú AUDIT-GAP, không được ghi ✅.
3. Cập nhật dòng **Trạng thái** phản ánh: dải verified mới nhất, verdict pilot
   hiện hành, độ lệch của `main`, các audit-gap.

## Acceptance Criteria

- **AC-01** Mỗi TIP có hồ sơ trong `vibecode_v2/` đều có đúng một hàng trong bảng.
- **AC-02** Mọi con số/verdict trong hàng trích được từ VERIFY report tương ứng.
- **AC-03** TIP thiếu Completion/Verify bị đánh dấu ◐ + AUDIT-GAP (không ✅).
- **AC-04** Slice chỉ đụng `vibecode_v2/` (docs) — không đụng code/test/CI.

## Ràng buộc

Không sửa nội dung các VERIFY report gốc (không sửa ngược); chỉ sổ cái được cập
nhật. Mọi phát hiện gap ghi thành finding cho Homeowner, không tự "hợp thức hoá".
