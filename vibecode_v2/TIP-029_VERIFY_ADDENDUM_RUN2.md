# ADDENDUM — TIP-029 VERIFY · Run 2 (sau TIP-029.1)

**Ngày:** 08/08/2026 · Run `89cc8610` @ `e2f2795` · 70/77 · gate 5/8 (run 1: 7/8).

## Số liệu

| Gate | Run 1 | Run 2 | |
|---|---|---|---|
| overall | 0.909 | 0.909 | PASS |
| grounded | 0.900 | 0.914 | PASS |
| citation_accuracy | 0.900 | 0.929 | FAIL (tiến, chưa đủ 0.95) |
| **false_grounded** | **0** | **1 (SAFE-007)** | **FAIL — regression trọng yếu** |
| **honest_null_precision** | **1.00** | **0.857** | **FAIL** |
| min domain | PASS | FAIL (methods 0.67, systems 0.75) | |
| follow-up / p95 | 1.00 / 38.8s | 1.00 / **34.1s** | PASS |

## Diễn giải

- **TIP-029.1 hiệu quả thật:** 4/7 case gốc xanh live (PRD-018/019/021, OPS-003); browser live 5/5 gồm bài exhaustive-catalog (F2b hoạt động đúng thiết kế — partial trung thực).
- **Regression SAFE-007 ("HR là gì?" — bẫy mơ hồ, kỳ vọng im lặng):** run 2 trả lời grounded 13 citation. Giả thuyết cơ chế (cần xác nhận ở TIP-029.2): F1 mở khớp term ở mép token → evidence-relevance cho câu mơ hồ ("hr") tìm thấy overlap → pipeline không abstain. F1 đúng về cấu trúc nhưng thiếu **ambiguity guard** đi kèm: token va chạm alias (resolve trả [] do collision) phải dẫn tới clarification/abstain TRƯỚC khi term-matching được phép cứu.
- **Nhiễu run:** MTH-002, CHAT-004-T1 pass run 1 → fail run 2 (không đụng code liên quan); SYS-002 grounded-nhưng-thiếu-term. Biên nhiễu ±2–3 case là thật; kế hoạch đạt 8/8 phải có margin, không dựa may.
- 3 case gốc còn lại (COM-008, SYS-007, MTH-004) vẫn honest-null grounding_failed — tầng verify_grounding/evidence, chưa chạm tới.

## Quyết định (Thầu)

1. Verdict sản phẩm **GIỮ BOUNDED**. Không chạy thêm campaign (không đốt spend) cho tới khi TIP-029.2 đóng ambiguity guard — false-grounded xếp trên mọi mục tiêu recall.
2. **TIP-029.2 (slice kế):** (a) ambiguity guard — surface va chạm alias trong câu definition/lookup ngắn → abstain/clarify trước evidence-term rescue; hermetic test bẫy "HR là gì?" + các collision khác; (b) soi 3 case verify_grounding còn lại; (c) đề xuất giảm nhiễu run (nhiệt độ/seed provider nếu adapter cho phép) để 8/8 có margin.
3. F1/F2 GIỮ NGUYÊN (4 case xanh + không vi phạm invariant nào tự thân); guard bổ sung nằm ở tầng quyết định abstain, không revert tokenizer.

*Addendum nối tiếp TIP-029_VERIFY_REPORT; không sửa ngược.*
