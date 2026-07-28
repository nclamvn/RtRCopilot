# Chạy RtR Copilot bằng API · độc lập, không cần tài khoản Team

**Phương án chính (Lâm chọn 27/07).** Bản Claude Team Project là phương án B, xem file `01_Setup_Claude_Project.md` nếu sau này muốn đổi.

## Cần chuẩn bị (một lần)

1. **API key:** vào console.anthropic.com → API Keys → tạo key. Nạp credit trả theo dùng (pilot 15 người ước vài chục USD/tháng, đo thật ở sổ theo dõi).
2. **Một máy chạy server:** Mac của bác hoặc máy nội bộ nào luôn bật, cùng mạng LAN/VPN với nhân viên.

## Chạy thử NGAY, không cần key (chế độ MOCK)

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/phase1_pilot
python3 copilot_server.py          # không có key = MOCK · mở http://127.0.0.1:8787
python3 test_copilot.py            # bộ test offline 26 test · không gọi API
```

MOCK = trả lời bằng máy tra cứu SOT (record khớp nhất + citation, dán nhãn MOCK rõ), đủ để duyệt toàn bộ UI/UX, tab Tra cứu SOT, evidence dock, GAP log. Muốn xem UI mà không chạy gì: mở `RtR_Copilot_UI_Preview.html` (thư mục trên) bằng double-click.

## Chạy thật (2 phút · khi có key)

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/phase1_pilot
export ANTHROPIC_API_KEY=sk-ant-...        # key của bác
export COPILOT_PASSCODE=matma-noi-bo       # tự đặt · nhân viên nhập một lần trong UI
python3 copilot_server.py
```

Thấy dòng `RtR Copilot · http://0.0.0.0:8787 · chế độ LIVE` là chạy. Nhân viên mở `http://<IP-máy-này>:8787` (xem IP: System Settings → Network, dạng 192.168.x.x). Không đặt passcode thì server tự khoá về 127.0.0.1 (chỉ máy này).

## Nó hoạt động thế nào

- Server đọc `GOI_L3.yaml` (gói 106 record từ kernel) + system prompt TIP-7, mỗi câu hỏi gọi Claude API với gói làm nguồn duy nhất. Đúng NT-1: bot là view của kernel.
- **Tab Tra cứu SOT:** tìm record trực tiếp không qua AI (nhanh, không tốn API) · bấm citation trong câu trả lời mở hồ sơ record.
- **GAP tự log:** câu nào bot không trả lời được tự ghi vào `gap_log.jsonl`. Thứ Sáu bác mở file này là có ngay danh sách gap, không phải quét hội thoại tay như phương án Team.
- **Audit tự có:** toàn bộ hỏi đáp ghi `qa_log.jsonl` kèm timestamp.
- Passcode chặn người ngoài mạng táy máy. Không đặt passcode thì chỉ nên chạy thử trên máy cá nhân.

## Test trước khi mời pilot (5 phút)

1. `python3 test_copilot.py` phải 0 fail (chạy được từ bây giờ, không cần key).
2. **Chạy Phần D trong `03_Bo_Cau_Test_Acceptance.md`: một câu hỏi thật để xác nhận API + model thông suốt** (test kỹ thuật không bắt được lỗi model id).
3. Chạy 10/20 câu phần A + 5/15 câu red-team ngay trên UI. Ngưỡng: 8/10 đúng có citation, 0 câu lộ L2. Đạt thì gửi link + `02_Huong_Dan_Nhom_Pilot.md` cho nhóm.

## Cập nhật tri thức hàng tuần

Nạp fact mới vào `kernel/registry/l3_facts.yaml` → chạy `python3 ../l3_pipeline/l3_export.py` → **restart server** (Ctrl+C rồi chạy lại). Gói mới tự nạp.

## Sự cố thường gặp

- "Server chưa có ANTHROPIC_API_KEY" → quên export key, chạy lại từ bước export.
- Nhân viên không vào được → kiểm tra cùng mạng, firewall Mac cho phép Python nhận kết nối.
- Trả lời chậm → bình thường 5-15 giây mỗi câu (model đọc cả gói mỗi lượt).
- Muốn đổi model: `export COPILOT_MODEL=claude-haiku-4-5-20251001` (rẻ và nhanh hơn, thử nếu chi phí thành vấn đề).
