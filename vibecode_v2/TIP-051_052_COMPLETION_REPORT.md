# TIP-051 và TIP-052 · Completion Report (Builder)

**Ngày:** 21/09/2026
**Phạm vi:** đường trả lời của Copilot, từ kế hoạch truy vấn tới chấm điểm ứng viên
**Trạng thái:** TIP-051 DONE có số liệu. TIP-052 PARTIAL, đã dịch chuyển nhưng chưa lật được thứ hạng. Nguyên nhân cuối đã đo được và đặt tên, chuyển TIP-053.

## 1. Vì sao có hai gói này

Chúng không nằm trong kế hoạch. Chúng sinh ra từ lượt VERIFY đầu tiên của TIP-050, khi 7 trên 16 câu hỏi được trả lời bằng `L3F.ENT.001`, bản ghi tên pháp nhân, mà vẫn mang nhãn `grounded`. Hỏi RtR có chứng nhận SOC 2 không thì hệ thống trả tên công ty và mã số thuế.

Ba gói TIP-048, TIP-049 và TIP-050 đều không thể VERIFY khi tầng trả lời còn như vậy.

## 2. TIP-051 · thu hẹp quyền ưu tiên của bản ghi định nghĩa

**Đo trước khi sửa.** `/api/v1/search` trả đúng bản ghi ở hạng 1 cho mọi câu thử: `SPEC.HERASIGHT.STD.NETD`, `SPEC.VEGA.RTK` lex 1,70, `L3F.STD.001` lex 2,40, `L3F.INF.014` cho từ khóa `Argon2id`. Cùng câu hỏi đi qua `/api/v1/ask` thì ra `L3F.ENT.001`, bản ghi không có trong sáu hạng đầu của `/search`. Khác biệt duy nhất là bộ lập kế hoạch.

**Nguyên nhân.** `plan_query` dựng `explicit_definition_record_keys` từ bản ghi định nghĩa của mọi thực thể nhận ra được, cho mọi intent. Retrieval dành sẵn một chỗ ở đầu bằng chứng cho từng bản ghi đó, bất kể điểm số.

**Sửa.** Guard một dòng ở chỗ gọi retrieval: chỉ dành chỗ ưu tiên khi intent là `definition` hoặc `enumeration`. Không sửa `plan_query` nên `QueryPlan.digest` không đổi.

**Kết quả đo được.** 6 PASS lên 12 PASS trên 16 case. `L3F.ENT.001` biến mất khỏi mọi câu trả lời. Bốn case của TIP-049 là MS-009 đến MS-012 chuyển xanh **với điều kiện trích dẫn được siết**, tức trả lời bằng đúng `SPEC.HERASIGHT.STD.NETD`, `SPEC.HERASIGHT61.NDAA.NETD`, `SPEC.VEGA.RTK`. Bộ số master ba phiên curate lần đầu tiên tới được người dùng.

## 3. TIP-052 · fact nguyên tử bị cổng nhắc-tên-thực-thể loại

**Đo.** Cùng nội dung câu hỏi, thêm hai chữ "của RtR" thì `L3F.INF.014` biến mất khỏi `/search`. Hỏi trần `Argon2id` thì nó là kết quả duy nhất.

**Nguyên nhân.** `candidate_relevance_score` trả `None` cho mọi ứng viên không nhắc tên thực thể khi câu hỏi có nhắc thực thể. Fact nguyên tử curate theo kỷ luật TIP-046/048/049 không lặp tên công ty vì thừa, nên bị loại. Fact sản phẩm thoát nhờ khóa bản ghi mang tên sản phẩm.

**Sửa (052).** Cứu ứng viên không nhắc thực thể nào cả mà trúng ít nhất hai từ quyết định và phủ trên 25 phần trăm. Bản ghi nhắc một thực thể khác vẫn bị loại nguyên như cũ.

**Sửa (052.1).** Sau 052, hàm không còn loại nhưng `L3F.INF.014` vẫn thua điểm. Đo bằng chính hàm thật: nó trúng 7/9 từ được 0,702, còn `L3F.2.039` trúng 3/9 từ được 1,047, vì mở đầu bằng "RtR có ..." nên ăn trọn 0,62 tiền thưởng nhắc tên. Ba biến thể công thức được chấm trên cùng tập ba case trước khi chọn; chỉ biến thể nhân thưởng với độ trùng chủ đề đúng cả ba. Đã đem vào mã.

**Kết quả.** Bảng 16 case không đổi, vẫn 12 PASS. Nhưng thứ hạng đã dịch, xem mục 4.

## 4. Nguyên nhân cuối, đã đo trên chỉ mục thật

`eval/tip050/live_rank.py` lấy đúng văn bản chunk trong generation đang hoạt động và chấm bằng đúng hàm thật:

| bản ghi | ts_rank_cd | điểm cuối | nhắc thực thể |
|---|---|---|---|
| L3F.2.039 | 0,50 | **0,754** | Real-time Robotics |
| L3F.REG.006 | 0,80 | 0,744 | HERA, Real-time Robotics |
| **L3F.INF.014** | **0,90** | 0,725 | không nhắc ai |

Bản ghi chứa câu trả lời có điểm từ vựng **cao nhất bảng** mà đứng hạng ba, thua 0,029.

Lý do nằm ở trọng số. Điểm từ vựng thật chỉ vào công thức qua số hạng `min(lex, 1.0) * 0.1`, tức chênh lệch 0,90 so với 0,50 chỉ đáng 0,04 điểm. Phần còn lại của điểm đến từ thưởng nhắc tên thực thể và độ trùng từ tính trên văn bản chunk, mà một chunk dài thì trùng nhiều từ một cách hiển nhiên.

**Nói gọn: hệ thống đang xếp "có nhắc tên công ty và dài" cao hơn "thật sự chứa câu trả lời".** Nó không có khái niệm từ hiếm. Chữ `argon2id` chỉ xuất hiện trong một bản ghi duy nhất của toàn kho, nhưng nó được tính ngang với chữ `nguoi` hay `dung` vốn có mặt khắp nơi.

TIP-052 và 052.1 đã kéo khoảng cách từ "loại hẳn" xuống còn 0,029. Đó là tiến bộ đo được và giữ lại. Nhưng lật được thứ hạng thì cần đổi trọng số, và đó là việc của gói sau.

## 5. Chuyển TIP-053

Đề xuất: đưa độ hiếm của từ vào chấm điểm. Hai đường, cần Homeowner chọn:

- **Nâng trọng số bằng chứng từ vựng.** Đổi hệ số `0.1` trong `base_fusion` lên mức đủ để chênh lệch `ts_rank_cd` quyết định được thứ hạng. Một hằng số, hoàn tác dễ, nhưng là chỉnh mù nếu không có bộ eval đủ rộng.
- **Thêm IDF thật.** Chấm trọng số từ theo tần suất trong kho, để `argon2id` đáng giá hơn `nguoi`. Đúng bản chất vấn đề, tốn công hơn, và cần một lần quét kho để dựng bảng tần suất.

Khuyến nghị của Builder: đường thứ hai, vì đường thứ nhất chữa triệu chứng của đúng một câu hỏi và có thể làm hỏng những câu đang đúng.

## 6. Trạng thái ba gói đang treo

| Gói | Trạng thái | Chặn bởi |
|---|---|---|
| TIP-049 | Nội dung ĐÃ tới được người dùng, 4 case MS xanh có trích dẫn đúng | MS-013 chờ bộ lập kế hoạch ngữ nghĩa, tức khóa LLM của Homeowner |
| TIP-050 | Cổng đã cài, đã có test đơn vị 16/16, **chưa kiểm được trên đường chạy thật** | Retrieval chưa đưa bản ghi `attested_practice` tới cổng. Phụ thuộc TIP-053 |
| TIP-048 | Như trên, BU-002 là case quyết định | Phụ thuộc TIP-053 |

Không gói nào được ghi PASS.

## 7. Ghi nhận về cách làm

Bốn vòng chẩn đoán, ba lần sửa, một lần đúng ngay. Hai lần trượt có chung một kiểu sai: tôi đo bằng dữ liệu tự dựng lại trong script thay vì dữ liệu hệ thống thật đang dùng, nên phép đo trông chặt mà đang trả lời câu hỏi khác. `bonus_probe.py` chấm trên đoạn văn gõ tay cho ra 0,633 cho `L3F.2.039`; `live_rank.py` chấm trên chunk thật cho ra 0,754. Chênh lệch đó chính là chỗ hai vòng sửa bị trượt.

Luật rút ra, đề nghị đưa vào Vibecode Kit: **phép đo phải lấy dữ liệu từ hệ thống đang chạy, không được dựng lại bằng tay.** Nếu phải gõ tay thì đó là phác thảo giả thuyết, không phải bằng chứng, và không được dùng làm căn cứ để sửa mã.
