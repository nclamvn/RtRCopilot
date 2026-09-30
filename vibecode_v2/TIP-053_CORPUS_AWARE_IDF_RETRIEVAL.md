# TIP-053 · Corpus-aware IDF retrieval

**Ngày:** 30/09/2026

**Mức:** P0 chất lượng trả lời

**Phụ thuộc:** TIP-051, TIP-052

**Chặn:** VERIFY của TIP-048 và TIP-050

## 1. Vấn đề

Đường truy hồi hiện coi mọi từ trùng nhau gần như có giá trị ngang nhau. Trên
chỉ mục thật, `argon2id` chỉ xuất hiện trong một chunk nhưng đóng góp không hơn
những từ phổ biến như `nguoi`, `dung` hay `rtr`. Vì vậy bản ghi đúng
`L3F.INF.014` có `ts_rank_cd` cao nhất vẫn đứng sau hai bản ghi dài có nhắc tên
công ty.

Không tăng mù hệ số `ts_rank_cd`. TIP này bổ sung độ hiếm được đo từ chính
active corpus để một từ hiếm có sức phân biệt cao hơn từ phổ biến.

## 2. Thiết kế

1. Mỗi search generation có bảng thống kê bất biến
   `search_generation_term_stats(generation_id, term, chunk_frequency)`.
2. Reindex dựng thống kê trong cùng transaction với chunk và chỉ kích hoạt
   generation sau khi cả chunk lẫn thống kê hoàn tất.
3. Migration backfill thống kê cho các generation đã tồn tại.
4. Khi hỏi, hệ thống chỉ đọc tần suất của các query term trên những generation
   đang active. Không quét lại corpus ở mỗi request.
5. Trọng số chuẩn:

   `idf(term) = ln((N + 1) / (df(term) + 1)) + 1`

6. Ứng viên nhận một tín hiệu coverage nhỏ, bị chặn trên:

   `idf_coverage = sum(idf của query term trùng) / sum(idf của query term)`

   `adjustment += 0.08 * idf_coverage`

7. Probe runtime đầu tiên làm lộ trường hợp thứ hai: trong câu ngắn “Argon2id
   được RtR dùng để làm gì?”, một exact identifier duy nhất vẫn thua ba từ phổ
   biến cộng lại. Vì vậy term có `idf >= 5,0` (trên corpus đo được: xuất hiện
   trong tối đa vài chunk) trở thành **rare exact anchor**. Ứng viên được cộng
   tối đa `0,72 * rare_coverage`; ứng viên không khớp không bị phạt. Nếu câu
   không có term hiếm hoặc stats thiếu, tín hiệu này bằng 0.

Hệ số coverage 0,08 được khóa trước khi chạy xác nhận: phép đo trên active corpus cho
chênh lệch coverage 0,475 giữa bản ghi đúng và nhiễu, tương đương 0,038 điểm,
vừa đủ vượt khoảng cách 0,029 đã đo ở TIP-052 nhưng nhỏ hơn nhiều các binding
authority (0,24–1,00).

Hệ số rare-anchor 0,72 được thêm sau probe runtime, không phải suy đoán: câu
ngắn còn thiếu 0,671 điểm do thưởng ba từ phổ biến và nhắc tên thực thể; exact
`argon2id` có `idf=6,30`, còn từ phổ biến cao nhất chỉ `idf=3,70`. Mức 0,72
đủ lật đúng khoảng cách đã đo, ngang definition binding nhưng vẫn thấp hơn
collection binding 1,00 và vẫn chịu toàn bộ ACL/DLP/grounding phía sau.

## 3. Ranh giới an toàn

- Không thay ACL, DLP, ontology binding, citation hay grounding.
- Không gọi LLM hoặc embedding external.
- Thống kê không chứa văn bản, chỉ lexeme và document frequency; không có API
  đọc trực tiếp bảng này.
- Chỉ generation active tham gia IDF; generation superseded không ảnh hưởng.
- File retrieval chưa dùng thống kê SOT và giữ nguyên hành vi.
- Nếu bảng không có số liệu, IDF adjustment bằng 0 và ranking quay về hành vi
  trước TIP-053.

## 4. Acceptance

| ID | Kiểm | Đạt khi |
|---|---|---|
| IDF-001 | Migration up/down và schema pin | Một Alembic head; bảng/index/ACL đúng |
| IDF-002 | Reindex mới | Có term stats trước khi generation active |
| IDF-003 | Atomic swap/replay | Generation lỗi không làm đổi active stats; replay idempotent |
| IDF-004 | Unit scoring | Từ hiếm nâng đúng ứng viên; thiếu stats là no-op |
| IDF-005 | Live retrieval | `L3F.INF.014` đứng hạng 1 cho câu Argon2id đầy đủ |
| IDF-006 | Regression | Bộ test backend và các probe retrieval local không tụt |
| IDF-007 | Hiệu năng | Mỗi search tối đa một query term-stats nhỏ; không full scan chunk |

## 5. Rollback

Hạ migration để bỏ bảng thống kê và bỏ đối số `idf_coverage` khỏi scoring.
Không cần sửa hay phục hồi dữ liệu SOT/corpus gốc.
