> **RANH GIỚI HIỆN HÀNH (28/07/2026 · reversal).** Sau khi thử "nội bộ không gì mật"
> (gộp một gói), Lâm chốt **khôi phục ranh giới đúng một lớp**: giá **vốn** rời khỏi gói
> nhân viên, chỉ còn ở gói lãnh đạo. Cụ thể:
> - **Mọi nhân viên (gói staff):** giá **BÁN** MSRP + chiết khấu + định vị + văn phong. KHÔNG có giá vốn.
> - **Chỉ lãnh đạo (gói này):** thêm giá **VỐN** linh kiện + tên nhà cung cấp — toàn bộ `boms.yaml`
>   (25 fact: 16 linh kiện `BOM.*` + 9 giá vốn thành phẩm `SKU.*`).
> - **Ngoài MỌI gói:** biên lợi nhuận chưa kiểm chứng (doctrine A3), tình báo giá đối thủ,
>   deal đang đàm phán, thư viện insight.
>
> Một câu: **nhân viên thấy giá mình BÁN, chỉ lãnh đạo thấy giá mình MUA.**
> Ranh giới khoá bằng code hai chiều — cổng 4a (`leader_export`) + cổng 6c (`test_copilot`).
> Lịch sử ba mốc: 27/07 giá vốn cấm cả leader · 28/07 mở cho mọi người · 28/07-reversal chốt leader-only.
> Phần dưới là **mô tả ranh giới CŨ** (27/07), giữ lại để hiểu vì sao từng phân tuyến như vậy.

---

# Gói lãnh đạo · vận hành và ranh giới

Gói riêng cho 6-8 lãnh đạo. So với gói nhân viên (đã có giá bán + chiết khấu), gói này chứa **thêm giá vốn linh kiện + tên nhà cung cấp** — thứ nhạy cảm nhất về đàm phán mua hàng. Rào chắn: passcode riêng, danh sách người, cổng chống rò hai chiều, và kỷ luật vận hành.

## Ranh giới CŨ 27/07/2026 (LỊCH SỬ · xem khối đầu trang cho ranh giới hiện hành)

> Mô tả dưới đây là ranh giới **27/07 đã bị thay**. Ở bản 27/07, giá vốn nằm ngoài **cả** gói lãnh đạo;
> bản hiện hành (reversal 28/07) cho lãnh đạo thấy giá vốn. Đọc để hiểu lịch sử, đừng dùng làm hiện trạng.

**Có trong gói (27/07):** giá bán MSRP HERA/VEGA (US và VN), giá bundle, giá cho nhà phân phối, bốn bậc chiết khấu đối tác, tỷ giá tham chiếu, quy định deal registration, hai chỉ số định vị so đối thủ đã kiểm chứng, hai tài liệu văn phong, và toàn bộ gói nhân viên làm nền.

**Cố ý để ngoài (27/07):** giá vốn linh kiện và tên nhà cung cấp (25 fact BOM), biên lợi nhuận và chi phí sản xuất chưa kiểm chứng, tình báo giá đối thủ, điều khoản deal đang đàm phán, thư viện insight chiến lược theo khách hàng.

Nguyên tắc phân tuyến 27/07 (đã đổi): *lãnh đạo thấy giá mình BÁN, không thấy giá mình MUA.* Ở bản hiện hành, ranh giới đó dời xuống **nhân viên/lãnh đạo**: nhân viên thấy giá BÁN, lãnh đạo thấy thêm giá MUA.

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

1. Gói này có giá bán, chiết khấu VÀ giá vốn linh kiện + nhà cung cấp. Nhân viên thường không có giá vốn. Không chuyển tiếp câu trả lời ra ngoài nhóm.
2. Passcode không chia sẻ, kể cả cho trợ lý.
3. Bot vẫn có thể sai. Số nào dùng để chào thầu thì đối chiếu lại với người phụ trách giá trước khi gửi khách.
4. Câu trả lời có nhãn "chưa chốt" nghĩa là số đó chưa duyệt, không cam kết được.

## Điều gói này KHÔNG làm được, và đừng kỳ vọng

- Không biết deal đang đàm phán tới đâu. Hỏi người phụ trách.
- Có giá vốn nhưng **không tự tính biên lợi nhuận** cho bạn: số margin là chưa kiểm chứng (doctrine A3), cố ý để ngoài mọi gói. Giá vốn `SKU.*` có nhãn "chưa kiểm chứng · CFO duyệt". Muốn con số margin chính thức thì hỏi CFO.
- Không thay quy trình duyệt giá. Bot cho biết chính sách, người vẫn duyệt.
