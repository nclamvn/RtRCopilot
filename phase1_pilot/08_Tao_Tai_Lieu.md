# Tạo tài liệu · cách hoạt động và cách thêm bản mẫu

Copilot **không dựng file từ trống**. Nó điền vào bản mẫu thật đã có, giữ nguyên thể thức do người soạn. Hai lý do: định dạng công văn nhà nước và khung workbook là thứ dựng lại chắc chắn lệch, và cách này không cần cài thêm thư viện nào.

## Ba loại trường

| Loại | Ai quyết | Ví dụ |
|---|---|---|
| Người nhập | nhân viên | số công văn, nơi nhận, nội dung |
| Fact khoá | nguồn sự thật | tên pháp nhân, người ký · **không sửa tay được** |
| Suy ra | máy tính từ trường khác | ngày ký tách thành ngày / tháng / năm |

Fact khoá hiện trong giao diện với viền vàng và mã record. Bấm vào mã là mở hồ sơ record.

## Cổng chặn (NT-4)

Tài liệu **không** xuất ra khi:

- thiếu bất kỳ trường bắt buộc nào
- fact khoá không giải được từ gói SOT đang phục vụ
- record của fact khoá đã bị đánh dấu spec cũ

Trạng thái hiện ở góc phải: `READY` · `PASS` · `FAIL-LOUD` · `BLOCKED BY CONFLICT`. Thiếu điều kiện thì chặn hẳn, **không xuất bản nháp** — bản nháp thiếu số là thứ dễ gửi nhầm nhất.

Mỗi lần xuất đều ghi vào nhật ký kèm danh sách record đã dùng, nên truy ngược được tài liệu nào lấy số từ đâu.

## Điền nhanh từ mô tả (cần chế độ LIVE)

Ô trên cùng của form: tả bằng lời việc cần làm, bấm **Điền sẵn giúp tôi**. Model đọc yêu cầu rồi điền vào các trường người nhập.

Ba ràng buộc, đúng NT-4:

- Model **chỉ bóc tham số**, không tạo file. Bộ render vẫn là thứ sinh ra tài liệu.
- Trường nào bác không nói rõ thì **để trống** — không suy đoán, không bịa số công văn hay ngày tháng.
- Model **không được lấy thông tin từ gói tri thức** để điền vào đây; fact khoá đi đường riêng.

Điền xong vẫn phải soát rồi mới bấm xuất. Ở chế độ MOCK nút này báo rõ là chưa dùng được, không giả vờ làm.

## Bốn bản mẫu hiện có

**Công văn gửi cơ quan nhà nước** — rút từ công văn thật đã gửi Bộ KH&CN, giữ nguyên thể thức Nghị định 30/2020. Fact khoá: tên pháp nhân, người ký.

**Sales brief sau buổi gặp** — workbook tiếng Việt, tự tính điểm cơ hội. Vá vào đúng ô nên **giữ nguyên công thức** đã có trong file.

**Fact-sheet sản phẩm** — một trang thông số. Đáng chú ý: **mọi số liệu đều là fact khoá**, truy về 5 record. Người dùng chỉ nhập tên sản phẩm, mô tả một câu và ngày lập. Không có cách nào gõ sai một con số vào đây.

**Slide card** — một slide theo chuẩn trình bày RtR, số liệu dẫn chứng cũng khoá từ nguồn.

*Hạn chế đã biết:* hai bản mẫu mới mượn khung định dạng của công văn nên phần đầu trang còn bố cục hai cột hơi lệch với dạng fact-sheet. Đủ dùng nội bộ; nếu cần gửi khách thì phải dựng bản mẫu riêng do người thiết kế.

## Thêm bản mẫu mới

1. Đặt file mẫu vào `templates/`, chỗ cần điền viết dạng `{{ten_truong}}` (docx) hoặc ghi địa chỉ ô (xlsx).
2. Khai trong `templates/registry.yaml`: tên trường, loại, bắt buộc hay không. Fact khoá phải ghi `record:` và `extract:` — biểu thức để kiểm rằng record vẫn nói đúng điều mình tưởng.
3. Chạy `./tools/rebuild_all.sh` — bộ test sẽ kiểm luôn.

**Vì sao fact khoá cần `extract`:** nếu nội dung record đổi (curator sửa fact), biểu thức không khớp nữa thì cổng báo FAIL-LOUD thay vì lặng lẽ điền giá trị cũ. Đây là chỗ dễ trôi nhất, nên nó phải kêu.

## Còn thiếu

- Bản mẫu deck đầy đủ (hiện mới có slide card lẻ).
- Bố cục đầu trang của fact-sheet và slide card còn mượn khung công văn.
- Chưa có bản mẫu nào cho hợp đồng hay báo giá — đó là vùng cần fact khoá từ gói lãnh đạo, phải cân nhắc riêng.
