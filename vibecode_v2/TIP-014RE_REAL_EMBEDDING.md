# TIP-014RE · Real Embedding — đóng AC-2 của TIP-014 (packet gộp, cập nhật theo tiến độ)

**Ngày:** 09/08/2026 · Sau PR #9 (main `3e2d351`, verdict COMPANY-WIDE INTERNAL PILOT tái xác nhận 96.1%).
**Homeowner chọn:** OpenAI `text-embedding-3-small` · key OpenAI ĐANG có sẵn trong `.env.demo` → không cần credential mới.
**Kế thừa:** TIP-014 QU (verify 04/08) đã đóng AC-1/3/4/5/6; AC-2 (semantic retrieval thật) là phần treo duy nhất. TIP-030 đã chuẩn bị sẵn 3 acceptance case + kênh chẩn đoán.

## 1. Phạm vi — chỉ lớp retrieval, grounding bất động

Thay `OfflineHashEmbedding` (băm SHA256, không hiểu nghĩa) bằng embedding thật ở: (a) index corpus khi reindex, (b) vector hoá câu hỏi khi truy vấn. **Không đụng**: gate grounding, citation verifier, honest-null, DLP/ACL, weak-alias guard (chặn TRƯỚC retrieval nên không bị ảnh hưởng).

## 2. Luật verdict (khoá TRƯỚC khi chạy dữ liệu)

| Gate | Ngưỡng |
|---|---|
| 3 acceptance case | SYS-007 → L3F.4.011, MTH-004 → L3F.2.035, OPS-010 → L3F.1.027: grounded + cite đúng oracle, targeted ≥2 vòng liên tiếp |
| Full campaign re-cert | ≥75/77, đủ 8/8 gate hiện hành |
| An toàn bất động | false-grounded **= 0** · honest-null precision **= 1.0** · SAFE-007 vẫn honest-null (`not_called_query_ambiguous`) |
| Hermetic | full suite xanh, ruff 0, mypy 0; trust-surface test khoá `rag_embedding_provider="offline"` mặc định |
| Suy thoái có kiểm soát | provider embedding chết/timeout → truy vấn rơi về lexical-only, KHÔNG câu hỏi nào fail |
| Ngưỡng vector | `rag_min_vector_score` hiệu chỉnh bằng harness phân bố điểm oracle-vs-random TRƯỚC campaign; không tinh chỉnh hậu nghiệm |

## 3. Thiết kế

1. **Adapter** `OpenAIEmbedding` (httpx, endpoint `/v1/embeddings`, tham số `dimensions` = config): `embed` sync (reindex), `aembed` async + timeout (đường truy vấn), `embed_batch` (backfill ≤128 text/call). Factory `build_embedding_adapter(settings)`.
2. **Trust surface:** `rag_embedding_provider` mặc định `"offline"`. Bật `"openai"` đòi **key + allowlist `internal`** (tái dùng nguyên pattern external-export fail-closed của rewrite; thiếu → ValueError lúc startup, không âm thầm hạ cấp).
3. **Chiều vector:** schema đang khoá `vector(64)`. Migration `0013`: nới cột `chunks.embedding` → `vector(1536)` (pad 0 các row cũ — chỉ generation không active, không được rank), CHECK `search_generations.embedding_dimension` từ `=64` → range 64..3072, rebuild HNSW cosine. Downgrade: slice 64 chiều đầu + CHECK cũ. `rag_embedding_dimension` mặc định mới **1536** (offline hash chạy mọi chiều → hermetic vẫn tất định).
4. **Re-embed corpus:** không cần cơ chế mới — fingerprint generation đã chứa (model, version, dimension). Lệnh `commands/reembed_corpus.py`: flip outbox `done→pending` cho các revision đang active + drain `ReindexService` → generation mới, pointer flip nguyên tử, idempotent (fingerprint trùng → no-op).
5. **Suy thoái:** query-path lỗi provider → vector 0 (giữ nhánh lexical, không rớt row lexical-hit), đếm metric, KHÔNG fallback về hash (khác không gian vector với chunk đã index).
6. **Chi phí:** backfill toàn corpus ~≤1M token ≈ $0.02 một lần; mỗi câu hỏi +1 call embedding (~$0.000002). Không cần cơ chế budget mới; usage ghi qua metric (REQ-014RE-D1: debit budget embedding — deferred, chi phí không trọng yếu).

## 4. Phase

- **RE-1** Adapter + config + governance + degrade + test hermetic (mock provider).
- **RE-2** Migration 0013 + reindex/ingestion dùng factory + batch + lệnh reembed + harness hiệu chỉnh `rag_min_vector_score`.
- **RE-3** Homeowner bật `.env.demo` (`RAG_EMBEDDING_PROVIDER=openai`), migrate + reembed local, targeted 3 case ×2 vòng.
- **RE-4** Full campaign re-cert (chờ duyệt chi) + PR #10.

## 5. Nhật ký thi công

**RE-1 + RE-2 XONG (Thợ, 09/08/2026, môi trường cloud):**

- Adapter `OpenAIEmbedding` (batch ≤128, L2-normalize, refuse dimension-mismatch, test seam MockTransport) + `EmbeddingProviderError` + factory `build_embedding_adapter` (fail-closed cả khi Settings bị bypass validator).
- Config: `rag_embedding_provider` default `offline` (test khoá), dimension default 1536, validator policy_required chạy MỌI environment (đặt trước early-return production).
- Đường truy vấn: `RetrievalService._query_vector` — provider lỗi → `CAST(NULL AS vector)` → `greatest(0, 1-NULL)` = 0 → degrade lexical-only đúng nghĩa (KHÔNG fallback hash — khác không gian vector); metric `rtr_embedding_query_degraded_total` + trace flag.
- Reindex: embed theo batch 2-pass (`zip strict` — lệch số lượng là lỗi cứng); ingestion/file_index nhận `EmbeddingAdapter` protocol.
- Migration `0013_real_embedding_dim`: widen chunks + file_chunks vector(64)→vector(1536) pad-0 (giữ FK citations, cosine bất biến trong generation), CHECK dimension → range 64..3072 (drop qua catalog, không đoán tên), downgrade slice + ghi lại metadata đúng thực tế. Ladder verify-data-integration thêm probe up/down 0013 assert `format_type = vector(1536)/(64)`.
- `commands/reembed_corpus.py`: flip outbox `dispatched→pending` cho revision active + drain ReindexService (fingerprint chứa model/dim → generation mới, pointer flip nguyên tử, idempotent; revision active thiếu outbox row = exit 2 fail-loud).
- Harness `eval/embedding/calibrate_min_vector_score.py`: đo oracle-best vs distractor-best cho mọi case grounded, in percentile + đề xuất floor (advisory, pre-commit trước campaign).
- compose.yaml: EXPECTED_SCHEMA_REVISION→0013, pass-through 4 env embedding mới; .env.example/.env.demo.example ghi rõ nghi thức bật.
- **Hermetic cloud: 599 passed / 88 skipped / 0 fail · ruff 0 · mypy 0** (integration DB-bound chạy ở stack CI + máy Homeowner).
