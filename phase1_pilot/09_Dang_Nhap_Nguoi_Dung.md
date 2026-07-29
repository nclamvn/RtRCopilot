# Đăng nhập và phân quyền

> **Bản hiện hành 29/07/2026.** Nhân viên tự đăng ký bằng email công ty, kích hoạt qua thư,
> và vào với vai thấp nhất. Quản trị viên chủ động nâng vai. Thay hoàn toàn cách cũ
> (Lâm gõ tay từng mã trong `users.yaml`) — cách cũ vẫn chạy được như đường lùi.

## Hai đường vào · chọn theo hiện trạng hộp thư công ty

**Đường A · tự đăng ký.** Dùng khi mọi nhân viên đã có hộp thư `@rtrobotics.me` chạy thật.
Email là thứ chứng minh danh tính.

**Đường B · quản trị viên mời tay.** Dùng khi công ty **chưa triển khai Workspace chuẩn** —
tức là hiện trạng tháng 07/2026. Quản trị viên gõ tên và email liên lạc của người đó, hệ
sinh một link dùng-một-lần sống 72 giờ, trao qua Zalo hoặc đưa tận tay. Người nhận mở link,
đặt mật khẩu, vào luôn.

> Đánh đổi của đường B phải nói thẳng: **email không còn chứng minh gì cả.** Thứ chứng minh
> danh tính là việc quản trị viên tự tay gõ tên người đó vào. Nên đường B chỉ quản trị viên
> dùng được, và mỗi lời mời đều ghi vào nhật ký kèm tên người mời.

Hai đường chạy song song, không loại trừ nhau. Workspace lên thì bật đường A, đường B vẫn
giữ làm dự phòng cho người có hộp thư hỏng hoặc thư rơi vào spam.

**Về Google Workspace:** SMTP chỉ cần *một* hộp thư biết gửi thư — bất kỳ tài khoản nào có
app password. Nó **không** đòi Workspace chuẩn của công ty. Cái Workspace quyết định là
chuyện khác: nhân viên có hộp thư `@rtrobotics.me` để **nhận** thư kích hoạt hay không.
Chưa có thì đường A không có nền để đứng, dù SMTP cấu hình hoàn hảo.

## Luồng của một người mới (đường A)

1. Mở địa chỉ Copilot trong mạng công ty, bấm tab **Đăng ký**.
2. Nhập họ tên, email công ty (`@rtrobotics.com` hoặc `@rtrobotics.me`), mật khẩu tối thiểu 10 ký tự.
3. Một thư kích hoạt gửi về chính hộp thư đó. Link sống 24 giờ.
4. Bấm link → tài khoản hoạt động, **vai nhân viên**.
5. Cần quyền cao hơn thì nhắn quản trị viên. Không có đường tự nâng.

Email quyết định tất cả vì đó là thứ duy nhất chứng minh được mà không cần ai gõ tay:
người này nhận được thư ở hộp thư công ty. Bằng chứng đó đủ cho vai thấp nhất, và
**không đủ cho gì hơn** — nên mọi vai cao hơn đều phải do quản trị viên bấm tay.

Hộp thư dùng chung (`info@`, `sales@`, `support@`…) bị chặn đăng ký: nhiều người cùng đọc
được một hộp thư như thế, nên "nhận được thư kích hoạt" không còn chứng minh được ai là ai.

## Ba vai

| | Nhân viên | Lãnh đạo | Quản trị |
|---|:---:|:---:|:---:|
| Hỏi đáp, tra cứu SOT, xem khoảng trống | ✓ | ✓ | ✓ |
| Sinh fact-sheet, slide card, sales brief | ✓ | ✓ | ✓ |
| Báo bot trả lời sai, đề xuất fact mới | ✓ | ✓ | ✓ |
| Xem nhật ký của chính mình | ✓ | ✓ | ✓ |
| **Đọc nội dung hạn chế** (giá vốn, nhà cung cấp) | | ✓ | ✓ |
| **Sinh công văn** mang tư cách pháp nhân | | ✓ | ✓ |
| **Duyệt ca báo sai** | | ✓ | ✓ |
| Xem nhật ký toàn công ty (không kèm tên) | | ✓ | ✓ |
| **Xem câu hỏi kèm tên người hỏi** | | | ✓ |
| **Phân vai, khoá tài khoản** | | | ✓ |
| **Ghi vào kernel** | | | ✓ |

Bảng này nằm ở một chỗ duy nhất trong code: `auth.QUYEN`. Mọi endpoint hỏi bảng đó chứ
không tự viết điều kiện riêng. Điều kiện rải rác là cách chắc chắn nhất để một chỗ quên
cập nhật khi luật đổi. Hành động chưa khai trong bảng thì **cấm** — sai theo hướng đóng.

### Ba chỗ thiết kế ngược trực giác, và lý do

**Lãnh đạo duyệt nhưng không ghi.** Duyệt ca báo sai chỉ đổi trạng thái thành "xác nhận
sai"; việc sửa kernel vẫn đi qua một cửa duy nhất là quản trị viên. Nhiều người ghi vào
nguồn sự thật là mất nguồn sự thật (NT-5).

**Lãnh đạo không xem được tên người hỏi.** Người ta chỉ dám hỏi câu ngây thơ khi biết sếp
không đọc được tên mình bên cạnh câu hỏi. Mà chính câu ngây thơ mới lộ ra chỗ tài liệu
công ty đang thủng — thứ có giá trị nhất mà hệ này thu được. Điều này **phải nói rõ trong
thư mời**, vì tác dụng chỉ có khi người ta biết mình được bảo vệ. Thư kích hoạt tự động
đã có câu đó.

**Chỉ công văn bị khoá, không phải mọi tài liệu.** Fact-sheet và slide card cũng in tên công
ty nhưng vô hại. Công văn có **chữ ký CEO** — một file như thế gửi ra cơ quan nhà nước là
ràng buộc công ty. Server nhận ra bản mẫu pháp nhân bằng chính dấu hiệu đó (trường khoá
`nguoi_ky`), suy ra từ registry chứ không chép tay danh sách id: thêm bản mẫu "tờ trình"
hay "báo cáo gửi Bộ" thì nó tự vào diện khoá, không cần ai nhớ sửa.

## Cấu hình khi dựng

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/phase1_pilot

# 1 · Quản trị viên gốc · người này đăng ký xong là thành quản trị luôn.
#     BẮT BUỘC. Không khai thì đăng ký xong KHÔNG có ai phân quyền được cho ai.
export COPILOT_ADMIN_EMAIL=lam.nguyen@rtrobotics.me

# 2 · Địa chỉ người dùng gõ vào · để link mời/kích hoạt trỏ đúng máy.
export COPILOT_URL=http://192.168.1.50:8787

# 3 · SMTP · CHỈ cần cho đường A (tự đăng ký). Đường mời tay chạy không cần dòng nào
#     dưới đây: link hiện thẳng trên màn quản trị để chép và trao tay.
export COPILOT_SMTP_HOST=smtp.gmail.com
export COPILOT_SMTP_PORT=465
export COPILOT_SMTP_USER=<hộp thư nào biết gửi · không nhất thiết Workspace công ty>
export COPILOT_SMTP_PASS=<app password, không phải mật khẩu đăng nhập>

export ANTHROPIC_API_KEY=sk-ant-...
python3 copilot_server.py
```

Biến tuỳ chọn: `COPILOT_EMAIL_DOMAINS` (mặc định `rtrobotics.com,rtrobotics.me`),
`COPILOT_TOKEN_GIO` (phiên sống bao lâu, mặc định 12), `COPILOT_KICHHOAT_GIO` (mặc định 24),
`COPILOT_SECRET` (khoá ký phiên — không khai thì tự sinh vào `.session_secret`).

Chạy thử không có SMTP: `export COPILOT_MAIL_DEV=1` in link kích hoạt ra màn hình thay vì
gửi thư. **Chỉ dùng để thử trên máy mình.** Bật trên máy chung là ai đọc được màn hình
cũng kích hoạt được tài khoản của người khác.

## Việc thường xuyên của quản trị viên

Màn **Người dùng** trong ứng dụng, chỉ vai quản trị thấy.

- **Mời người mới** bằng nút *Mời người mới*: gõ tên, email liên lạc, chọn vai → hệ trả về
  link, bấm *Chép link* rồi gửi qua Zalo. Nếu SMTP đã cấu hình thì thư cũng tự gửi, nhưng
  link vẫn hiện ra để chép — hộp thư chưa chuẩn thì thư hay rơi vào spam.
- **Nâng vai** khi có người cần đọc giá vốn hoặc soạn công văn.
- **Khoá tài khoản người đã nghỉ.** Email công ty còn dùng được **không có nghĩa** người đó
  còn làm ở công ty. Không có cách nào để hệ tự biết — danh sách này phải rà bằng mắt.
  Cột "Hoạt động" cho biết lần cuối mỗi người vào; dùng cột đó để soi ai đã im lâu.
- **Nhìn số "chờ kích hoạt".** Con số cao dai dẳng nghĩa là thư không tới được (spam, SMTP
  sai), không phải người ta lười.

Nâng vai hoặc khoá tài khoản làm **chết ngay** phiên đang mở của người đó — họ phải đăng
nhập lại. Không có cơ chế này thì hạ vai một người mà người đó vẫn giữ quyền cũ tới hết 12
giờ, đúng kiểu chế độ suy biến âm thầm.

Hệ không cho hạ vai hoặc khoá **quản trị viên duy nhất còn hoạt động** — đó là tự khoá mình
ra ngoài vĩnh viễn. Nên cấp quyền quản trị cho người thứ hai sớm.

## Năm điều hệ này KHÔNG làm được

Ghi ra để không ai tưởng nhầm là đã an toàn.

1. **Email công ty còn hiệu lực ≠ còn là nhân viên.** Người nghỉ việc mà IT chưa khoá hộp
   thư vẫn đăng ký được. Chống bằng việc admin rà danh sách, không bằng code.
2. **Không có xác thực hai lớp.** Ai lấy được mật khẩu là vào được.
3. **Trên macOS, mật khẩu băm bằng pbkdf2 chứ không phải scrypt.** Python bản hệ thống của
   macOS dựng trên LibreSSL, mà LibreSSL không có scrypt. Hệ tự nhận ra và chuyển sang
   `pbkdf2-sha256` 600.000 vòng — vẫn là KDF đúng nghĩa, nhưng yếu hơn scrypt trước dàn GPU.
   Muốn có scrypt thì cài Python từ python.org hoặc Homebrew (dựng trên OpenSSL), hệ tự dùng.
   Chạy `python3 auth.py` để xem máy đang dùng cách nào.
   **Kèm theo:** `accounts.json` tạo trên máy có scrypt thì máy không có scrypt **không kiểm
   được** — đăng nhập báo đúng lý do đó chứ không nói "sai mật khẩu", và cách xử lý là quản
   trị viên đặt lại mật khẩu, không phải bắt người dùng gõ lại.
4. **`accounts.json` là tài sản nhạy cảm** — email nhân viên và hash mật khẩu.
   `.session_secret` còn nặng hơn: ai có nó ký được token giả mạo bất kỳ ai. Cả hai để
   quyền 0600, nằm trong `.gitignore`, không sao ra máy khác.
5. **Giới hạn tần suất mất khi khởi động lại** (đếm trong bộ nhớ). Nó chặn script dò hàng
   nghìn lần, không chặn được kẻ tấn công kiên nhẫn.

Vì năm điều trên, **server phải nằm trong mạng nội bộ**. Muốn mở ra ngoài LAN thì thay bằng
đăng nhập thật (SSO Google Workspace, xác thực hai lớp), không vá thêm vào cái này.

## Chế độ mã chung · đường lùi

Chưa có tài khoản nào thì server chạy như cũ với `COPILOT_PASSCODE`. Ở chế độ đó server
**không biết người gọi là ai**, nên cấp vai thấp nhất: hỏi đáp và tra cứu chạy bình thường,
nhưng **không ai tạo được công văn** và màn Người dùng không hiện. Suy biến theo hướng đóng
là cố ý — thà mất một tính năng còn hơn phát quyền cho người không nhận diện được.

Hễ có **một** tài khoản hoạt động là server chuyển hẳn sang đường tài khoản và bỏ qua
passcode. Không có chế độ lai.

## Đường lùi cũ: users.yaml

Vẫn đọc được nếu có, và vẫn dịch vai `staff`/`leader` sang `nhanvien`/`lanhdao`. Nhưng nó
đứng **sau** tài khoản: có `accounts.json` là `users.yaml` bị bỏ qua. Nên chuyển hẳn sang
tài khoản rồi xoá `users.yaml`, để khỏi có hai nguồn sự thật về việc ai là ai.

## Vì sao bỏ mã chung (giữ lại lý do gốc)

Mã chung cả nhóm hỏng ba việc cùng lúc: không đếm được người dùng thực (ô bắt buộc trong sổ
theo dõi 4 tuần, và là chỉ số quyết định gate Phase 2); không biết ai báo sai để hỏi lại cho
rõ; không phân quyền được — ai có mã là vào được gói lãnh đạo, kể cả người không thuộc nhóm.
