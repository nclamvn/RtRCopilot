# TIP-049 · Completion Report (Builder)

**Date:** 21/09/2026 · **Status:** BUILT, kiểm sạch trong cloud · chờ Homeowner áp và onboard
**Phạm vi:** đồng bộ bộ master 14/09/2026 vào kernel, lấp khoảng trống NETD, đóng nợ TIP-046.D4, ban hành quy ước phiên bản.

## 1. Ba phân xử Homeowner 21/09/2026

| # | Nội dung | Áp vào |
|---|---|---|
| 1 | Phần cứng chỉ dùng phiên bản chính v1.0 và v2.0, không dùng phiên bản con; phần mềm được dùng | `L3F.STD.001`, `OBLIG.RTR.VERSION.HARDWARE_MAJOR_ONLY` |
| 2 | VEGA hỗ trợ **cả hai** cấu hình RTK tùy yêu cầu khách | `SPEC.VEGA.RTK` (approved_internal) |
| 3 | Ban hành quy ước và bắt buộc ghi log History, vì đây là tài sản để hiểu tiến trình | `OBLIG.RTR.MASTER_SPEC.HISTORY_LOG` |

Phân xử 2 đảo ngược nghi vấn ở TIP-049 mục 4.2: ô `C38` của VEGA ghi "Integrated RTK-GNSS" trong khi `C16` ghi "RTK and PPK ready" **không phải lỗi bỏ sót** mà là hai cấu hình khác nhau. Đã ghi lại đúng bản chất.

## 2. Việc đã làm

**Nguồn.** Copy cả 9 workbook từ thư mục Downloads vào `source_canonical/master_spec/`, cập nhật 9 dòng trong `source_hashes.yaml`. Kernel giờ là bản sao trung thực của thư mục nguồn.

**18 fact mới trong registry:**

| Nhóm | Số | Ghi chú |
|---|---|---|
| NETD bốn biến thể | 4 | Điểm phân biệt thật: NDAA 20 mK, Standard 40 mK |
| HeraSight61 Standard atomize | 11 | Đóng nợ TIP-046.D4 |
| RTK | 2 | HERA "supports" theo master đã sửa; VEGA cả hai cấu hình theo phân xử |
| Quy ước phiên bản | 1 | `L3F.STD.001` |

**2 nghĩa vụ mới** trong `obligations/standards.yaml`, cả hai `enforcement: HARD`.

**Note bổ sung, không đổi giá trị:** 5 fact `SPEC.HERASIGHT61.*` cũ được làm rõ là lấy từ bản NDAA (biến thể Standard nay có bộ riêng `SPEC.HERASIGHT61.STD.*`); `SPEC.HERA.GNSS` và `SPEC.HERA.CONNECTIVITY` được thêm cảnh báo không dùng cụm "Integrated" cho HERA.

## 3. Kiểm định

| Phép thử | Kết quả |
|---|---|
| Guard A3 + cổng use-class TIP-048 | **Sạch** |
| `validate.py` | 441 entry, 0 issue, 0 trùng ID. Sáu dòng "Source missing" chỉ do mirror cloud thiếu `source_canonical/`; trên máy sẽ sạch |
| Adapter dry-run, **model pydantic thật** | ready 380 lên **398**. Strict 103 lên 120. Cả 18 fact mới đều ready, không cái nào rơi needs_curation |
| Em-dash trong fact mới | 0 |

**Cổng TIP-048 đã cắn một lần trong lúc thi công.** Tôi đặt fact quy ước phiên bản ở `SPEC.RTR.VERSION_SCHEME`, cổng chặn với lý do `hard_floor_attestation_without_document`: tiền tố `SPEC.` bị coi là thông số sản phẩm, mà một quy ước do Homeowner chốt thì không có tài liệu nguồn. Cổng đúng, phân loại của tôi sai. Đã chuyển thành `L3F.STD.001` trong `l3_facts.yaml`, đúng bản chất là quy ước tổ chức chứ không phải thông số. Đây là lần đầu cổng bắt lỗi thật của người dùng chính nó.

## 4. Còn mở

| # | Việc | Chờ |
|---|---|---|
| 049.1 | HERA có cấu hình RTK tích hợp như VEGA không | Quoc Luong. Hiện HERA ghi "supports" theo master; nếu cũng có tùy chọn tích hợp thì sửa `SPEC.HERA.RTK` cho đối xứng với VEGA |
| 049.2 | DualSight `L3R.1.015` đang ghi NETD ≤20 mK | Không có master DualSight để đối chiếu. Nếu 20 mK cũng chép từ bản NDAA thì sai như HeraSight Standard trước đây |
| 049.3 | Đổi tên file master cho khớp quy ước mới | Homeowner quyết có đổi `V1.0.1` trong tên file hay giữ và chỉ tách nghĩa như `L3F.STD.001` mô tả |
