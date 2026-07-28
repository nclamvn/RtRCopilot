# Gói lãnh đạo · vận hành và ranh giới

Gói riêng cho 6-8 lãnh đạo, chứa thêm **giá bán và chính sách chiết khấu** so với gói nhân viên. Đây là thay đổi lớn về an toàn: gói nhân viên trước nay an toàn tuyệt đối vì thông tin nhạy cảm **không nằm trong gói**; gói này thì có. Rào chắn còn lại là passcode, danh sách người, và kỷ luật vận hành.

## Ranh giới đã chốt (Lâm · 27/07/2026)

**Có trong gói:** giá bán MSRP HERA/VEGA (US và VN), giá bundle, giá cho nhà phân phối, bốn bậc chiết khấu đối tác, tỷ giá tham chiếu, quy định deal registration, hai chỉ số định vị so đối thủ đã kiểm chứng, hai tài liệu văn phong, và toàn bộ gói nhân viên làm nền.

**Cố ý để ngoài:** giá vốn linh kiện và tên nhà cung cấp (25 fact BOM), biên lợi nhuận và chi phí sản xuất chưa kiểm chứng, tình báo giá đối thủ, điều khoản deal đang đàm phán, thư viện insight chiến lược theo khách hàng.

Nguyên tắc phân tuyến: **lãnh đạo thấy giá mình BÁN, không thấy giá mình MUA.** Đủ để dự toán và duyệt giá, không lộ cấu trúc chi phí.

Danh sách đầy đủ kèm lý do từng mục: `kernel/registry/leader_allowlist.yaml`. Đây là file duy nhất quyết định gói chứa gì.

## Bốn ràng buộc khoá bằng code

| Mã | Ràng buộc | Nếu vi phạm |
|---|---|---|
| RB.1 | Gói lãnh đạo chỉ chạy được ở chế độ LIVE | Server từ chối khởi động |
| RB.2 | Bắt buộc có passcode | Server từ chối khởi động |
| RB.3 | Passcode phải khác gói nhân viên | Kỷ luật vận hành, không tự kiểm được |
| RB.4 | Mỗi câu trả lời từ nội dung hạn chế phải kèm nhãn | Cổng exporter chặn |

RB.1 là ràng buộc quan trọng nhất và dễ bị xem nhẹ nhất. Chế độ MOCK là máy tra cứu thuần: gặp từ khoá khớp là trả **nguyên văn** record, không có lớp phán đoán nào. Chạy gói lãnh đạo ở MOCK là nhả thẳng bảng giá ra màn hình cho bất kỳ ai gõ chữ "giá". Vì vậy nó bị chặn ở tầng khởi động chứ không phải nhắc trong tài liệu.

## Chạy

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/phase1_pilot
export ANTHROPIC_API_KEY=sk-ant-...
export COPILOT_PASSCODE=<mã riêng nhóm lãnh đạo>   # KHÁC mã nhân viên
export COPILOT_PACK=leader
export COPILOT_PORT=8788                            # cổng riêng, chạy song song gói nhân viên
python3 copilot_server.py
```

Gói nhân viên chạy như cũ (`COPILOT_PACK` bỏ trống hoặc `staff`), cổng 8787, passcode riêng.

## Cập nhật gói

```bash
cd ../l3_pipeline
python3 l3_export.py           # gói nhân viên trước
python3 leader_export.py       # gói lãnh đạo (đọc gói nhân viên làm nền + allowlist)
python3 leader_export.py --selftest   # xác nhận cổng chống rò còn cắn
cd ../phase1_pilot && python3 test_copilot.py   # phải 0 fail
```

Thêm fact giá mới vào kernel **không** tự động đưa nó vào gói lãnh đạo. Phải ghi id vào `leader_allowlist.yaml`. Quên ghi thì fact không ra ngoài — đó là hướng sai an toàn, cố ý thiết kế vậy.

## Điều phải nói với 6-8 người khi trao quyền

1. Gói này có giá bán và chiết khấu. Không chuyển tiếp câu trả lời ra ngoài nhóm.
2. Passcode không chia sẻ, kể cả cho trợ lý.
3. Bot vẫn có thể sai. Số nào dùng để chào thầu thì đối chiếu lại với người phụ trách giá trước khi gửi khách.
4. Câu trả lời có nhãn "chưa chốt" nghĩa là số đó chưa duyệt, không cam kết được.

## Điều gói này KHÔNG làm được, và đừng kỳ vọng

- Không biết deal đang đàm phán tới đâu. Hỏi người phụ trách.
- Không biết giá vốn nên **không tính được biên lợi nhuận**. Muốn biết còn bao nhiêu dư địa giảm giá thì hỏi CFO.
- Không thay quy trình duyệt giá. Bot cho biết chính sách, người vẫn duyệt.
