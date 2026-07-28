# Đề xuất tier — ma trận năng lực (ĐÃ ĐƯỢC THAY THẾ 28/07 chiều)

> **CẬP NHẬT 28/07 (chiều):** Lâm chốt **"ứng dụng nội bộ nên không có gì mật với nội bộ" → MỘT GÓI**.
> Toàn bộ bảng phân tier dưới đây KHÔNG còn áp dụng: mọi năng lực (gồm quốc phòng/gov/nội bộ) + giá bán
> + **giá vốn BOM** + voice giờ vào chung một gói cho mọi nhân viên. **SC-011 Blue UAS: Lâm xác nhận HERA
> ĐÃ chính thức cleared** → không còn landmine, L3F.RES.003 cập nhật thành cleared. Chỉ còn giữ ngoài gói:
> margin chưa-kiểm (doctrine A3) + deal/intel bên thứ ba. Truy vết bằng đăng nhập từng người. Giữ file này
> làm lịch sử quyết định.

---

## (Lịch sử) Đề xuất tier ban đầu — trước khi Lâm chốt một-gói

**Bối cảnh:** `kernel/registry/capabilities.yaml` (76 năng lực: 37 Hard · 22 Soft · 17 Org, nguồn chính `RtR_Ma_Tran_Nang_Luc.xlsx` — dán nhãn **P2 CONFIDENTIAL**). Máy (QA 28/07) đã **chọn tay** phần công khai an toàn nạp vào gói staff; phần nhạy/quốc phòng/nội bộ **chưa nạp**, chờ anh quyết tier. Ba tier đề xuất:
- **STAFF (L3)** — công khai (báo chí/giải thưởng/brochure), mọi nhân viên thấy.
- **LEADER (L2)** — nội bộ/thương mại/quốc phòng, chỉ nhóm lãnh đạo (cần dựng kênh năng lực leader-only — CHƯA có, chờ anh OK mới build).
- **KHÔNG NẠP** — tranh chấp/quá nhạy/aspirational chưa verify.

---

## ✅ ĐÃ NẠP staff (commit f10127f) — anh xác nhận wording
| Fact | Nguồn năng lực | Nội dung |
|---|---|---|
| `L3F.REC.001` | SC-001/002/003 | Phó Thủ tướng công nhận · Giải Vàng BKHCN 12/2025 · first VN export UAV sang Mỹ+G7 |
| `L3F.BRD.002` | SC-030/031/032 | Sứ mệnh "Drone Innovation to Advance Humanity" · "Invent. Build. Prove." · US-aligned+R&D VN |

## 🚨 KHÔNG NẠP — landmine, phải xử trước
| Năng lực | Vì sao |
|---|---|
| **SC-011 "on DCMA Blue UAS list (submission v8 FINAL)"** | **Chính là claim SAI đang escalation khẩn** — thực tế hồ sơ đang trong quy trình (L3F.RES.003). Bulk-nạp ma trận = bot khẳng định claim sai. Đã thêm test khoá landmine. |
| SC-050/051/052 (100% công nghệ lõi trước 12/2027 · 5 patent/năm · unicorn >$1B trước 2029) | Aspirational/cam kết tương lai, maturity 2-3, chưa verify — không nên bot khẳng định như sự thật. |

## 🔒 ĐỀ XUẤT LEADER-only (chờ anh duyệt + OK dựng kênh)
| Năng lực | Loại |
|---|---|
| SC-012 US Army 11th Airborne · SC-014 Israel defense customer Protrack | Khách quốc phòng cụ thể — nhạy quan hệ |
| SC-010 chính phủ chọn nhiệm vụ chiến lược (Internal CEO comm) · OC-051 Z115 govt VN | Quan hệ chính phủ nội bộ |
| SC-013 allied compliance trio · SC-020 94% tự chủ + NDAA BOM | Compliance/BOM-linked |
| OC-030 Vibecode Kit · OC-031 4-tier classification · OC-032 AI OS model | Phương pháp nội bộ |
| OC-040/041/042/050 kênh sales, MoU, partner ecosystem | Thương mại nội bộ |

## 🟢 CÓ THỂ NẠP staff thêm (công khai, nếu anh muốn lô 2)
SC-021 vertical integration · SC-022 production-validated · SC-023 zero-cloud/edge · SC-040/041/042 press/Xponential/Detroit · OC-003 UC Berkeley founders · OC-010 80+ kỹ sư trẻ · OC-011/012 in-house eng + AI/ML · OC-020/021 HQ (SHTP HCM + Castro Valley). *Nhiều cái đã có phần trong gói — nạp thêm sẽ trùng, cần lọc.*
> Lưu ý: Hard capabilities (37 HC) hầu hết là **spec sản phẩm đã có** trong gói — không cần nạp lại.

---

**Việc của anh:** (1) xác nhận 2 fact đã nạp; (2) redline cột LEADER (mục nào đồng ý → em dựng kênh leader-only + nạp; mục nào bỏ); (3) xử SC-011 trong khối escalation Blue UAS (khẩn). Máy KHÔNG tự nạp phần nhạy.
