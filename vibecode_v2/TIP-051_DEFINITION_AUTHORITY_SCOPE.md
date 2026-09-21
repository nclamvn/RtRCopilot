# TIP-051 · Thu hẹp quyền ưu tiên của bản ghi định nghĩa thực thể

**Ngày:** 21/09/2026
**Mức:** P0 sản phẩm
**Phụ thuộc:** phát hiện từ lượt VERIFY của TIP-050 ngày 21/09
**Chặn:** VERIFY của TIP-048, TIP-049 và TIP-050 đều không kết luận được nếu chưa sửa

## 1. Triệu chứng đo được

Lượt chạy `eval/tip050/capture_use_class.py` ngày 21/09, 16 câu hỏi:

- 7 câu được trả lời bằng `L3F.ENT.001`, bản ghi tên pháp nhân và mã số doanh nghiệp, mà vẫn mang nhãn `grounded`. Trong đó có "RtR có chứng nhận SOC 2 không?" và "Dữ liệu của RtR được lưu ở đâu?".
- 9 câu còn lại được trả lời bằng bản ghi năng lực `HC-001`, `HC-002`, `HC-010`.
- **Không câu nào được trả lời bằng một fact nguyên tử.** Toàn bộ `SPEC.*` và `L3F.INF.*` mà TIP-046, TIP-048 và TIP-049 curate trong ba phiên đều không xuất hiện.

Ba ô PASS trong lượt đó là PASS giả, do oracle của Builder chỉ kiểm `state` và chuỗi con chứ không kiểm bản ghi được trích dẫn. Đã siết lại trong cùng file.

## 2. Nguyên nhân, đã chứng minh chứ không phải giả thuyết

`eval/tip050/probe_retrieval.py` đi thẳng vào `/api/v1/search`, nơi không có bộ lập kế hoạch và không có ràng buộc ontology:

| Truy vấn | Bản ghi đúng | Hạng | Điểm |
|---|---|---|---|
| HeraSight Standard NETD | `SPEC.HERASIGHT.STD.NETD` | 1 | fusion 1,46 |
| HeraSight Standard có độ nhạy nhiệt NETD bao nhiêu? | `SPEC.HERASIGHT.STD.NETD` | 1 | lex 1,00 |
| VEGA có RTK tích hợp sẵn hay chỉ tương thích? | `SPEC.VEGA.RTK` | 1 | lex 1,70 |
| quy ước đánh số phiên bản phần cứng | `L3F.STD.001` | 1 | lex 2,40 |
| Argon2id | `L3F.INF.014` | 1 | duy nhất |
| us-east-1 | `L3F.INF.002` | 1 | duy nhất |

Chỉ mục đúng, thu hồi đúng, xếp hạng đúng. Cùng câu hỏi đó đi qua `/api/v1/ask` thì ra `L3F.ENT.001`, một bản ghi thậm chí không có trong sáu hạng đầu của `/search`.

Khác biệt duy nhất giữa hai đường là bộ lập kế hoạch. `plan_query` dựng `explicit_definition_record_keys` từ bản ghi định nghĩa của MỌI thực thể nhận ra được, cho MỌI intent (`query_understanding.py` dòng 967). Retrieval nhận danh sách đó rồi **dành sẵn một chỗ ở ĐẦU bằng chứng cho từng bản ghi, bất kể điểm số** (`retrieval.py` dòng 1212 đến 1231). Câu hỏi nào nhắc "RtR" cũng làm hồ sơ pháp nhân chiếm chỗ C1, rồi tầng trả lời trích nguyên văn C1.

Cổng cuối `answer_relevant` không bắt được vì nó chỉ đòi câu trả lời có nhắc đúng tên thực thể, mà hồ sơ pháp nhân thì lúc nào cũng nhắc tên RtR.

Thiết kế này đúng cho câu hỏi "RtR là công ty gì". Nó sai khi áp cho mọi intent.

## 3. Sửa

Một guard ở chỗ gọi retrieval trong `answering.py`:

```python
DEFINITION_AUTHORITY_INTENTS = frozenset({"definition", "enumeration"})
...
query_definition_record_keys=(
    query_plan.definition_record_keys
    if query_plan.intent in DEFINITION_AUTHORITY_INTENTS
    else ()
),
```

Ở intent khác, bản ghi định nghĩa vẫn nằm trong nhóm ứng viên và vẫn được thu hồi, chỉ là phải cạnh tranh bằng điểm. Facet hồ sơ không đụng tới, vì ở intent `lookup` chúng đã được lọc theo đúng câu hỏi trước khi tới đây (`_facet_matches_question`).

Không sửa `plan_query`, nên `QueryPlan.digest` không đổi và dấu vân tay của các gói eval cũ giữ nguyên.

## 4. Acceptance

| ID | Kiểm | Đạt khi |
|---|---|---|
| DA-001 | `probe_retrieval.py` phần 2 | G1 và G3 trích `L3F.INF.014`, không phải `L3F.ENT.001` |
| DA-002 | `capture_use_class.py` | Không câu nào trích `L3F.ENT.001`; MS-009 trích `SPEC.HERASIGHT.STD.NETD`, MS-011 trích `SPEC.VEGA.RTK` |
| DA-003 | Câu định nghĩa thật: "RtR là công ty gì?" | VẪN trả lời bằng `L3F.ENT.001`. Đây là cổng chống sửa quá tay |
| DA-004 | `eval/run_eval.py` và gói TIP-026 | Không hồi quy. Chạy trong container vì `uv` không dựng được môi trường trên macOS |

## 5. Rủi ro

Gói eval cũ nào cam kết bản ghi định nghĩa phải là C1 cho câu hỏi intent `lookup` sẽ đổi kết quả. Đó là rủi ro thật và là lý do DA-003, DA-004 tồn tại. Nếu hồi quy, hoàn tác chỉ là bỏ một guard.

## 6. Việc còn mở sau gói này

| ID | Việc |
|---|---|
| TIP-051.1 | `answer_relevant` nên đòi câu trả lời chạm được nội dung câu hỏi chứ không chỉ nhắc tên thực thể. Đây mới là lưới an toàn thật: có nó thì câu hỏi SOC 2 ra honest-null thay vì ra tên pháp nhân |
| TIP-051.2 | Thu hồi kém với cách hỏi tự nhiên: "Dữ liệu của RtR được lưu ở đâu?" không chạm `L3F.INF.002` ngay ở `/search`, dù hỏi thẳng `us-east-1` thì trúng. Cần bổ sung từ khóa vào `searchable_text` hoặc bật embedding ngữ nghĩa |
| TIP-051.3 | Bộ lập kế hoạch ngữ nghĩa chưa sẵn sàng làm một số câu bị từ chối thẳng (`answer_quality_configuration_required`). Phụ thuộc quyết định khóa LLM của Homeowner |
