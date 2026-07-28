# TIP-0 · Schema fact card ứng viên L3 + DISPUTED queue + danh mục L3 draft

**Chủ thầu ban hành 27/07/2026 · mọi Thợ TIP-1..4 tuân theo đúng schema này.**

## 1. Schema fact card ứng viên (YAML · file candidates)

```yaml
- id: CAND.<TIP số>.<seq 3 chữ số>          # ví dụ CAND.1.001
  content: >
    Phát biểu fact MỘT câu, tự đứng được, người ngoài đọc hiểu ngay.
  domain: product | process | company | legal | system | brand | event
  source_path: đường dẫn file gốc (bắt buộc · path đầy đủ)
  evidence_span: >
    Đoạn VERBATIM từ file nguồn chứa fact (kể cả lỗi chính tả gốc).
    File binary (xlsx/docx/pdf) thì ghi vị trí (sheet/section) + trích text đọc được.
  extraction: verbatim | normalized | inferred
  tier_proposed: L3 | L2 | L4
  owner_hint: người/vai trò chịu trách nhiệm fact này (đoán được thì ghi · không thì null)
  effective_date: YYYY-MM-DD hoặc null (không bịa ngày)
  kernel_check: new | duplicate | conflict | legacy | unsure
  kernel_ref: mã record kernel nếu duplicate/conflict (HC-xxx · SPEC-SYNC-02...) · else null
  note: tuỳ chọn
```

## 2. Luật cứng cho Thợ (vi phạm = card bị loại ở VERIFY)

1. **Kernel thắng.** Trước khi đánh `new`, đối chiếu `kernel/registry/capabilities.yaml` + `kernel/_dist/SPEC_CHANGELOG.md`. Trùng thì đánh `duplicate` + kernel_ref. Khác giá trị thì `conflict` + kernel_ref (KHÔNG tự chọn bên).
2. **Legacy 15 kg tự xử.** Claim Hera 15 kg / 33 lb / 1-4-15 → `kernel_check: legacy`, không đưa vào conflict (đã phân xử tại `kernel/_dist/LEGACY_HERA_15KG_MANIFEST.md`).
3. **Không bịa.** Không có evidence_span thì không có card. Ngày không rõ thì null.
4. **Chất lượng hơn số lượng.** Mỗi TIP nộp 20-40 card tốt nhất, ưu tiên fact nhân viên sẽ hỏi thật (spec, quy trình, chính sách, mốc công ty, hệ thống tool).
5. **Nhạy cảm đánh L2, nghi ngờ đánh L2.** Pricing, contact cá nhân ngoài công ty, deal cụ thể, intel đối thủ: `tier_proposed: L2` (không vào gói nhân viên). Mặc định nghi ngờ thì L2, hạ xuống L3 là việc của curator.
6. **Deck là derived artifact.** Không cào số kỹ thuật từ deck. Chỉ cào từ deck những gì deck là nguồn gốc (ví dụ: cấu trúc pitch đã dùng cho khách nào, ngày gửi).

## 3. DISPUTED queue format (Chủ thầu tổng hợp ở VERIFY · Thợ chỉ đánh conflict)

```yaml
- dispute_id: DISP.<seq>
  field: điều đang tranh chấp
  value_a: {value, source_path, effective_date}
  value_b: {value, source_path, effective_date}
  de_xuat: kernel thắng | nguồn mới hơn thắng | cần leader X xác nhận
  trang_thai: cho_Lam_duyet
```

## 4. Danh mục L3 draft (trình CEO · checkpoint C1)

**Được vào L3 (toàn nhân viên):**

- Spec sản phẩm hiện hành đã công bố nội bộ (payload, endurance, range, sensor line)
- Mốc lịch sử công ty và pháp lý công khai (FCC exemption, patent count, thành lập)
- Quy trình nội bộ (sales brief, bảo dưỡng, phát hành công văn, đặt tên file)
- Danh mục sản phẩm + mô tả một dòng
- Danh mục hệ thống phần mềm nội bộ (tên, mục đích, owner, link hướng dẫn)
- Chuẩn văn phong, template được dùng, brand assets ở đâu
- Org: phòng ban nào phụ trách domain nào (không kèm thông tin cá nhân)

**KHÔNG vào L3 (giữ L2/L1):**

- Mọi con số giá (giá bán, giá vốn, quote, pricing intel đối thủ)
- Deal cụ thể và pipeline khách (USAFA, EVN pursuit detail, deal reg)
- Contact cá nhân bên ngoài (khách, quan chức, channel partner)
- Insight library (tier P/S/H toàn bộ)
- Chiến lược thầu, wedge từng khách, adjustment basis
- Thông tin nhân sự cá nhân (lương, đánh giá, hồ sơ)
- Chi tiết BQP và mọi record liên quan quốc phòng cụ thể
```
