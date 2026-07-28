# Sổ theo dõi pilot · 4 tuần · điền mỗi thứ Sáu

**Ngưỡng gate ra Phase 2 (từ PRD):** usage giữ được sau tuần 3 · tối thiểu 3 use case lặp hàng tuần · giới hạn của server pilot thực sự cản trở. Thiếu một trong ba: DỪNG ở server pilot, tiết kiệm được là thành công.

**Điền sổ này thế nào:** chạy `python3 weekly_review.py --tuan N` mỗi thứ Sáu · máy tự đếm số câu hỏi, tỷ lệ trả lời được, GAP gom nhóm, chủ đề hỏi nhiều nhất · bác chỉ điền ba ô máy không biết (người dùng unique, ca báo sai, fact nạp thêm) rồi dán vào đây.

## Tuần 1 · ngày __ / __

| Metric | Số | Ghi chú |
|---|---|---|
| Số câu hỏi trong tuần | | |
| Số người dùng thực (unique) | | |
| Tỷ lệ trả lời được từ gói (ước) | ___ % | mục tiêu tuần 1: 60% |
| Số ca báo SAI | | mỗi ca ghi mã record + trace nguồn |
| Số GAP mới quét được | | weekly_review.py tự gom · liệt kê dưới |
| Fact nạp bổ sung trong tuần | | |

GAP list tuần 1 (câu hỏi chưa trả lời được · xếp theo tần suất):
1.
2.
3.

Việc curator tuần sau: đi gặp ai, hỏi gì:
-

## Tuần 2 · ngày __ / __

(bảng như tuần 1 · mục tiêu tỷ lệ trả lời 70%)

## Tuần 3 · ngày __ / __

(bảng như tuần 1 · mục tiêu 75% · CHÚ Ý: usage tuần này so tuần 1 là chỉ báo "đồ chơi mới" hay nhu cầu thật)

## Tuần 4 · ngày __ / __

(bảng như tuần 1 · mục tiêu 80%)

## Tổng kết cuối kỳ · quyết định gate

- [ ] Usage tuần 4 ≥ tuần 1? (nhu cầu thật)
- [ ] Có ≥ 3 use case lặp hàng tuần? Liệt kê: ______
- [ ] Tỷ lệ báo sai < 2%?
- [ ] Thời gian curator mỗi fact < 5 phút?
- [ ] Giới hạn nào của server pilot THẬT SỰ cản trở? (không suy đoán · ghi ca cụ thể): ______

**Quyết định:** ☐ Dừng ở server pilot (thành công · tiết kiệm) ☐ Build Phase 2 portal (có data biện minh) ☐ Kéo dài pilot thêm __ tuần

Khảo sát 5 câu gửi nhóm pilot cuối tuần 4:
1. Tuần qua anh chị dùng Copilot mấy lần?
2. Câu nó trả lời có tin được không, vì sao?
3. Có lần nào nó sai mà anh chị không buồn báo không?
4. Thiếu tính năng gì khiến anh chị quay về hỏi người?
5. Nên mở cho toàn công ty chưa?
