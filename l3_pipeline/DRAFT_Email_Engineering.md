# Draft email gửi Engineering · cập nhật 27/07/2026

**Trạng thái:** hai điểm cũ (IP54 vs IP43, 15 km vs 10 km) đã ĐÓNG — curator chốt 27/07/2026 rằng IP43 và 10 km là số cũ chưa cập nhật; file gốc đã sửa. Email này giờ là **thông báo đã sửa + ba điểm còn cần Engineering**.
**Người gửi:** Lâm · **Người nhận:** Engineering lead · **CC:** đội bảo dưỡng

---

**Subject:** Đã cập nhật spec baseline trong bộ workbook bảo dưỡng · và 3 điểm cần team xác nhận

Chào team,

Trong quá trình chuẩn hoá nguồn sự thật cho công ty, bên mình rà lại bộ workbook Chương trình bảo dưỡng và thấy một số thông số baseline lấy từ hồ sơ DCMA cũ, không khớp spec hiện hành đã chốt. Mình đã cập nhật, báo team nắm và đối chiếu.

## Đã sửa

| Thông số | Cũ trong workbook | Đã sửa thành | Căn cứ |
|---|---|---|---|
| Kháng bụi/nước HERA | IP43 | **IP54** | HC-042 · certified · verified_primary |
| Tầm điều khiển HERA | 10 km | **15 km** | HC-001 · chốt CEO 16/07/2026 |
| Tải trọng tối đa HERA | 15 kg | **14 kg** | signature 1-4-14 hiện hành |
| Định danh model | HERA 1-4-15 | **HERA 1-4-14** | cùng lý do · 9 ô trong 3 file |

Bản gốc trước khi sửa lưu tại `KnowledgeBase/_archives/maintenance_workbooks_truoc_SPECFIX01_20260727/`. Hai dòng tương ứng trong Gap Register (file 00 Tổng thể) đã chuyển "Đã chốt".

## Ba điểm mình chưa tự sửa · cần team xác nhận

**1 · MTOW HERA: 31 kg hay 30,5 kg?**
Workbook ghi 31 kg, nguồn đối chiếu ghi 30,5 kg. Là làm tròn hay hai con số khác nhau? Cần thống nhất một giá trị để tài liệu gửi khách không lệch.

**2 · Workbook HeraHub ghi "Tầm truyền 10 km"**
HeraHub là GCS của HERA (15 km), trong khi 10 km đúng là tầm của VEGA. Nghi số này lẫn từ hồ sơ VEGA sang. Nhờ team xác nhận tầm truyền thật của HeraHub.

**3 · Nhiệt độ vận hành: hai con số cùng đúng?**
Workbook ghi -20°C đến 45°C (khuyến cáo vận hành cho bảo dưỡng), nguồn đối chiếu ghi -30°C đã validated tại US Army Alaska. Mình hiểu là hai ngữ cảnh khác nhau nên đã ghi chú tách bạch chứ không sửa. Team xác nhận cách hiểu này đúng, và cho biết nên dùng con số nào khi trả lời khách.

## Một việc nữa: mốc bảo dưỡng đang treo

Toàn bộ chu kỳ và mốc trong chương trình v1.0 đang mang nhãn **PROPOSED** (3 tháng/3.000 km, 6 tháng, 12 tháng...). Nhãn này nghĩa là nội bộ dùng được nhưng không cam kết với khách. Team ký duyệt được thì mình gỡ nhãn; chưa duyệt thì giữ nguyên, không sao.

Trả lời thẳng vào email theo số thứ tự là đủ, không cần họp.

Cảm ơn team.

Lâm

---

## Ghi chú cho người gửi (xoá trước khi gửi)

- Ba câu đều dạng đóng, trả lời một dòng mỗi câu.
- Câu 2 có giá trị nhất: nếu đúng là lẫn từ VEGA sang thì khả năng còn chỗ khác lẫn tương tự, đáng rà một lượt.
- Cố ý KHÔNG hỏi lại "IP43 hay IP54". Hỏi lại việc đã chốt làm loãng ba câu thật sự cần trả lời.
