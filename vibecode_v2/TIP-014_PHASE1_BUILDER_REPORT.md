# COMPLETION REPORT — TIP-014 Phase 1 (Builder)

**Ngày:** 02/08/2026 · **Vai:** Thợ (Builder) · **Phạm vi:** Phase 1 — alias/entity
resolution tất định + wiring vào retrieval. KHÔNG cần credential, hermetic.

## Đã xây

| File | Loại | Nội dung |
|---|---|---|
| `apps/backend/src/rtr_copilot/rag/product_aliases.py` | NEW | Bảng alias sản phẩm **curator-owned** (`CURATED=True`). 13 canonical từ `capabilities.yaml` thật (HERA, VEGA, HeraSight, HeraSight LR/"61T", DualSight, OmniSight, SkyWatch 360, HeraHub/"heralink", VegaHub, VegaSight, AeroTunnel, LS1, S1) + biến thể/viết tắt thật (hr, hira, heara, vga…). Không bịa tên. |
| `apps/backend/src/rtr_copilot/rag/query_understanding.py` | NEW | `resolve_entities()` — greedy longest n-gram exact + fuzzy strict (difflib, ngưỡng 0.86, chỉ token ≥4 ký tự). `augment_query()` — nối canonical vào query, additive, giữ nguyên câu gốc. Tất định, không LLM, không network. |
| `apps/backend/tests/test_query_understanding.py` | NEW | 25 test hermetic. |
| `apps/backend/src/rtr_copilot/rag/answering.py` | EDIT | 1 dòng: `search(subject, augment_query(question), …)` — chỉ nắn query truy hồi; `question` gốc giữ nguyên ở lưu trữ/answer/honest-null. |

## Kết quả gate (Thợ tự chạy, Thầu chạy lại độc lập)

- **pytest** `tests/test_query_understanding.py`: **25 passed** (0.16s).
- **ruff** (4 file): **All checks passed**.
- **mypy** (3 src file): **Success: no issues found**.
- **Import**: `import rtr_copilot.rag.answering` OK (không circular).
- **Regression collection**: full suite **480 tests collected**, 0 lỗi import — module mới không phá import-graph.

## Đối chiếu AC của TIP-014

- **AC-1** (alias → đúng canonical, 0 giải sai): **PASS**. `TestExactResolution`, `TestAbbreviationAndVariant`, `TestFuzzyNetIsStrict`, và `TestNoFalseEntities.test_resolver_range_is_curated_set` chứng minh **range của resolver ⊆ tập canonical curated** — về mặt cấu trúc **không thể đẻ thực thể lạ** ("hr"→HERA, "human resources"→∅).
- **AC-3** (guardrail): **PASS phần tất định** — không sinh thực thể ngoài registry; `augment_query` chỉ THÊM term, giữ nguyên câu gốc, không đụng grounding. Test honest-null end-to-end cần DB → thuộc rerun Thầu.
- **AC-4** (fallback khi LLM chết): **N/A Phase 1** — chưa có LLM; chính đường tất định này LÀ fallback cho Phase 2.
- **AC-5** (leak 0, DLP/ACL/breaker không đổi, hermetic): **giữ nguyên theo thiết kế** — không sửa retrieval/DLP/grounding; test hermetic. Reverify leak/e2e trên DB → rerun Thầu.
- **AC-6** (không schema migration): **PASS** — thuần code + data trong module.

## Deferred (đúng ranh giới, không P0/P1)

- **AC-2** (đo honest-null rate giảm / non-answerable giữ 100%): thuộc **Phase 0** — cần embedding THẬT + bộ eval. Dưới stub băm hiện tại, augmentation giúp ít; giá trị đầy đủ hiện ra khi bật provider thật. Phase 1 chỉ bảo đảm phần *giải alias* đúng và tất định.
- **Reverify full 394-suite + integration honest-null trên Postgres**: sandbox cloud không chạy được backend-DB → thuộc rerun Thầu trên máy Homeowner (cùng lớp với các env-note trước).

## Bàn giao Thầu

Cây để nguyên, chưa commit. Đề nghị Thầu: chạy lại 3 gate + full suite trên máy có Postgres, xác nhận honest-null bất biến, rồi commit + đồng bộ. Phase 2 (LLM rewrite) chờ provider thật của Homeowner.

*Không sửa ngược sau commit.*
