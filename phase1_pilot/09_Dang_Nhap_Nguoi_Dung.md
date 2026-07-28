# Đăng nhập theo người

## Vì sao bỏ mã chung

Mã chung cả nhóm hỏng ba việc cùng lúc:

- **Không đếm được người dùng thực** — ô bắt buộc trong sổ theo dõi 4 tuần, và là chỉ số quyết định gate Phase 2. Mười lăm người dùng chung một mã thì con số đó không tồn tại.
- **Không biết ai báo sai** để hỏi lại cho rõ.
- **Không phân quyền được** — ai có mã là vào được gói lãnh đạo, kể cả người không thuộc nhóm đó.

## Cách bật

```bash
cd phase1_pilot
cp users.example.yaml users.yaml     # rồi sửa danh sách
```

Mỗi người một dòng: mã, tên, phòng, và quyền `staff` hoặc `leader`. File `users.yaml` **không vào git** (đã có trong `.gitignore`).

Chưa tạo `users.yaml` thì server chạy y như cũ với passcode chung — không có bước nào bắt buộc phải làm ngay.

## Phân quyền

| Quyền | Gói nhân viên | Gói lãnh đạo |
|---|---|---|
| `staff` | vào được | **bị chặn** kể cả khi mã hợp lệ |
| `leader` | vào được | vào được |

Chặn ở tầng server, không phải ẩn nút trên giao diện. Người quyền `staff` gọi thẳng API của gói lãnh đạo cũng nhận 403.

## Điều mã đăng nhập KHÔNG làm được

Đây là **nhận diện**, không phải bảo mật mạnh. Mã đủ để biết ai đang hỏi và chặn người ngoài nhóm; không đủ để chống một người cố tình tấn công. Cụ thể:

- Không mã hoá, lưu dạng chữ thường trong `users.yaml`.
- Không hết hạn, không khoá sau nhiều lần sai.
- Ai biết mã người khác thì dùng được như người đó.

Vì vậy: **đừng dùng lại mã của bất kỳ hệ thống nào khác**, và giữ server trong mạng nội bộ. Nếu sau này Copilot mở rộng ra ngoài LAN thì phải thay bằng đăng nhập thật, không vá thêm vào đây.

## Ảnh hưởng tới sổ theo dõi

Nhật ký và ca báo sai giờ ghi kèm tên người. Báo cáo thứ Sáu đếm được người dùng thực. Đây là dữ liệu vận hành, **không phải công cụ theo dõi nhân viên** — dùng để biết ai cần hỏi thêm khi báo sai, không dùng để đánh giá ai chăm hỏi hay lười hỏi.
