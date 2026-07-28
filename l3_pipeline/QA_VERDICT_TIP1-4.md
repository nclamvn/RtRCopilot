# QA VERDICT · TIP-1..4 candidates · independent contractor re-check

**Ngày:** 2026-07-27 · Người kiểm: Chủ thầu (Claude) · Phương pháp: script `qa_validate.py` (không kiểm bằng cảm giác) + đối chiếu chéo DISPUTED_QUEUE.

## KẾT LUẬN: PASS — sẵn sàng cho checkpoint C2

121/121 card đạt schema + cả 6 luật cứng. 0 lỗi cứng (hard error). Không re-scrape, không sửa card nào.

> **Addendum 2026-07-27 (sau QA):** Đã áp DISP.009/010 theo cách tách-đôi (chỉ đạo Lâm). TIP-3: 29→31 card, tổng **123 card**. conflict 11→9, duplicate 21→23, new 82→84, L3 100→102, L2 18 giữ nguyên. Re-run `qa_validate.py`: vẫn **0 hard error**. Bảng dưới là snapshot QA gốc (121 card); phần thay đổi ghi ở đây.

## Đã kiểm (bằng script, pass hết)

| Hạng mục | Kết quả |
|---|---|
| YAML parse 4 file + key `candidates:` | 4/4 pass |
| Số card | TIP1 39 · TIP2 40 · TIP3 29 · TIP4 13 = **121** |
| ID duy nhất, đúng format `CAND.N.NNN`, N khớp file | 121/121, 0 trùng |
| Enum hợp lệ (domain/extraction/tier/kernel_check) | 121/121 |
| Luật 3 · mọi card có evidence_span + source_path | 121/121, 0 thiếu |
| **source_path tồn tại thật trên đĩa** | 121/121 resolve (đã sửa path space) |
| Luật 1 · duplicate/conflict có kernel_ref | 21 dup + 11 conflict đều có ref hợp lệ |
| kernel_ref trỏ record/doc kernel thật | 100% (capabilities.yaml + _dist) |
| Luật 2 · legacy 15kg/33lb/1-4-15 | 4 card legacy, không lọt vào conflict |
| TIP-3 · card HOSO_CEO = L2 + note "chờ Lâm" | 8/8, 0 vi phạm |
| conflict ↔ DISPUTED_QUEUE traceability | 11 conflict ↔ DISP.001–011, 1:1 |

## 4 cảnh báo mềm còn lại — đã phân xử, KHÔNG phải lỗi

- **CAND.1.030 / CAND.2.033 / CAND.4.001** (regex bắt "Price/báo giá"): cả 3 chỉ mô tả *sự tồn tại của tính năng/quy ước* (booth app có ô tra giá · quy ước ID `PRICE.*` · module báo giá của CRM) — KHÔNG lộ con số giá. Schema cho phép "quy trình/hệ thống nội bộ" ở L3. → giữ L3 đúng.
- **CAND.2.012** (legacy nhưng có kernel_ref → LEGACY manifest): schema nói legacy để null, nhưng trỏ manifest là provenance hữu ích. Cosmetic, không cần sửa (nếu muốn sạch tuyệt đối thì set null).

## Ghi chú cho người chạy lại

- `qa_validate.py` dùng lại được cho các đợt cào sau (đã sửa 2 nguồn false-positive: path có dấu cách; kernel_ref trỏ doc `_dist`).
- Lưu ý môi trường: prefix `/sessions/.../mnt/` trong đề TIP **không tồn tại** ở máy này; base thật là `/Users/os/RtR/`. Card đã ghi source_path đúng base thật.
