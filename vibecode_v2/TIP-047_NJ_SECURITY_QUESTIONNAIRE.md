# TIP-047 · Hồ sơ State of New Jersey Third-Party Information Security Questionnaire

**Status:** PLANNED · chờ Homeowner xác nhận bối cảnh gói thầu và người đứng tên ISO
**Số TIP:** đổi từ 042 sang 047 ngày 16/09/2026 (TIP-042 đã dùng cho Product hardening 31/08)
**Date:** 16/09/2026
**Priority:** P1 (phụ thuộc hạn nộp thầu, Homeowner cung cấp)
**Nguồn:** `ATTACHMENT 4 - State of New Jersey Third Party Info Security Questionnaire 2024.pdf` (v1.5, 42 trang, NJCCIC ban hành; form PDF điền được: 220 trường gồm 111 ô văn bản, 49 checkbox, 30 dropdown Yes/No/N/A **đang mặc định "No"**)

## 1. Bản chất hồ sơ

Bộ câu hỏi thẩm định an ninh thông tin bên thứ ba của bang New Jersey, bám Statewide Information Security Manual, NIST CSF/SP 800-53, CIS Top 20, CSA CCM. Áp cho nhà cung cấp phát triển/vận hành/host hệ thống của bang **hoặc có quyền truy cập hệ thống, mạng, dữ liệu nhạy cảm của bang**. Người nộp cam đoan đúng sự thật. NJCCIC lập Risk Assessment Report; cơ quan chủ quản quyết định chấp nhận rủi ro; có thể yêu cầu bổ sung kiểm soát **trước khi trao hợp đồng**. Bản đã điền được bảo mật theo OPRA và Domestic Security Preparedness Act.

## 2. Cấu trúc và chỗ RtR phải cân nhắc

| Mục | Nội dung | Điểm nhạy với RtR |
|---|---|---|
| I | Mô tả dịch vụ; phân loại dữ liệu (PII, SSN, ePHI, tài chính, thuế, CJI/thực thi pháp luật, hạ tầng trọng yếu); liệt kê trường dữ liệu | Video/ảnh bay có thể là **CJI** (nếu người dùng là cảnh sát) và **hạ tầng trọng yếu**; PII ngẫu nhiên trong video |
| II | SaaS/cloud? nhà cung cấp; cloud chính phủ?; **dữ liệu nằm trong Mỹ?**; FedRAMP/StateRAMP; sàng lọc nhân sự; thiết bị; nhà thầu phụ | Mapview có bản cloud subscription → toàn bộ Mục II áp dụng; chọn **on-premises** thì nhiều câu thành N/A có lợi. **Nhân sự Việt Nam có truy cập dữ liệu bang không** là câu quyết định (câu 4, 7, 8, 9) |
| III | Hồ sơ tổ chức; người nộp; **Information Security Officer** | Phải có người đứng tên ISO |
| IV | 30 lĩnh vực kiểm soát, mỗi lĩnh vực 1 dropdown + câu tự luận; No/N/A phải giải trình | Kernel gần như không có fact về ISMS nội bộ; trả lời Yes không tài liệu là cam đoan sai |
| V | Đính kèm: chính sách an ninh, privacy policy, SOC2 Type II, FedRAMP/StateRAMP, chứng nhận độc lập, hồ sơ CSP/nhà thầu phụ | RtR có ISO 9001, FCC, IP54, NDAA (kernel); chưa có SOC2/ISO 27001/FedRAMP |

## 3. Kế hoạch

**Phase A · Homeowner cung cấp bối cảnh (critical path):** gói thầu nào, cơ quan chủ quản (NJ State Police? OHSP?), sản phẩm chào (HERA/VEGA + HeraHub + Mapview on-prem hay cloud), hạn nộp, ai đứng tên ISO, có nhân sự Việt Nam truy cập dữ liệu bang không, cloud nào nếu có.

**Phase B · Gap audit ISMS (Builder, 1 buổi):** rà 30 lĩnh vực theo ba mức: có tài liệu (Yes + đính kèm), có thực hành chưa văn bản hóa (viết chính sách ngắn rồi Yes), chưa có (No + kiểm soát bù + lộ trình). Kết quả là bảng 30 dòng có owner.

**Phase C · Bộ tài liệu tối thiểu (Builder + Homeowner duyệt):** Information Security Policy, Acceptable Use Policy, Privacy Policy, Incident Response Plan, Access Control/MFA standard, Vulnerability Management, BCP/DR (tận dụng drill RTO/RPO đã đo trong Copilot làm ví dụ thực hành), Third-Party Management. Mỗi tài liệu nạp vào SOT với provenance `approved_internal` sau khi CEO ký.

**Phase D · Điền form (Document OS):** dùng Copilot lấy fact có provenance, điền 220 trường; **kiểm 30 dropdown không còn "No" mặc định ngoài ý muốn**; đối chiếu từng "Yes" với tài liệu đính kèm Mục V; Homeowner rà cuối và ký cam đoan.

## 4. Nguyên tắc

- Không "Yes" khi không có tài liệu hoặc thực hành chứng minh được; "No" kèm kiểm soát bù và lộ trình tốt hơn "Yes" bị NJCCIC bác.
- Không đưa số kỹ thuật sản phẩm vào hồ sơ này ngoài phạm vi an ninh thông tin; số sản phẩm lấy từ kernel sau TIP-046.
- Dữ liệu cư trú và nhân sự truy cập là cam kết pháp lý, phải do CEO chốt.
