# TIP-046 · Phase 2 Completion Report (Builder)

**Date:** 16/09/2026
**Builder:** Claude (device bridge, Homeowner chạy lệnh)
**Phạm vi:** onboarding kernel đã sửa vào runtime Copilot local, kiểm 5 câu acceptance, vá retrieval để câu tiếng Việt chạm record spec strict.
**Trạng thái:** DONE với 7/8 case; 1 case (so sánh) chuyển follow-up phụ thuộc quyết định embedding của Homeowner.

## 1. Chu trình đã chạy

| Bước | Kết quả |
|---|---|
| Stack | `docker compose up -d`: 7 service healthy; api map cổng 18000, `ready=200`, `operational=200` |
| Baseline SOT | 6 nguồn `rtr.*` đang ở revision 6 (từ TIP-041 US Proclamation 28/08), outbox sạch |
| Phase 2 · onboard rev 7 | run_migration `--revision 7 --curated`: ready 325 (specs 100, l3_facts 132). Dry-run 6/6 `planned_valid`. Activate `activated_count=6`. Worker rút outbox, index flip: specs 11 → 100 chunk, l3_facts 131 → 134, rev 6 `superseded` |
| Phase 2b · key song ngữ | 5 câu kiểm cho thấy câu tiếng Việt không chạm record spec **strict**. Sửa `specs.yaml`: key mọi record thành `EN · VI` (kernel `ba778cb`). Onboard rev 8. Vẫn không chạm |
| Phase 2.1 · vá chunker (TIP-046.1) | Đọc `rag/reindex.py`: record strict chỉ băm **câu trích nguyên văn** từ master vào index, nhãn record (key + value) không vào index. Vá `compose_chunk_base`, `CHUNKER_VERSION → /2`. Rebuild api+worker. Onboard rev 9, chunker_version `rtr-evidence-chunker/2` cho cả 6 nguồn |

## 2. Nguyên nhân gốc (TIP-046.1)

`ReindexService._candidates` dựng văn bản chunk bằng:

```python
base = str(row["evidence_text"] or row["searchable_text"]).strip()
```

Record **strict** có `evidence_text` (câu trích nguyên văn từ master, ví dụ "Maximum payloads weight: 30 lb(13.6 kg)", "3500W"), nên chỉ câu trích tiếng Anh vào index; nhãn record chứa key song ngữ và giá trị không bao giờ vào index. Hệ quả: càng nhiều record strict (Phase 1 nâng specs từ 11 lên 100 record, 98 strict) thì câu hỏi tiếng Việt càng trượt; chỉ record **soft** (HC-001, L3F) mới có chữ tiếng Việt trong chunk nên luôn thắng. Đây là lỗi Copilot, không phải kernel; Phase 2b vẫn đúng và cần, chỉ chưa tới được index.

**Vá:** `compose_chunk_base(searchable_text, evidence_text)`:
- record soft (không evidence): giữ searchable_text.
- record strict có nhãn ngắn (≤400 ký tự): `nhãn · Nguồn: câu trích nguyên văn`. Câu trích không bị sửa, chỉ đặt sau nhãn, nên strict vẫn giữ span verbatim ở đuôi.
- record strict prose dài (L3F strict): giữ câu trích, không lặp.

`CHUNKER_VERSION` nâng `/1 → /2` để đổi mọi chunking fingerprint, buộc reindex sinh generation mới thay vì no-op. Kèm `tests/test_tip046_chunk_base.py` (5 unit test).

## 3. Acceptance (oracle cam kết trước ở packet)

| Case | Kỳ vọng | Kết quả sau rev 9 |
|---|---|---|
| MS-001 payload HERA | 14 kg + 30 lb, fail nếu 15 kg | PASS (14 kg / 30 lb / MTOW 29,6 kg; qua HC-001, số đúng) |
| MS-002 tầm điều khiển | 10 km chuẩn + 15 km @8 dBi | PASS |
| MS-003 TOPS | Xavier 21 chuẩn + Orin 100 tùy chọn | PASS |
| MS-004 VEGA payload | 20 kg (44 lb), MTOW 38 kg | PASS |
| MS-005 VEGA (gộp MS-004) | như trên | PASS |
| MS-006 HeraSight NDAA vs Standard | LRF/IR khác nhau | **FAIL** (trả HC-010, không gom hai biến thể) |
| MS-007 Tether backup | ~7 phút với 6 kg tải | PASS (SPEC.TETHER.BACKUP_FLIGHT_TIME) |
| MS-008 IP54 | IP54 | record live, chưa hỏi lại trên UI |

Bổ sung ngoài oracle: MS "Tether cấp điện bao nhiêu W" → PASS (SPEC.TETHER.POWER 3500 W).

## 4. Vì sao MS-006 chưa đạt và hướng xử lý

MS-006 là câu **so sánh nhiều record** (SPEC.HERASIGHT.NDAA.* với SPEC.HERASIGHT.STD.*), khác tra cứu một giá trị. Hai lực cản:

1. Hệ trả lời là **verbatim extraction, no inference** theo thiết kế; nó trả record, không tự dựng bảng khác biệt.
2. Ranking: lexical arm xếp HC-010 ("HeraSight 61MP") cao hơn các record spec vì trùng token "herasight"; embedding hiện là `rtr-offline-hash-embedding` (hash cục bộ, không ngữ nghĩa) nên không kéo lại được các record NDAA/Standard.

Đây đúng loại câu mà **quality-mode OpenAI embedding** giải quyết (ngữ nghĩa kéo hai record biến thể lên, và breadth đủ để trình bày cạnh nhau). Việc bật OpenAI embedding là quyết định Homeowner đang giữ (khóa API dưới kiểm soát của Homeowner, không commit secret). Vì vậy chuyển thành:

- **TIP-046.2 (follow-up):** câu so sánh và ranking strict-vs-capability. Phụ thuộc quyết định bật OpenAI embedding + có thể chỉnh trọng số lexical/vector cho record spec. Không phải blocker của bộ số master.

## 5. Trạng thái runtime cuối

6 nguồn `rtr.*` ở **revision 9**, `search_generations` active với chunker `rtr-evidence-chunker/2`; specs 100 chunk, l3_facts 134. Không secret vào repo/chat. Số master 07/2026 (ba phân xử 16/09) đã trả lời đúng và có điều kiện trên UI cho các câu tra cứu giá trị.

## 6. Deferred (REQ-ID)

| ID | Việc | Chờ |
|---|---|---|
| TIP-046.D1 | Nâng RANGE.EXTENDED lên verified_primary | Quoc Luong xác nhận 15 km @8 dBi |
| TIP-046.D2 | Bộ ghi hiện trường Tây Ninh bản 2 | Homeowner cho biết đã gửi Sở chưa |
| TIP-046.D3 | Website LS1 + factsheet báo chí đồng bộ master | Owner nội dung |
| TIP-046.D4 | HeraSight61 Standard atomize fact | Phase 1b nếu cần |
| TIP-046.2 | Câu so sánh + ranking strict record | Quyết định OpenAI embedding của Homeowner |
