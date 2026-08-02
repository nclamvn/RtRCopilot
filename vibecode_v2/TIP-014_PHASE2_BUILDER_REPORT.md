# COMPLETION REPORT — TIP-014 Phase 2 skeleton (Builder)

**Ngày:** 02/08/2026 · **Vai:** Thợ (Builder) · **Phạm vi:** Phase 2 — bộ khung
LLM query-rewrite **an toàn**, test được ngay, **chưa cắm LLM thật** (provider-gated).

## Nguyên tắc giữ đúng

Mặc định **không đổi hành vi runtime**: rewriter mặc định là `OfflineRewriter`
(tất định, không LLM/network) → pipeline chạy y hệt Phase 1 cho tới khi Homeowner
tiêm một rewriter LLM thật. Hai guard cứng đã có mã + test:

1. **Chặn thực thể lạ** (`validate_entities`): mọi thực thể rewriter đề xuất bị
   đối chiếu registry; cái nào không phải canonical curated (vd LLM bịa
   "human resources" từ "hr") bị **loại**, không tới retrieval.
2. **Fallback tất định** (`understand`): rewriter chết/timeout/lỗi bất kỳ →
   rơi về `augment_query` Phase 1. Câu hỏi **không bao giờ mất**.

## Đã xây

| File | Loại | Nội dung |
|---|---|---|
| `rag/query_understanding.py` | EDIT | + `RewriteResult`, `QueryRewriter` (Protocol seam), `OfflineRewriter` (default/fallback), `validate_entities` (guard), `understand()` (orchestrate + timeout + fallback), expansions có cận (`MAX_EXPANSIONS=5`, `≤40` ký tự). Phase 1 refactor về `_augment_with` — hành vi giữ nguyên. |
| `rag/answering.py` | EDIT | `AnswerService.__init__` nhận `rewriter` (default `OfflineRewriter`); `ask()` gọi `await understand(question, self._rewriter)` chỉ cho query truy hồi; `question` gốc giữ nguyên. |
| `tests/test_query_understanding.py` | EDIT | +10 test Phase 2 (tổng **35**). |

## Kết quả gate (Thợ tự chạy)

- **pytest**: **35 passed** (25 Phase 1 + 10 Phase 2), 0.25s.
- **ruff**: All checks passed. **mypy**: no issues (2 src file).
- **import** `rtr_copilot.rag.answering`: OK (không circular).
- **collection** full suite: **490 tests**, 0 lỗi import.

## Test Phase 2 chứng minh gì

- `validate_entities` giữ HERA/VEGA, **loại** "human resources"/"Acme"/"Skynet".
- `understand` + `OfflineRewriter` **== `augment_query`** (đảm bảo default = Phase 1).
- rewriter trả thực thể bịa → bị strip, query không chứa nó.
- rewriter raise / timeout (0.05s) → **fallback tất định**, vẫn giải HERA/VEGA.
- expansions quá dài bị bỏ; câu gốc luôn đứng đầu; tất định.

## Còn lại — Phase 2b (Homeowner-gated)

- **`ExternalLLMRewriter` thật**: lớp gọi provider LLM sau breaker + cost budget
  (mirror `AnswerService._call_provider`), tiêm qua DI (`rewriter=`). Cần
  **provider thật của Homeowner** (H-value) — không dựng được sống ở đây.
- Bật qua `rag_provider_mode="external"` + config allowlist/endpoint đã có sẵn.
- Reverify full 394-suite + integration honest-null trên Postgres → rerun Thầu.

*Seam đã sẵn; cắm LLM là một bước tiêm DI + config, không phải sửa gate.*
