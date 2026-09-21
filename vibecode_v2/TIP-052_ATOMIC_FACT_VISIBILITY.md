# TIP-052 · Fact nguyên tử bị cổng nhắc-tên-thực-thể làm cho vô hình

**Ngày:** 21/09/2026
**Mức:** P0 sản phẩm
**Phụ thuộc:** TIP-051 (đã đóng cổng ưu tiên bản ghi định nghĩa)
**Chặn:** VERIFY của TIP-048 và TIP-050

## 1. Triệu chứng và bằng chứng đối chứng

Cùng một nội dung câu hỏi, chỉ khác hai chữ:

| Câu hỏi | Kết quả `/search` |
|---|---|
| "Mật khẩu người dùng được băm bằng thuật toán nào?" | `L3F.INF.014` hạng 2 |
| "Mật khẩu người dùng **của RtR** được băm bằng Argon2id phải không?" | `L3F.INF.014` **vắng mặt hoàn toàn** |
| "Argon2id" | `L3F.INF.014` hạng 1, kết quả duy nhất |

Thêm chữ vào câu hỏi làm mất kết quả đúng. Và những bản ghi sống sót ở câu thứ hai đều là bản ghi mở đầu bằng "RtR có ...": `L3F.2.039`, `L3F.2.021`, `L3F.REG.006`, `L3F.CERT.002`.

Đã loại trừ ba nguyên nhân khác bằng đo đạc: chỉ mục và thu hồi khỏe (mọi bản ghi đích đứng hạng 1 ở `/search` khi hỏi bằng từ khóa); ràng buộc ontology không can thiệp (`prof_n` và `coll_n` bằng 0 trong `answer_runs`, và TIP-051 đã chặn `def_n`); nhánh từ vựng không thiên vị bản ghi dài (`ts_rank_cd` mặc định xếp `L3F.INF.014` hạng 1 đến 2 trong SQL trực tiếp, dù nó chỉ dài 91 ký tự).

## 2. Nguyên nhân

`relevance.candidate_relevance_score`:

```python
if targets:
    matched = targets & mentions
    if (not matched and not collection_anchor and not profile_anchor
            and not definition_anchor and not semantically_bridged):
        return None
```

`targets` là thực thể phân giải từ câu hỏi. `mentions` là thực thể mà bản ghi ứng viên nhắc tới, tính cả khóa bản ghi. Khi câu hỏi nhắc "RtR", mọi ứng viên không chứa chữ "RtR" bị **loại hẳn**, không phải tụt hạng.

`L3F.INF.014` nói "Mật khẩu người dùng được băm bằng Argon2id với salt riêng cho từng người dùng." Không có chữ RtR, và khóa bản ghi `L3F.INF.014` cũng không mang tên thực thể nào. Nó bị loại.

Đây là nghịch lý của chính kỷ luật SOT: TIP-046, TIP-048 và TIP-049 curate fact thành câu ngắn, một dữ kiện một bản ghi, không lặp lại tên công ty vì thừa. Càng sạch thì càng vô hình. Fact sản phẩm thoát được chỉ nhờ khóa bản ghi mang tên sản phẩm (`SPEC.HERA.*` tính là có nhắc HERA), còn `L3F.INF.*` thì không có gì để bấu víu.

## 3. Sửa

Cứu ứng viên **không nhắc thực thể nào cả** và trúng đủ từ quyết định của câu hỏi:

```python
unbound_but_specific = (
    not mentions
    and original_matches >= 2
    and term_overlap >= 0.25
)
```

Điều kiện `not mentions` là điểm mấu chốt: bản ghi nhắc một thực thể KHÁC vẫn bị loại nguyên như cũ, nên tính cách ly giữa HERA và VEGA không suy giảm. Ứng viên được cứu không nhận điểm thưởng coverage nào, nó cạnh tranh thuần bằng độ trùng từ.

## 4. Acceptance

| ID | Kiểm | Đạt khi |
|---|---|---|
| AV-001 | `probe_retrieval.py` phần 2, G1 và G3 | Trích `L3F.INF.014` |
| AV-002 | `probe_retrieval.py` phần 2, G2 và G4 | Honest-null nêu ngữ cảnh chứng thực. Đây là lần đầu cổng TIP-050 nhận được đúng loại bản ghi để chặn |
| AV-003 | `capture_use_class.py` BU-001, BU-002 | BU-001 trích `L3F.INF.*`, BU-002 honest-null |
| AV-004 | Câu chéo sản phẩm: "HERA mang được tải trọng tối đa bao nhiêu?" | Không bản ghi VEGA nào lọt vào citation |
| AV-005 | `capture_use_class.py` toàn bộ | Không tụt so với 12 PASS của lượt TIP-051 |

## 5. Rủi ro

Nới một cổng cách ly thực thể là việc phải cân. Rủi ro thật là một fact không mang tên thực thể nào lọt vào câu hỏi về một thực thể mà nó không thuộc về. Ngưỡng `original_matches >= 2` cùng `term_overlap >= 0.25` giữ cho việc đó chỉ xảy ra khi bản ghi trúng nhiều từ quyết định, và AV-004 canh chiều ngược lại. Hoàn tác là bỏ một mệnh đề.

## 6. Ghi chú cho lần sau

Cổng này do TIP-029 dựng để chữa RECALL-MISS và TIP-014RE nới lần đầu cho embedding thật. Cả hai lần đều đúng với bối cảnh lúc đó. Lần này là bối cảnh thứ ba: kho fact đã chuyển từ văn xuôi dài sang fact nguyên tử ngắn, và luật cũ không còn khớp hình dạng dữ liệu mới. Đây là loại sai lệch chỉ lộ ra khi đo trên dữ liệu thật, không phải khi đọc mã.
