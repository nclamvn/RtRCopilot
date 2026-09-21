# TIP-050 · Cưỡng chế trục use_class ở tầng trả lời

**Ngày:** 21/09/2026
**Chủ thầu:** Claude (Contractor)
**Thợ:** Claude (Builder, cloud workspace + device bridge)
**Homeowner:** Nguyễn Cảnh Lâm
**Phụ thuộc:** TIP-048 (dựng tầng và trục), TIP-048.1 (ánh xạ tầng về Literal), TIP-049 (bộ số master hiện hành)
**Đóng:** deviation D3 của TIP-048

## 1. Vấn đề

TIP-048 nới kỷ luật SOT theo thực tế kinh doanh: thêm tầng `attested_practice` (lời chứng có người đứng tên và ngày) và `roadmap_commitment` (cam kết có chủ và mốc), kèm trục `use_class` ba ngữ cảnh lồng nhau `attestation ⊂ proposal ⊂ sales`. Kernel cưỡng chế trục đó khi curate. Adapter mang nó vào `value_payload` của record. Nhưng tầng trả lời chưa bao giờ đọc tới.

Hệ quả cụ thể: registry hiện có 47 fact `attested_practice` và 5 fact `roadmap_commitment`. Hỏi "mật khẩu người dùng được băm bằng gì" thì `L3F.INF.014` trả lời Argon2id. Câu đó đúng cho một buổi chào hàng. Đưa nguyên văn vào một bản trả lời câu hỏi an ninh của khách hàng chính phủ thì nó trở thành lời khẳng định có hiệu lực chứng thực trong khi RtR chưa có tài liệu ký. Đó chính là loại rủi ro mà TIP-048 dựng trục để chặn, và chặn chưa tới nơi.

Nói ngắn: **phần nới lỏng của TIP-048 mới là mô tả, chưa được máy cưỡng chế.**

## 2. Quyết định thiết kế

**Đặt cổng ở tầng trả lời, không đổi schema, không reindex.** Adapter đã ghi `use_class` và `sot_tier` vào `value_payload` từ TIP-048.1. Đọc payload lúc trả lời là đúng cơ chế TIP-013B đang dùng cho `confidence_signal`, nên không cần cột mới, không cần migration, không đụng xếp hạng và không phải đánh chỉ mục lại 398 record.

**Hai cổng tách bạch.** `require_verified` hỏi *bằng chứng đã kiểm chưa*. `use_class` hỏi *bằng chứng có được phép dùng trong ngữ cảnh này không*. Hai câu hỏi khác nhau nên không gộp: lời gọi `require_verified=False` vẫn giữ nguyên nghĩa là chấp nhận claim, còn trục `use_class` chỉ phân xử giữa các tầng dùng được.

**Mặc định là `proposal`, không phải `sales`.** Theo mục 6 của packet TIP-048: ngữ cảnh chứng thực phải được nêu tường minh chứ không suy đoán, và mặc định không được là mức rộng nhất. Hôm nay chưa fact nào tự khai hẹp tới mức chỉ `sales`, nên chọn `proposal` không đổi kết quả của gói eval nào.

**Thứ tự suy luận tầng, dừng ở bước đầu tiên có dữ liệu.** `value_payload["use_class"]`, rồi `value_payload["sot_tier"]`, rồi `provenance_level`. Bước thứ hai là bước quan trọng nhất: TIP-048.1 ánh xạ `attested_practice` về `approved_internal` để vừa `Literal` của `PackageRecord`, nên nếu chỉ nhìn `provenance_level` thì mọi lời chứng sẽ đội lốt tầng phê duyệt nội bộ và lọt thẳng vào ngữ cảnh chứng thực. Cổng này sẽ tự vô hiệu mà không ai biết.

**Không im lặng.** Nếu trục loại hết bằng chứng, honest-null nói rõ ba điều: ngữ cảnh nào đang áp, có bao nhiêu ghi nhận liên quan ở tầng bị loại và mã của chúng, hỏi lại ở ngữ cảnh nào thì xem được nội dung. Không trích nội dung ghi nhận, vì trích ra tức là đã dùng nó làm căn cứ trong đúng ngữ cảnh vừa cấm.

## 3. Thay đổi theo file

| File | Thay đổi |
|---|---|
| `rag/use_class.py` (mới, 205 dòng) | Module thuần: bảng `TIER_MAX_USE` chép từ kernel, `record_use_classes`, `gate_applies`, `record_allows`, `blocks`, `null_message`, `normalize_use_class`. Không DB, không IO, không phụ thuộc rag khác, nên kiểm được ngoài stack |
| `rag/answering.py` | `_use_class_filtered` đọc `record_versions.value_payload` theo lô một truy vấn, trả về hit giữ lại kèm danh sách mã bị loại; nối vào `ask()` ngay sau cổng `require_verified`; honest-null nhận `answer_override` khi trắng bằng chứng vì trục này |
| `rag/models.py` | `AskRequest.use_class: Literal["sales","proposal","attestation"] = "proposal"` |
| `rag/api.py` | Truyền `body.use_class` ở cả hai chỗ gọi `service.ask` (stream và không stream) |
| `tests/test_tip050_use_class.py` (mới) | 16 case oracle cam kết trước |

## 4. Acceptance Criteria

| ID | Kiểm | Đạt khi |
|---|---|---|
| UC-001 | `pytest tests/test_tip050_use_class.py` | 16/16 xanh |
| UC-002 | `pytest` toàn backend | Không hồi quy so với 717 passed của TIP-038; con số mới ghi vào Verify report |
| UC-003 | `mypy` | Không lỗi mới trên 4 file đã sửa |
| UC-004 | `ruff` | Sạch trên 4 file đã sửa |
| UC-005 | Hỏi UI không nêu ngữ cảnh, câu hạ tầng | Trả lời như trước TIP-050, vì mặc định `proposal` nhận `attested_practice` |
| UC-006 | Gọi API `use_class: "attestation"` cho câu chỉ có nguồn `attested_practice` | Honest-null nêu đúng mã ghi nhận bị loại, không trích nội dung |
| UC-007 | Cùng câu hỏi, `use_class: "attestation"`, nhưng có nguồn `verified_primary` | Vẫn trả lời bình thường bằng nguồn đã kiểm |
| UC-008 | Log `use_class_filtered` | Có `request_id`, `use_class`, `denied_count`; không có nội dung bằng chứng |

## 5. Rủi ro và cách chặn

| Rủi ro | Chặn |
|---|---|
| Cổng mới làm trôi câu trả lời cũ | Mặc định `proposal` nhận đủ tầng đang dùng; UC-005 canh |
| Lời chứng đội lốt `approved_internal` lọt cổng | Bước suy luận thứ hai đọc `sot_tier`; test `test_sot_tier_chan_duoc_loi_chung_doi_lot_approved_internal` canh |
| Cổng chặn nhầm claim khi `require_verified=False` | `gate_applies` trả False cho tầng không dùng được, trả quyền cho cổng cũ; test canh |
| Thêm một truy vấn DB mỗi lượt hỏi | Truy vấn theo khóa chính dạng lô, cùng hình dạng với `_soft_cited_version_ids` của TIP-013B đang chạy production |
| Ba nơi định nghĩa trục lệch nhau (kernel, adapter, backend) | `test_bang_tang_khop_voi_kernel` so bảng; lệch là đỏ ngay |

## 6. Không làm trong gói này

| ID | Việc | Lý do |
|---|---|---|
| TIP-050.D1 | Ô chọn ngữ cảnh trên giao diện web | Chưa chốt vị trí và nhãn; hiện gọi qua API. Cần Homeowner quyết chỗ đặt |
| TIP-050.D2 | Hiện nội dung ghi nhận kèm nhãn "không đủ tư cách chứng thực" ngay trong câu trả lời ở ngữ cảnh attestation | BU-002 của TIP-048 mô tả mức này. Nó đòi sửa tầng dựng câu và nhãn giao diện, rộng hơn phạm vi đóng D3. Bản hiện tại là tập con an toàn hơn: nói có ghi nhận, không trích nội dung |
| TIP-050.D3 | Cưỡng chế `use_class` cho đường `/search` và `/intelligence` | Hai đường đó không dựng câu khẳng định, rủi ro thấp hơn; làm sau khi đường `ask` chạy thật |

## 7. Nguyên tắc

Cổng nào cũng phải có răng và phải tự chứng minh được là nó cắn. Ở gói này, răng là `test_sot_tier_chan_duoc_loi_chung_doi_lot_approved_internal`: nếu ai đó gỡ bước đọc `sot_tier`, test đỏ ngay chứ không đợi tới lúc một lời chứng lọt vào hồ sơ gửi khách.
