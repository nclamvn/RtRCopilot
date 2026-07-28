# Vận hành liên tục · để server tự chạy và tự báo cáo

Ba việc làm một lần, sau đó pilot chạy không cần ai canh.

## 1 · Khởi động một lệnh

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/phase1_pilot
./start_copilot.sh
```

Script tự kiểm tra Python, gói tri thức, chạy bộ test offline, rồi mới khởi động. **Test fail thì không khởi động** (không phục vụ nhân viên bằng gói lỗi). Nó cũng in sẵn địa chỉ LAN để gửi nhóm.

Để không phải gõ key mỗi lần, tạo file `.env` cạnh script:

```
ANTHROPIC_API_KEY=sk-ant-...
COPILOT_PASSCODE=matma-noi-bo
```

File `.env` không nằm trong zip và không nên commit đi đâu.

## 2 · Tự chạy lại khi Mac khởi động lại (tuỳ chọn)

Chép `com.rtr.copilot.plist` vào `~/Library/LaunchAgents/`, sửa đường dẫn nếu thư mục khác, rồi:

```bash
launchctl load ~/Library/LaunchAgents/com.rtr.copilot.plist    # bật
launchctl unload ~/Library/LaunchAgents/com.rtr.copilot.plist  # tắt
```

Log chạy nền ghi vào `phase1_pilot/server_out.log` và `server_err.log`. Không bắt buộc — bỏ qua nếu bác tự bật server mỗi sáng.

## 3 · Báo cáo thứ Sáu · máy đếm thay

```bash
python3 weekly_review.py --tuan 1
```

Đọc `qa_log.jsonl` + `gap_log.jsonl` (server tự ghi), in ra báo cáo markdown và lưu vào `bao_cao_tuan/`. Nó tự tính: số câu hỏi, tỷ lệ trả lời được từ gói, GAP gom theo nhóm lặp, chủ đề được hỏi nhiều nhất.

Ba ô nó **cố tình để trống** vì máy không biết: số người dùng thực, số ca báo sai, số fact nạp thêm. Bác điền tay — đó đúng là phần cần mắt người.

**Khi thấy nó gom nhóm chưa đúng:** hai câu cùng chủ đề mà bị tách, thường vì dùng hai từ đồng nghĩa chưa có trong từ điển. Mở `weekly_review.py`, thêm cặp vào `CANON` (ví dụ `"tam bay": "tambay"`), rồi chạy `python3 test_copilot.py` — bộ test có 8 ca khoá cả hai chiều (phải gom / cấm gom) nên thêm sai sẽ đỏ ngay. Thêm dè: từ điển rộng quá thì gom nhầm hai chủ đề khác nhau, hại hơn tách nhầm.

Dán báo cáo vào `04_So_Theo_Doi_4_Tuan.md` là xong việc thứ Sáu.

## Vòng cập nhật tri thức trong tuần

```bash
# 1 · curator sửa kernel (l3_facts.yaml · leader_allowlist.yaml · prices.yaml…)
# 2 · một lệnh tái sinh TẤT CẢ artefact dẫn xuất + tự kiểm
./tools/rebuild_all.sh
# 3 · restart server
```

`rebuild_all.sh` chạy đúng thứ tự: gói nhân viên → gói lãnh đạo → cổng chống rò tự kiểm → đóng zip → bộ test. Test fail thì báo đỏ và không coi là xong.

**Vì sao có lệnh này:** ba lần liên tiếp sửa kernel xong quên tái sinh một artefact dẫn xuất (gói lãnh đạo, gói nằm trong zip), khiến bản đang phục vụ mang thông tin cũ. Nhớ thủ công không chặn được, nên gộp thành một lệnh và khoá bằng cổng: bộ test tự tái sinh gói vào thư mục tạm rồi so với bản trên đĩa — lệch một byte là đỏ.

Fact giá mới KHÔNG tự vào gói lãnh đạo · phải khai id trong `kernel/registry/leader_allowlist.yaml`. Xem `07_Goi_Lanh_Dao.md`.

Không tắt bước nào. Bước test là cái chặn gói lỗi ra tới người dùng; bước selftest là cái chặn gói lãnh đạo rò giá vốn.

## Khi nào dừng lại và nghĩ

- **Tỷ lệ trả lời tụt** giữa hai tuần liên tiếp: gói đang lệch nhu cầu thật, xem GAP thay vì thêm tính năng.
- **Số câu hỏi tuần 3 thấp hơn tuần 1**: hiệu ứng đồ chơi mới đã hết, nhu cầu thật chưa đủ. Đây là dữ liệu quý, không phải thất bại.
- **Một ca trả lời sai không trace được về record**: dừng phục vụ, tìm nguồn trước khi chạy tiếp. Nguyên tắc NT-1 (bot là view của kernel) bị vi phạm thì mọi câu khác cũng đáng ngờ.
