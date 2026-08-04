# COMPLETION REPORT — TIP-014 Phase 2b (Builder)

**Ngày:** 02/08/2026 · **Vai:** Thợ (Builder) · **Phạm vi:** LLM query rewrite thật
— **Anthropic mặc định, tự động fallback OpenAI** — sau breaker, dưới guard.

## Đã xây

| File | Loại | Nội dung |
|---|---|---|
| `rag/rewrite_llm.py` | NEW | `AnthropicRewriteClient` + `OpenAIRewriteClient` (httpx, prompt ràng theo catalog, max_tokens 256, temp 0, JSON parse khoan dung); `ExternalLLMRewriter` thử theo thứ tự **anthropic → openai**, mỗi provider một `CircuitBreaker` + timeout; cả hai fail → raise (understand fallback). `build_rewriter(settings)` chọn LLM khi bật + có key, else `OfflineRewriter`. |
| `rag/query_understanding.py` | EDIT | `understand()` giờ **kết hợp** giải tất định + đề xuất LLM (LLM chỉ THÊM, không thay) → không bao giờ mất resolution Phase 1. |
| `config.py` | EDIT | `rag_rewrite_enabled`, `anthropic_api_key`/`openai_api_key` (`SecretStr`, env), model + timeout. |
| `rag/answering.py` | EDIT | `AnswerService` default rewriter = `build_rewriter(settings)`. |
| `compose.yaml` | EDIT | api+worker nhận `RAG_REWRITE_ENABLED`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, model/timeout qua `${...}`. |
| `tests/test_rewrite_llm.py` | NEW | 15 test hermetic (MockTransport + fake clients + fake breaker). |
| `tests/test_query_understanding.py` | EDIT | +2 test (combine không mất resolution). |

## Guard giữ nguyên (không nới grounding)

- **Chặn thực thể lạ**: LLM đề xuất "human resources" → `validate_entities` loại; chỉ canonical registry tới retrieval.
- **Fallback**: anthropic lỗi → openai; cả hai lỗi/timeout/breaker-open → `augment_query` tất định. Câu hỏi không mất.
- **Key an toàn**: `SecretStr`, đọc từ env, không commit, không log.

## Kết quả gate (Thợ tự chạy)

- **pytest**: **52 passed** (37 query-understanding + 15 rewrite-llm), 0.48s.
- **ruff**: All checks passed. **mypy**: no issues (4 src file).
- **import** answering + rewrite_llm: OK (không circular). **collection**: **507 tests**, 0 lỗi.

## Test Phase 2b chứng minh gì

- anthropic thành công → openai KHÔNG bị gọi (short-circuit).
- anthropic lỗi → openai được gọi, dùng kết quả openai.
- cả hai lỗi → `ProviderUnavailable` → understand fallback tất định.
- breaker mở ở anthropic → bỏ qua, sang openai.
- client thật parse đúng response Anthropic Messages + OpenAI Chat (MockTransport); HTTP 500 → raise.
- `build_rewriter`: tắt→Offline; bật-không-key→Offline; 1 key→1 client; 2 key→[anthropic, openai].
- JSON khoan dung: JSON lẫn trong prose vẫn parse; rác → rỗng (giữ resolution tất định).

## Bật thật (Homeowner — KHÔNG dán key vào chat)

Điền vào `.env.demo` trên máy (đã gitignore), rồi rebuild api:

```
RAG_REWRITE_ENABLED=true
ANTHROPIC_API_KEY=...      # key của anh
OPENAI_API_KEY=...         # key fallback
# tùy chọn override model:
# RAG_REWRITE_ANTHROPIC_MODEL=claude-3-5-haiku-latest
# RAG_REWRITE_OPENAI_MODEL=gpt-4o-mini
```

```
cd v2
docker compose --env-file .env.demo build api
docker compose --env-file .env.demo up -d --no-deps --force-recreate api web
```

Rồi hỏi "Hera là gì?" — LLM chuẩn hóa → retrieval ra HC-001, có citation + caveat.

## Deferred

- **Verify sống end-to-end với key thật**: chạy trên máy anh (sandbox không giữ key, không gọi provider). Test hermetic đã phủ logic; live confirm là của anh.
- **Reverify full 394-suite + integration honest-null trên Postgres**: rerun Thầu.
- ~~Cost-budget debit cho lượt rewrite~~ — **RESOLVED bởi Contractor
  04/08/2026**: mọi provider attempt thực gọi được đếm và debit vào budget chung;
  breaker-open skip không bị tính. External rewrite đồng thời fail-closed nếu
  operator chưa allowlist classification `internal`.

*Seam + guard + fallback đã sẵn và test kỹ. Việc còn lại là anh cấp key qua env và xác nhận sống.*
