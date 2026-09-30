# TIP-053 · Completion Report (Builder)

**Ngày:** 30/09/2026

**Candidate local:** working tree trên `fc67e2ad39e7`

**Trạng thái:** DONE ở tầng retrieval; downstream `/ask` chưa recertify vì lượt này không có phê duyệt gửi evidence ra LLM external.

## 1. Kết quả

TIP-053 thay ranking theo corpus thật, không tăng mù hệ số lexical:

- Alembic head mới `0015_generation_term_stats` tạo bảng tần suất bất biến theo
  generation và backfill các generation hiện hữu.
- Reindex dựng term stats trong cùng transaction trước active-pointer swap.
- Search chỉ đọc IDF của query terms trên sáu generation đang active; không
  quét 400 chunk ở mỗi request.
- Scoring có hai tín hiệu bị chặn trên: weighted coverage `0,08` và rare exact
  anchor `0,72` cho lexeme có `idf >= 5,0`.
- Không thay ACL, DLP, ontology, citations, grounding hoặc external policy.

Hai câu chặn đã được đo trực tiếp trên runtime local:

| Câu | Trước TIP-053 | Sau TIP-053 |
|---|---:|---:|
| Mật khẩu người dùng của RtR được băm bằng Argon2id phải không? | `L3F.INF.014` hạng 3, 0,725 | **hạng 1, 1,511258** |
| Argon2id được RtR dùng để làm gì? | vắng khỏi top 12 | **hạng 1, 1,216652** |

Ở câu thứ hai, đối thủ gần nhất còn 1,165384. Exact identifier đã thắng nhưng
không đẩy toàn bộ entity/authority logic ra khỏi công thức.

## 2. Dữ liệu chứng thực

- Active corpus: 400 chunk, 6 generation.
- Bảng active term stats: 3.617 dòng.
- `argon2id`: df 1, idf 6,3008.
- `dung`: df 68, idf 2,7599.
- `nguoi`: df 22, idf 3,858.
- `rtr`: df 116, idf 2,2318.
- PostgreSQL `EXPLAIN ANALYZE` cho 9 query terms: **0,529 ms** execution.
- 20 lượt `/search`: p50 867,12 ms; p95 1.048,84 ms; max 2.253 ms. IDF
  chiếm dưới 1 ms; tail còn lại thuộc pipeline retrieval hiện hữu.

## 3. QA/QC

| Gate | Kết quả |
|---|---|
| `migration-gate.sh` | PASS, 15 revisions, single head khớp pin |
| Migration cô lập up/down/up | PASS |
| Data integration | **73 passed**, toàn bộ migration/restore/policy drill PASS |
| Backend unit/conditional suite | **750 passed, 132 skipped** |
| Ruff | PASS |
| mypy strict cho bốn module thay đổi chính | PASS |
| Live retrieval probe | **15/18 PASS**, không gọi `/ask` |
| Runtime | 7/7 container healthy; schema `0015_generation_term_stats` |

Trong full suite có một invariant procedure đỏ từ baseline: numbered workflow
row đứng sau cover. Builder sửa đúng invariant bằng cách làm structural step
signal quyết định bên trong một procedure đã được admit; suite sau sửa xanh
750/750. Một lint debt `isinstance((bytes, bytearray))` cũng được đổi sang cú
pháp Python 3.12 tương đương, không đổi hành vi.

## 4. Ba probe còn đỏ

P10 và hai biến thể D3 đều là cùng một yêu cầu “Dữ liệu của RtR được lưu ở
đâu?”. Bản ghi đích `L3F.INF.002` không chia sẻ anchor từ vựng với cách hỏi;
IDF không thể tăng một từ không hề trùng. Đây là semantic-planner/ontology
bridge gap, không phải lỗi corpus-frequency. Không nới IDF để chữa sai lớp.

## 5. Phạm vi chưa chứng thực

Không gọi `/api/v1/ask`, TIP-033 hay TIP-034. Runtime đang có cấu hình external
nhưng lượt này không có phê duyệt gửi câu hỏi/evidence nội bộ ra endpoint. Vì
vậy TIP-053 đóng blocker retrieval của TIP-048/TIP-050, chưa tự động biến hai
TIP đó thành VERIFIED.

## 6. Kết luận Builder

TIP-053 đạt acceptance ở tầng được phép kiểm: dữ liệu được backfill, swap
atomic, ranking đúng trên corpus thật, regression xanh và chi phí DB không đáng
kể. Bước hợp lý kế tiếp là một TIP semantic bridge riêng cho nhóm câu không có
lexical anchor, sau đó mới xin một lượt `/ask` recertification có phê duyệt.
