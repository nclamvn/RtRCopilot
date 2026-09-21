# TIP-050 · Completion Report (Builder)

**Ngày:** 21/09/2026
**Builder:** Claude (cloud workspace cho phần kiểm, device bridge cho phần sửa tại chỗ)
**Phạm vi:** `rag/use_class.py`, `rag/answering.py`, `rag/models.py`, `rag/api.py`, `tests/test_tip050_use_class.py`, `eval/tip050/capture_use_class.py`
**Trạng thái:** BUILT · test đơn vị xanh ngoài stack · **CHƯA QUA VERIFY tích hợp**, chờ Homeowner chạy runbook

## 1. Đã làm

Đóng deviation D3 của TIP-048: trục `use_class` từ chỗ chỉ là mô tả trong kernel nay được cưỡng chế ở tầng trả lời.

| Thành phần | Nội dung |
|---|---|
| `rag/use_class.py` (mới, 205 dòng) | Module thuần. Bảng `TIER_MAX_USE` chép từ kernel, thứ tự suy luận ba bước (`use_class` trong payload, rồi `sot_tier`, rồi `provenance_level`), `gate_applies` tách thẩm quyền với cổng `require_verified`, `null_message` dựng câu honest-null có nội dung |
| `rag/answering.py` | `_use_class_filtered` đọc `record_versions.value_payload` theo lô một truy vấn, trả về hit giữ lại kèm mã bị loại; cắm ngay sau cổng `require_verified`; honest-null nhận `answer_override` khi trục này loại hết bằng chứng |
| `rag/models.py` | `AskRequest.use_class`, mặc định `proposal` |
| `rag/api.py` | Truyền ngữ cảnh ở cả hai chỗ gọi `service.ask` |
| `tests/test_tip050_use_class.py` | 16 case, oracle viết trước khi nối vào `answering.py` |
| `eval/tip050/capture_use_class.py` | Bàn thử tự động 16 case chạy thẳng vào stack, in PASS/FAIL, thoát 1 khi P0 hỏng |

Không đổi schema, không migration, không reindex, không đụng xếp hạng. Cơ chế đọc payload chỉ-đọc là cơ chế TIP-013B đang chạy production cho `confidence_signal`.

## 2. Bằng chứng đã có

```
16 passed in 0.04s
```

Chạy trong cloud workspace bằng **chính file module thật** được stage từ máy Homeowner, không phải bản chép tay. Đây là phản ứng trực tiếp với bài học TIP-048.1: lần đó dry-run dùng backend giả nên không bắt được vi phạm `Literal` của `PackageRecord`, và Phase 4 chết khi chạy thật. Lần này mọi logic phán xử nằm trong một module không phụ thuộc gì, nên bàn thử ngoài stack kiểm được đúng thứ sẽ chạy trong stack.

Hai case đáng chú ý:

- `test_sot_tier_chan_duoc_loi_chung_doi_lot_approved_internal`: đúng cái bẫy mà TIP-048.1 tạo ra. Vì `attested_practice` bị ánh xạ về `approved_internal` để vừa `Literal`, nếu cổng mới chỉ nhìn `provenance_level` thì mọi lời chứng sẽ lọt vào ngữ cảnh chứng thực và cổng tự vô hiệu mà không ai biết.
- `test_bang_tang_khop_voi_kernel`: so bảng tầng của backend với bảng của kernel. Ba nơi định nghĩa trục này (kernel, adapter, backend) lệch nhau là hỏng doctrine, và lệch thì test đỏ ngay.

## 3. Chưa có bằng chứng

Bridge không với tới Docker trên máy Homeowner, nên bốn thứ sau chưa chạy lần nào:

| Cổng | Vì sao chưa |
|---|---|
| UC-002 pytest toàn backend | Cần venv và DB trên máy Homeowner |
| UC-003 mypy, UC-004 ruff | Như trên |
| UC-005 đến UC-008 | Cần stack chạy |
| BU-001 đến BU-006, MS-009 đến MS-014 | Cần stack chạy |

Không suy đoán kết quả cho các cổng này. Runbook ở `TIP-050_VERIFY_RUNBOOK.md` có đủ lệnh theo thứ tự.

## 4. Deviation

| ID | Nội dung | Trạng thái |
|---|---|---|
| TIP-050.D1 | Giao diện web chưa có ô chọn ngữ cảnh; `attestation` hiện chỉ gọi được qua API | Chờ Homeowner quyết vị trí và nhãn |
| TIP-050.D2 | BU-002 của TIP-048 mô tả mức "nêu rõ chưa có chính sách ký, KÈM thực hành hiện có". Bản này dừng ở tập con an toàn hơn: nói có bao nhiêu ghi nhận và mã của chúng, không trích nội dung. Trích nội dung trong ngữ cảnh chứng thực đòi sửa tầng dựng câu và nhãn giao diện, rộng hơn phạm vi đóng D3 | Chờ Homeowner phân xử: tập con an toàn là đủ, hay cần hiện nội dung kèm nhãn |
| TIP-050.D3 | `/search` và `/intelligence` chưa cưỡng chế trục này | Rủi ro thấp hơn vì hai đường đó không dựng câu khẳng định |
| TIP-050.D4 | Mặc định đổi từ `sales` (bản nháp đầu) sang `proposal` theo mục 6 của packet TIP-048 | Đã sửa trong gói này, ghi lại để đối chiếu |

## 5. Phát hiện ngoài kế hoạch

**F1. Cổng sàn cứng bắt theo chữ, không theo nghĩa.** `HARD_FLOOR_PATTERN` trong `provenance_rules.py` có mẫu `data residency|cư trú dữ liệu`, nhưng `L3F.INF.002` nói hạ tầng đặt trên AWS vùng `us-east-1` mà không chứa cụm chữ nào trong mẫu, nên lọt và đang ở tầng `attested_practice`. Cư trú dữ liệu là nhóm 3 của sàn cứng, đáng lẽ không được dùng tầng thực hành. TIP-050 vá được hệ quả (ở ngữ cảnh chứng thực fact này bị giữ lại) nhưng không vá nguyên nhân. Hai hướng xử lý và khuyến nghị nằm ở mục 5 của runbook.

**F2. Không fact nào nói RtR chưa có SOC 2.** Câu hỏi thẳng sẽ ra honest-null. Không sai nhưng không hữu ích. Đề nghị thêm `L3F.CERT.004` dạng sổ phủ định liệt kê chứng nhận chưa có và chưa theo đuổi, tầng `derived_from_verified` vì suy ra được từ `L3F.CERT.001/002`.

## 6. Không làm

Không chạm kernel, không chạm registry, không onboarding, không đổi revision. Runtime vẫn ở revision 11 của TIP-049. Không secret vào repo hay chat. Không xóa file nào trên máy Homeowner.
