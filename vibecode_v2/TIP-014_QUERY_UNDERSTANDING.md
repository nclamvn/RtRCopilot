# TIP-014 · Query Understanding & Entity Resolution cho Ask

## HEADER

- **TIP-ID:** TIP-014
- **Tên:** Ask Smoothness — hiểu câu hỏi trước truy hồi, KHÔNG nới grounding
- **Vai đề xuất:** Tổng công trình sư (Contractor)
- **Ngày:** 02/08/2026
- **Depends on:** TIP-007 (Hybrid RAG), TIP-011 (Ask UI), TIP-012 (breaker + cost limit), TIP-013B (soft/caveat). Kernel `entities.yaml` + `capabilities.yaml`.
- **Trạng thái:** DRAFT — chờ Homeowner chốt phạm vi + thứ tự.
- **Nguồn gốc:** hợp nhất hai đề xuất —
  - **Homeowner:** gọi LLM chuẩn hóa/hiểu câu hỏi trước để mượt (typo "hira/heara", viết tắt "hr", câu tự nhiên "Hera là gì?").
  - **Contractor:** embedding thật + từ điển alias từ registry + gate grounding bất động + LLM **không bao giờ** là nguồn sự thật + thứ tự "đo trước, xây sau".

---

## 1. CONTEXT — vấn đề thật, tách đúng lớp

Trên bản demo local, "Hera là gì?" trả honest-null dù HERA có đủ fact (HC-001 mô tả nền tảng, MTOW 31 kg, payload 15 kg…). Cần tách bạch **hai lớp** để không sửa nhầm:

- **Lớp grounding (độ chặt):** không đủ căn cứ → nói "chưa có", không bịa. Đây là linh hồn SOT. **Không đụng, không nới.**
- **Lớp retrieval (độ khôn khi tìm bằng chứng):** khớp câu hỏi → đúng fact. Đây mới là chỗ hỏng. Demo local xài `OfflineHashEmbedding` (băm SHA256, `adapters.py:55` — không hiểu nghĩa), nên câu tự nhiên/typo/viết tắt trượt.

TIP này **chỉ làm lớp retrieval khôn hơn**, tuyệt đối không hạ chuẩn grounding.

**Cảnh báo phóng đại:** phần lớn cảm giác "kém phán đoán" là do stub băm của demo. Với embedding thật, một phần lớn biến mất **trước khi** thêm LLM. Vì thế Phase 0 (đo baseline thật) đứng trước mọi việc xây.

---

## 2. THIẾT KẾ HỢP NHẤT — pipeline "hiểu câu hỏi" trước truy hồi

Chèn một tầng **Query Understanding (QU)** giữa `rag/api.py::ask` (nhận `body.question`) và `retrieval.py::Retriever.search(query=…)`. Bốn tầng, có fallback xuống dần — **không tầng nào được phép làm câu hỏi thất bại**:

```
câu hỏi thô
  │
  ├─ (1) NORMALIZE  — tất định, luôn bật, rẻ
  │      casefold + fold dấu + gọn khoảng trắng (mở rộng normalize_query hiện có)
  │
  ├─ (2) ENTITY/ALIAS RESOLUTION — tất định, từ registry của RtR
  │      khớp fuzzy (edit-distance/trigram) token → thực thể canonical
  │      "hira/heara/hr" → HERA · "vega"/"vga" → VEGA · HeraSight/HeraHub…
  │      Nguồn alias = entities.yaml (canonical+aliases) + BẢNG ALIAS SẢN PHẨM
  │      curator-owned (seed từ capabilities/specs), cùng kỷ luật entities.yaml
  │
  ├─ (3) LLM QUERY REWRITE/EXPAND — provider thật, CÓ fallback
  │      vào: query đã normalize + thực thể đã giải
  │      ra: (a) rewrite canonical  (b) từ mở rộng  (c) intent (define/spec/price/compare)
  │      RÀNG BUỘC: mọi thực thể LLM sinh ra phải ĐỐI CHIẾU NGƯỢC registry;
  │      thực thể lạ (vd "hr"→"human resources") bị LOẠI, không tới retrieval
  │      LLM chết / breaker mở / quá cost → rơi về (1)+(2), KHÔNG fail câu hỏi
  │
  └─ (4) RETRIEVE — truy hồi trên query đã cải thiện (embedding THẬT + lexical)
         gate grounding NGUYÊN VẸN: honest-null nếu rỗng · citation · caveat soft
```

**(Phase tùy chọn) (5) LLM ANSWER COMPOSITION** — diễn đạt câu trả lời tự nhiên **chỉ từ** bằng chứng đã truy hồi (ràng theo citation), honest-null + caveat giữ nguyên. Đây là phần "mượt" ở đầu ra; tách phase riêng vì rủi ro cao hơn.

---

## 3. LẰN RANH CỨNG (một câu, không thương lượng)

> **LLM được nắn *câu hỏi* và (tùy chọn) nắn *cách diễn đạt câu trả lời* — NHƯNG KHÔNG BAO GIỜ là nguồn của sự thật.**

Cụ thể, bất biến sau mỗi lượt:

1. Câu trả lời chỉ dựa **bằng chứng đã truy hồi**; không fact nào ngoài citation.
2. Mọi thực thể LLM sinh ra phải nằm trong **registry thực thể thật** của RtR; thực thể lạ bị loại trước khi tới retrieval.
3. **Honest-null** vẫn bắn khi không có bằng chứng — kể cả khi LLM "tự tin".
4. Caveat soft giữ nguyên; DLP/ACL/scope **không đổi**.
5. LLM hỏng → đường tất định (1)+(2) vẫn trả lời được.

---

## 4. TASK — theo phase, đúng thứ tự "đo trước, xây sau"

### Phase 0 — Baseline thật (Homeowner, cấu hình, KHÔNG code)
- Bật embedding provider **thật** (H-value RAG provider) thay `OfflineHashEmbedding`.
- Chạy lại bộ câu hỏi cố định (mục 6) → đo **honest-null rate thật** trên embedding thật.
- **Mục tiêu:** biết khoảng cách CÒN LẠI sau khi có semantics, để không over-engineer tầng LLM. Contractor dựng bộ đo; Homeowner cấp provider.

### Phase 1 — Alias/Entity resolution tất định (Builder 1 — xây được NGAY, không cần credential)
- Mở rộng `normalize_query` (fold dấu + casefold) — giữ tất định.
- Dựng **bảng alias sản phẩm** RtR: canonical + variants (HERA↔hira,heara,hr; VEGA↔vga; HeraSight; HeraHub; OmniSight; DualSight…), seed từ `capabilities.yaml`/`specs.yaml`, **curator-owned**, cùng kỷ luật `entities.yaml` (`curated` flag, không auto-merge nếu chưa Lâm duyệt).
- Resolver fuzzy (trigram/edit-distance ngưỡng chặt) token → canonical; nối vào query trước `search()`.
- Test hermetic: mọi biến thể tên sản phẩm giải đúng canonical; **không giải sai** ("hr" chỉ →HERA vì có trong bảng, "human resources" KHÔNG bao giờ tự sinh).

### Phase 2 — LLM query rewrite/expand (Builder 2 — provider-gated)
- Gọi provider thật (tái dùng abstraction RAG hiện có + circuit breaker + cost limit của TIP-012).
- Ra rewrite + expansion + intent; **đối chiếu mọi thực thể ngược registry**; loại thực thể lạ.
- Fallback tất định khi provider chết/breaker mở/quá budget.
- Stub provider (như stub RAG local) để test tất định trong CI.

### Phase 3 — (Tùy chọn) LLM answer composition (Builder 3)
- Diễn đạt câu trả lời tự nhiên **chỉ từ** citation đã truy hồi; honest-null + caveat giữ nguyên.
- Test hồi quy: không chèn được fact ngoài bằng chứng.

---

## 5. INTEGRATION SEAMS (neo vào code thật)

- Vào: `apps/backend/src/rtr_copilot/rag/api.py::ask` (`body.question`).
- Tầng QU: module mới `rag/query_understanding.py`, gọi trước `Retriever.search`.
- Truy hồi: `rag/retrieval.py::Retriever.search(query=…)` — nhận query đã cải thiện; **không đổi** logic hybrid (lexical `ts_rank_cd` + vector `<=>`, `rag_min_vector_score`).
- Normalize: mở rộng `rag/adapters.py::normalize_query`.
- Alias source: kernel `entities.yaml` (canonical+aliases) + bảng alias sản phẩm mới (curator-owned).
- Embedding thật: thay `OfflineHashEmbedding` qua config provider (Phase 0).

---

## 6. ACCEPTANCE CRITERIA (đo được)

Bộ eval cố định gồm biến thể: đúng chuẩn / typo / viết tắt / câu tự nhiên / song ngữ VI-EN (vd "Hera là gì?", "hira mtow", "hr payload", "what is hera", "vga giá").

- **AC-1** Alias: mọi biến thể tên sản phẩm → đúng canonical; **0 giải sai** thành thực thể ngoài registry.
- **AC-2** Retrieval: với câu **trả lời được**, honest-null rate giảm xuống dưới ngưỡng chốt ở Phase 0; với câu **thật sự không có căn cứ**, honest-null giữ **100%** (không đẻ hallucination mới).
- **AC-3** Guardrail: test chứng minh LLM **không** chèn được thực thể ngoài registry, **không** sinh fact ngoài citation; honest-null + caveat bảo toàn.
- **AC-4** Fallback: tắt LLM/mở breaker → câu hỏi vẫn được trả lời qua đường tất định.
- **AC-5** Leak vẫn = 0; DLP/ACL/scope không đổi; cost/breaker tôn trọng; hermetic.
- **AC-6** Không schema migration bắt buộc (bảng alias là dữ liệu curator; QU là tầng xử lý). Nếu cần lưu, chỉ thêm additive.

---

## 7. CONSTRAINTS

- **KHÔNG nới grounding.** Gate honest-null/citation/caveat bất động.
- LLM chỉ nắn câu hỏi + (tùy chọn) diễn đạt; không phải nguồn fact.
- Thực thể LLM sinh phải đối chiếu registry thật; loại thực thể lạ.
- Tôn trọng circuit breaker + cost limit (TIP-012); fallback tất định.
- Bảng alias curator-owned, kỷ luật `entities.yaml` (curated flag, no auto-merge).
- Token/tests hermetic; kernel read-only.

---

## 8. HOMEOWNER vs AGENT

- **Homeowner:** cấp RAG embedding + LLM provider thật (H-value) cho Phase 0/2; duyệt bảng alias sản phẩm (curator); chốt ngưỡng honest-null mục tiêu.
- **Agent:** xây Phase 1 tất định + tests NGAY (không cần credential); dựng bộ eval Phase 0; xây Phase 2/3 khi có provider; chạy dry-run; không tự bật provider thật thay Homeowner.

---

## 9. THỨ TỰ TÔI KHUYẾN NGHỊ

1. **Phase 0** bật embedding thật + đo baseline (rẻ, xử phần lớn cảm giác "kém").
2. **Phase 1** alias/entity tất định — xây + chứng minh local hôm nay (fix typo/viết tắt/tên sản phẩm).
3. Đo lại. Còn khoảng cách ở câu tự nhiên → **Phase 2** LLM rewrite.
4. Muốn câu trả lời "mượt" như hội thoại → **Phase 3** answer composition.

*Không mục nào ở đây nới chuẩn grounding. Ta làm việc TÌM bằng chứng khôn hơn, không hạ tiêu chuẩn cái gì được tính là bằng chứng.*
