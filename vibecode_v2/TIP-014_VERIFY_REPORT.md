# CONTRACTOR VERIFY REPORT — TIP-014 Query Understanding

**Ngày:** 04/08/2026  
**Nhánh:** `agent/tip-014-contractor-verify`  
**Disposition:** **CONDITIONAL GO** cho Phase 1 + guarded Phase 2; **NO-GO** cho
tuyên bố real-semantic retrieval/AC-2 cho tới khi có provider embedding thật.

## 1. Kết luận điều hành

Query Understanding hiện có một đường mặc định tất định và an toàn: alias RtR
được chuẩn hóa trước retrieval, câu hỏi gốc vẫn được lưu, grounding/citation/
honest-null không bị nới. Khi operator chủ động bật LLM rewrite, Anthropic là
primary và OpenAI là fallback; mọi thực thể ngoài catalog bị loại.

Contractor không chấp nhận trạng thái Builder ban đầu làm mốc hoàn tất vì còn ba
lỗ hổng vận hành: key có thể vô tình trở thành quyền xuất dữ liệu, timeout ngoài
ngắn hơn timeout provider làm mất fallback, và lượt rewrite chưa vào cost budget.
Ba điểm này đã được sửa và có test.

## 2. Remediation đã triển khai

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| External export fail-closed | PASS | `build_rewriter` chỉ bật external khi feature flag + key + allowlist có `internal`; key đơn độc trả `OfflineRewriter` |
| Anthropic → OpenAI fallback | PASS | mỗi provider có timeout riêng; outer timeout đủ cho toàn chuỗi; hanging primary rơi xuống fallback |
| Entity anti-hallucination | PASS | output entity bị intersect với catalog curator-owned; unknown bị loại |
| Cost governance | PASS | actual provider attempts tăng counter và debit budget; breaker-open skip không tính; audit ghi `usage_kind=query_rewrite` |
| Grounding isolation | PASS | rewrite chỉ thay retrieval query; original question, citation verifier, ACL/DLP và honest-null giữ nguyên |
| Operator configuration | PASS | `.env.example` và `.env.demo.example` mô tả flag, key, model, timeout và yêu cầu allowlist |

## 3. Acceptance evidence

| AC | Kết quả | Nhận định Contractor |
|---|---|---|
| AC-1 alias chính xác | PASS | 13 canonical; exact/variant/fuzzy strict; resolver range luôn nằm trong curated set; integration `hira`, `hr`, `Hera là gì?`, `vga` đều grounded đúng scoped record |
| AC-2 semantic retrieval + honest-null target | **OPEN** | runtime vẫn dùng `OfflineHashEmbedding`; chưa có provider contract, credential, corpus baseline và ngưỡng Homeowner duyệt |
| AC-3 guardrail | PASS cho phạm vi đã build | unknown entity bị loại; evidence/citation verifier và honest-null regression xanh |
| AC-4 fallback | PASS | disabled/no-key/no-allowlist/provider error/timeout/breaker-open đều rơi về deterministic path |
| AC-5 leak/DLP/ACL/cost/breaker | PASS cho local + hermetic | external classification explicit; live Postgres/Redis cost audit; suite ACL/DLP hiện hữu xanh; không nới scope |
| AC-6 migration | PASS | không thêm schema; migration head vẫn `0010_file_retrieval` |

## 4. Gate độc lập đã chạy

- Ruff: PASS.
- Mypy: **104 source files**, 0 issue.
- Query-understanding + rewrite unit: **54 passed**.
- Full backend trong image chuẩn có fonts/runtime libs: **413 passed, 114 skipped,
  0 failed**.
- Data integration trên database/bucket tạm, có Postgres + Redis thật:
  **57 passed**, migration up/down 10 revision, runtime mutation-denial và restore
  drill PASS.
- Trivy image scan: **0 HIGH/CRITICAL** (OS + Python packages).
- TIP-014 integration chứng minh alias → đúng scoped citation và unavailable
  scope → honest-null.

## 5. Điều kiện để đóng toàn bộ TIP-014

Homeowner cần chọn/cấp một embedding provider có hợp đồng xử lý dữ liệu phù hợp,
credential qua secret store (không chat/commit), và duyệt corpus + ngưỡng. Sau đó:

1. cắm adapter provider-neutral với model/version/dimension bất biến;
2. atomic reindex toàn corpus và rollback pointer;
3. đo Recall@5, MRR, grounded rate, honest-null precision, leak và p95 VI/EN;
4. chạy live rewrite canary với allowlist tối thiểu và xác nhận budget/breaker;
5. chỉ đánh dấu TIP-014 ✅ khi AC-2 đạt và leak vẫn bằng 0.

Trong lúc dependency này chưa có, default `RAG_REWRITE_ENABLED=false` và
`OfflineHashEmbedding` là trạng thái demo/local trung thực; không được quảng bá
như semantic production retrieval.
