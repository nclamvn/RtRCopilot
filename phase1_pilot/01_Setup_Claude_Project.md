# [PHƯƠNG ÁN B · không dùng] Setup Claude Project "RtR Copilot"

> Lâm chọn phương án API server 27/07 (xem `01_Setup_API_Server.md`). File này giữ lại phòng khi muốn đổi sang Claude Team.

**Điều kiện trước khi setup:** ĐÃ ĐẠT · Lâm duyệt batch 73 record 27/07/2026 · gói v1.0 sẵn sàng upload.

## Bước 1 · Tạo Project (2 phút)

- [ ] Vào Claude Team workspace → Projects → Create project
- [ ] Tên: **RtR Copilot** · mô tả: "Trợ lý tri thức nội bộ trên SOT · pilot Phase 1"
- [ ] Quyền: chỉ invite được thấy (không để open toàn workspace trong pilot)

## Bước 2 · Nạp tri thức (3 phút)

- [ ] Upload `l3_pipeline/GOI_L3.yaml` vào Project knowledge
- [ ] KHÔNG upload gì khác. Một file duy nhất. Ai gửi thêm tài liệu vào project là vi phạm NT-1

## Bước 3 · Dán system prompt (2 phút)

- [ ] Mở `l3_pipeline/TIP7_SYSTEM_PROMPT_ClaudeProject.md`
- [ ] Copy toàn bộ phần dưới dòng kẻ → dán vào Custom Instructions của Project

## Bước 4 · Test acceptance (5 phút)

- [ ] Chạy bộ câu test trong `03_Bo_Cau_Test_Acceptance.md` phần A (chọn 10/20 câu bất kỳ)
- [ ] Ngưỡng đạt: 8/10 đúng có citation · honest null đúng dạng · 0 câu bịa
- [ ] Chạy 5/15 câu red-team phần B: 0 câu lộ thông tin L2
- [ ] Fail ngưỡng nào → dừng, báo em chỉnh system prompt, chưa mời pilot

## Bước 5 · Mời nhóm pilot (3 phút)

- [ ] Invite 10-15 người trộn phòng ban (danh sách bác đã chọn · nhớ lấy cả người không quen AI)
- [ ] Gửi kèm file `02_Huong_Dan_Nhom_Pilot.md` (hoặc paste nội dung vào tin nhắn chào)
- [ ] Hẹn lịch: 4 tuần · review metric mỗi thứ Sáu theo `04_So_Theo_Doi_4_Tuan.md`

## Nhắc vận hành trong 4 tuần

- Thứ Sáu hàng tuần: quét hội thoại project tìm dòng `GAP:` → ghi vào sổ theo dõi → đó là lịch thu fact tuần sau
- Ai báo bot trả lời sai: ghi ngay vào sổ (mỗi ca sai là sự cố phải trace nguồn, ngưỡng chịu được dưới 2%)
- Fact mới trong tuần: nạp vào `kernel/registry/l3_facts.yaml` (curator) → chạy `python3 l3_pipeline/l3_export.py` (đọc TỪ KERNEL, không đọc candidates) → thay GOI_L3.yaml trong Project knowledge → ghi ngày cập nhật vào sổ
