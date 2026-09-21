# TIP-049 · Rà soát sai lệch bộ RTR Master Specification bản 14/09 trước khi đồng bộ

**Status:** AUDIT XONG · chờ Homeowner phân xử 2 mục rồi mới thi công
**Date:** 21/09/2026
**Priority:** P1
**Nguồn mới:** `/Users/os/Downloads/RTR Master Specification` (Homeowner kết nối 21/09)
**Nguồn đang dùng:** `kernel/source_canonical/master_spec/` (9 file, nạp 16/09 theo TIP-046, registry `e99624f`)

## 0. Kết luận trước, chi tiết sau

**SOT hiện tại KHÔNG có số nào sai.** Không một fact `SPEC.*` nào trỏ vào ba ô đã thay đổi. Việc đồng bộ lần này là cập nhật nguồn và lấp một khoảng trống, không phải chữa lỗi.

Quy mô thay đổi nhỏ hơn nhiều so với vẻ ngoài: 7 trong 9 file lệch hash, nhưng chỉ **3 ô** thực sự đổi nội dung.

## 1. Đối chiếu ba nơi

Băm sha256 (16 ký tự đầu) và so từng ô. Cả hai bản đều có **1189 ô có dữ liệu**, cùng bộ sheet, không ô nào thêm hay mất.

| File | Downloads (mới) | kernel (đang dùng) | mtime cũ → mới | Nội dung |
|---|---|---|---|---|
| HERA 2.0-MASTER-V1.0.1 | `13d902d5b6c7a693` | `7b3b2441685f3aa5` | 31/08 → **14/09** | **ĐỔI 1 ô** |
| HeraSight-Standard-MASTER-V1.0 | `888f64da6a550f7b` | `73013420603eeb27` | 05/09 → **14/09** | **ĐỔI 1 ô** |
| HeraSight61-standard-MASTER-v1.0 | `0d0c945d7767592d` | `cbc7a63b90f803d6` | 05/09 → **14/09** | **ĐỔI 1 ô** |
| HERASIGHT-NDAA-MASTER-V1.0 | `cc5f0c82f3ae68de` | `f332223f962ca64c` | 31/08 (không đổi) | giống hệt |
| LoudSpeaker -MASTER-V1.0 | `7a61e98caffcc68b` | `e3932b117d116349` | 31/08 (không đổi) | giống hệt |
| Spotlight-MASTER-V1.0 | `7e56c9fb5a99d036` | `f5d742c01898185e` | 31/08 (không đổi) | giống hệt |
| Tether System-MASTER-V1.0 | `d6dc9f7e4a7b297c` | `518e5471f4a3861e` | 31/08 (không đổi) | giống hệt |
| HeraSight61-NDAA-MASTER-v1.0 | `f103611d37ce90b1` | `f103611d37ce90b1` | 05/09 (không đổi) | trùng hash |
| VEGA-MASTER-V1.0 | `fe32b066a830aca9` | `fe32b066a830aca9` | 21/07 (không đổi) | trùng hash |

Bốn file lệch hash nhưng cùng mtime và **nội dung ô giống hệt**: container zip của xlsx bị ghi lại (đồng bộ đám mây hoặc lưu lại bằng công cụ khác), không phải sửa số. Không có ý nghĩa nghiệp vụ.

## 2. Ba thay đổi thật

### 2.1 HERA 2.0 · `Specs!C36` · cường độ tuyên bố RTK

```
CŨ : Supports multi-link: RF, Cellular, Starlink, Tether. / Integrated RTK-GNSS
MỚI: Supports multi-link: RF, Cellular, Starlink, Tether. / Supports RTK-GNSS
```

Đây là ô thuộc nhóm HeraHub (C34 thời gian hoạt động, C35 sáu luồng video). Thay "Integrated" bằng "Supports" là **hạ cường độ tuyên bố**: tích hợp sẵn khác với tương thích.

Đánh giá: đây là sửa cho nhất quán nội bộ. Ô `C16` của chính HERA ghi "RTK and PPK ready", tức "sẵn sàng" chứ không phải "tích hợp". Bản cũ mâu thuẫn với chính nó, bản mới hết mâu thuẫn.

### 2.2 và 2.3 HeraSight Standard và HeraSight61 Standard · độ nhạy nhiệt NETD

```
CŨ : Professional: ≤20 mK
MỚI: ≤40 mK
```

Đây không phải hạ cấp sản phẩm mà là **sửa lỗi chép nhầm**. So bốn biến thể trong bộ master mới:

| Biến thể | NETD |
|---|---|
| HeraSight NDAA | Professional: ≤20 mK (giữ nguyên) |
| HeraSight Standard | ≤40 mK (sửa từ 20) |
| HeraSight61 NDAA | Professional: ≤20 mK (giữ nguyên) |
| HeraSight61 Standard | ≤40 mK (sửa từ 20) |

Cả cụm chữ "Professional:" lẫn con số 20 mK trước đây bị chép nguyên từ bản NDAA sang bản Standard. Bản mới tách đúng: NDAA dùng cảm biến nhạy hơn, Standard 40 mK.

**Cả ba thay đổi đều làm thông số kém đi hoặc yếu đi.** Đó là dấu hiệu của sửa đúng, không phải thổi phồng. Độ tin cậy cao.

## 3. Ảnh hưởng tới kernel: không có fact nào sai

Truy từng fact `SPEC.*` (107 fact) theo `source.cell`:

| Ô đổi | Fact trỏ vào | Kết quả |
|---|---|---|
| HERA `Specs!C36` | không có | `SPEC.HERA.CONNECTIVITY` lấy từ `C22`, `SPEC.HERAHUB.*` lấy từ C34 và C35. Không fact nào chạm C36 |
| HeraSight-Standard `C49` | không có | Kernel chưa có fact NETD nào |
| HeraSight61-Standard `C64` | không có | HeraSight61 Standard chưa được atomize (nợ TIP-046.D4) |

Kiểm chéo: `SPEC.HERA.GNSS` (ô C16) ghi "RTK/PPK ready", **khớp** với cách diễn đạt mới "Supports RTK-GNSS". Không cần sửa.

Kết luận: không phải sửa một fact nào. Đồng bộ lần này là thay nguồn và bổ sung, không phải chữa cháy.

## 4. Năm phát hiện cần xử lý

### 4.1 Khoảng trống: kernel không có fact NETD nào (nên lấp)

Sau thay đổi này, NETD trở thành **điểm phân biệt thật giữa bản NDAA và bản Standard** (20 mK so với 40 mK). Đây là con số bán hàng và hồ sơ thầu cần, mà SOT đang không trả lời được. Đề xuất thêm 4 fact `SPEC.HERASIGHT*.NETD`.

### 4.2 Bộ master mới tự mâu thuẫn: VEGA chưa được sửa theo HERA

HERA `C36` đã sửa thành "Supports RTK-GNSS", nhưng VEGA `Specification !C38` **vẫn ghi "Integrated RTK-GNSS"**, trong khi VEGA `C16` cũng ghi "RTK and PPK ready" y như HERA.

Nghĩa là VEGA giờ mang đúng cái mâu thuẫn mà HERA vừa được chữa. Nhiều khả năng đợt sửa 14/09 bỏ sót VEGA.

**Cần Quoc Luong xác nhận:** VEGA có RTK tích hợp thật, hay cũng chỉ "supports" như HERA? Trước khi có trả lời, không dùng cụm "Integrated RTK" cho VEGA trong tài liệu ra ngoài.

### 4.3 Quản trị phiên bản: nội dung đổi mà số hiệu không đổi

Ba file sửa ngày 14/09 nhưng **vẫn mang tên V1.0.1 và V1.0**, và sheet `History` của HERA chỉ có đúng một dòng cũ (16/07, đổi màn hình, Quoc Luong duyệt). **Không dòng nào ghi lần sửa 14/09.**

Hệ quả: nhìn tên file hoặc sheet History không thể biết nội dung đã đổi. Lần này phát hiện được là nhờ băm hash và so từng ô, không phải nhờ quy trình.

**Đề xuất quy ước:** mỗi lần sửa master thì tăng số hiệu (V1.0.2) và thêm một dòng vào `History` gồm ngày, ô đã đổi, người duyệt. Nếu Homeowner đồng ý, ghi thành nghĩa vụ trong `obligations/standards.yaml` để cổng kiểm tra được.

### 4.4 Cần kiểm chứng: DualSight cũng đang ghi NETD ≤20 mK

Fact `L3R.1.015` mô tả DualSight với "FLIR Boson/Boson+ 640x512 NETD ≤20 mK". Nếu con số 20 mK ở bản HeraSight Standard là chép nhầm, rất có thể DualSight cũng chép từ cùng một nguồn.

Không có master DualSight trong bộ này nên **tôi không khẳng định là sai**, chỉ nêu để kiểm. Fact này hiện ở tầng thấp, chưa vào tài liệu cam đoan.

### 4.5 Nợ cũ liên quan: HeraSight61 Standard vẫn chưa atomize

TIP-046.D4 để mở. Giờ bản này đã có NETD khác bản NDAA, tức có nội dung riêng đáng nạp. Nên gộp vào đợt đồng bộ này.

## 5. Kế hoạch đồng bộ đề xuất (chưa chạy, chờ duyệt)

| # | Việc | Ghi chú |
|---|---|---|
| S1 | Copy **cả 9 file** từ Downloads vào `kernel/source_canonical/master_spec/`, cập nhật đủ 9 dòng hash trong `source_hashes.yaml` | Thay cả 9 thay vì chỉ 3, để kernel là bản sao trung thực của thư mục nguồn. Chi phí thêm bằng không, tránh lệch byte về sau |
| S2 | Thêm 4 fact `SPEC.HERASIGHT.NDAA.NETD`, `SPEC.HERASIGHT.STD.NETD`, `SPEC.HERASIGHT61.NDAA.NETD`, `SPEC.HERASIGHT61.STD.NETD` | Tầng `verified_primary`, có ô và raw_text, đạt tier strict |
| S3 | Atomize HeraSight61 Standard (đóng TIP-046.D4) | Các fact còn thiếu của biến thể này |
| S4 | Ghi note vào `SPEC.HERA.GNSS` và `SPEC.HERA.CONNECTIVITY`: master 14/09 dùng "Supports RTK-GNSS", không dùng "Integrated" | Chặn tài liệu tương lai dùng sai cụm |
| S5 | Mở cờ cho VEGA RTK theo mục 4.2, chờ Quoc Luong | Không nạp fact khẳng định cho tới khi có trả lời |
| S6 | `bash check.sh` phải PASS exit 0, rồi onboard `--revision 11` | Chu trình đã chứng minh 4 lần |

Ước lượng: khoảng 12 đến 16 fact mới, không sửa fact cũ nào ngoài thêm note.

## 6. Hai việc cần Homeowner phân xử

| # | Việc | Đề xuất |
|---|---|---|
| 1 | VEGA có RTK tích hợp hay chỉ tương thích (mục 4.2) | Hỏi Quoc Luong. Trong lúc chờ, tài liệu ra ngoài dùng "supports" cho cả hai, vì đó là mức thấp hơn và an toàn hơn |
| 2 | Có ban hành quy ước tăng số hiệu và ghi History khi sửa master không (mục 4.3) | Có. Ghi thành nghĩa vụ để lần sau phát hiện được bằng quy trình chứ không nhờ may |

## 7. Nguyên tắc áp dụng

- Bộ master 14/09 là nguồn sơ cấp mới. Số cũ không xóa, chuyển lịch sử có note.
- Không nạp fact khẳng định cho điểm đang mâu thuẫn giữa hai master (VEGA RTK).
- NETD thuộc thông số kỹ thuật sản phẩm, tức nhóm 4 của sàn cứng TIP-048: chỉ nhận bằng chứng tài liệu, không nhận tầng thực hành.
