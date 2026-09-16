# TIP-046 · Master Specification Sync: RTR Master Specification → kernel → Copilot

**Status:** PHASE 1 BUILT (cloud) · chờ Homeowner áp registry + commit · Phase 2 chờ onboarding revision 7
**Số TIP:** đổi từ 041 sang 046 ngày 16/09/2026 vì TIP-041 đã được dùng cho US Proclamation 11055 (28/08), TIP-042 đến 045 đã tồn tại (31/08 đến 03/09)
**Date:** 16/09/2026
**Priority:** P0 (số liệu sản phẩm là xương sống của mọi câu trả lời, báo giá, hồ sơ thầu)
**Nguồn mới:** `/Users/os/RtR/RTR Master Specification/` gồm 9 workbook MASTER: HERA 2.0 v1.0.1 (duyệt 16/07/2026, Quoc Luong), VEGA v1.0, HeraSight NDAA v1.0, HeraSight Standard v1.0, HeraSight61 NDAA v1.0, HeraSight61 Standard v1.0, Loudspeaker LS1 v1.0, Spotlight S1 v1.0, Tether System v1.0
**Nguồn cũ:** `KnowledgeBase/DCMA submission compliance questions/Supporting Document/SPECIFICATION/HERA SPECIFICATION.xlsx` (02/2026, sha b304070906b2) và `VEGA SPECIFICATION.xlsx` (bản sao byte-identical của file HERA, không phải spec VEGA thật)
**Kernel hiện hành:** registry `8847e72` (24/08/2026) cộng đợt curation 28/08 chưa commit (L3F.REG.010 đến 015, hash `vanban_hoaky/*`, `phase_a/bites_kernel.py`); chưa có master nào trong `source_canonical`

## 0. Ba phân xử Homeowner 16/09/2026 (ghi sổ)

| # | Xung đột | Quyết định | Áp vào record |
|---|---|---|---|
| 1 | Tầm điều khiển HERA: master 10 km @3 dBi; kernel/bảng chuẩn 24/08 = 15 km | **15 km có điều kiện ăng-ten**: 10 km là cấu hình chuẩn (ăng-ten 3 dBi), 15 km với ăng-ten 8 dBi / cấu hình RF nâng cao. **Cần Quoc Luong xác nhận HERA đạt 15 km** trước khi nâng lên verified_primary | L3R.K.007, capabilities (dòng 13), L3F.REG.009: tách hai số có điều kiện; bỏ câu "10 km là số của VEGA" (VEGA master cũng 10 km / 15 km @8 dBi) |
| 2 | Tải trọng: master 30 lb (13,6 kg); kernel 14 kg | **14 kg là số chính thức tiếng Việt (làm tròn của 30 lb)**; record ghi cả ba dạng 30 lb ≈ 13,6 kg ≈ 14 kg | SPEC.HERA.PAYLOAD.MAX giữ 14, thêm `value_lb: 30`, note làm tròn; nguồn chuyển sang master |
| 3 | Edge AI: master Xavier NX; kernel Orin NX 105 TOPS | **Xavier NX là chuẩn (21 TOPS), Orin NX 100 TOPS là tùy chọn nâng cấp** | SPEC.HERA.EDGE_AI.TOPS → 21 chuẩn + 100 tùy chọn; capabilities "Edge AI on-drone 105 TOPS" → tùy chọn; L3F 105 TOPS "≥5× compute" positioning sửa thành có điều kiện; L3F.REG.009 sửa dòng 105 TOPS |

## 1. Phase 1 · Registry (Homeowner áp, dry-run + backup theo registry-hygiene)

| # | Việc | Chi tiết |
|---|---|---|
| R1 | source_canonical | Copy 9 master vào `kernel/source_canonical/master_spec/`; `source_hashes.yaml` thêm 9 dòng (sha256 16 ký tự: HERA 7b3b2441685f, VEGA fe32b066a830, HeraSight NDAA f332223f962c, HeraSight Std 73013420603e, HS61 NDAA f103611d37ce, HS61 Std cbc7a63b90f8, LS1 e3932b117d11, S1 f5d742c01898, Tether 518e5471f4a3) |
| R2 | SPEC.HERA.* viết lại từ master | MTOW 29,6 kg (65,2 lb) thay 31; empty 16 kg giữ; payload theo phân xử 2; FLIGHT: 56 / 40 @6 lb (2,7 kg) / giữ 16 @14 kg từ nguồn cũ với note; PAYLOAD.BAYS: CONFLICT → **4 cổng 120 W** (giải cờ flagged); thêm: deployment <1 phút, IP54, -25..45 °C, radar mmWave 4 hướng, Remote ID, băng ISM, multi-link RF/Cellular/Starlink/Tether, pin 43,2 V 35 Ah, sạc 2 cổng 3000 W@220 V, tầm bay 35 km, tốc độ 20/5/4 m/s, trần 5000 m, gió 13 m/s; EDGE_AI theo phân xử 3; RANGE theo phân xử 1. Provenance `verified_primary` (master đã duyệt), số cũ chuyển lịch sử có note |
| R3 | SPEC.HERAHUB.* | HeraHub 2.0: 10,1" 1280×800 1800 nits, QCS8550 16 GB, 6 luồng 1080p, 512 GB (1 TB), Android 13, 2,8 kg, -25..45 °C (khớp RENAME-01 và L3R.1.009) |
| R4 | SPEC.VEGA.* (lấp gap Pha 3) | payload 20 kg (44 lb), MTOW 38 kg, empty 18 kg, 60 phút, S-band 1,98–2,7 GHz, AES-256 + mesh, nhảy tần, multi-link + fiber optic, tầm 10 km / 15 km @8 dBi, pin 50,4 V, -30..45 °C, VIO; VegaHub 2.0 2000 nits, ATAK/WinTAK. L3R.1.010 (brochure 04/2026: 37,4 / 17,4 kg) thành lịch sử |
| R5 | Phụ kiện | HeraSight NDAA vs Standard (khác LRF 3000 m/0,5 m so với 6000 m/1 m; IR 30/60 Hz 4 tiêu cự so với 30 Hz 9,1 mm; 850 g; Xavier 21 TOPS, Orin 100 TOPS tùy chọn); HeraSight61 NDAA/Standard (Sony ILX-LR1 61 MP, 965 g); LS1 (Whelen WSSC, 106 dB @3 m, 400 m, 1,72 kg, 30 W); S1 (50 lux @50 m, 15°, 6500 K, 0,98 kg, 80 W, IEC 62471 RG1); Tether (24 kg, 3500 W, 50/100 m, 1 Gbps, kéo 200 kg, pin dự phòng 43,2 V 15 Ah ~7 phút với 6 kg tải) |
| R6 | Fact và capability liên đới | L3F.REG.009 giữ nguyên văn (extraction verbatim), thêm ngoặc cập nhật ở đầu và trỏ sang bảng chuẩn mới L3F.REG.016; capabilities.yaml dòng 13 và mục "Edge AI 105 TOPS"; L3F.1.2022 positioning "≥5×"; L3R.K.007 tầm điều khiển; L3R.1.005 "30 lbs (14 kg)" giữ, thêm cross-ref |
| R7 | Kiểm tra hậu kiểm | Rà báo cáo Tây Ninh 29/08 (nếu đã gửi Sở): số 15 km có kèm điều kiện ăng-ten không; nếu không, ghi nhận sai lệch vào ledger, không sửa im lặng |

## 2. Phase 2 · Ứng dụng

1. `run_migration.py --revision 7` (revision 6 đã active từ TIP-041 US Proclamation 28/08; kiểm SQL trước khi chọn số) → onboard dry-run → activate → reindex (chu trình đã chứng minh ở TIP-040).
2. Kiểm 5 câu trên UI: tải trọng HERA; tầm điều khiển HERA (phải nêu hai số có điều kiện); Edge AI HERA (phải nêu chuẩn/tùy chọn); VEGA bay được bao lâu; Tether cấp điện bao nhiêu W.

## 3. Phase 3 · Acceptance chống chép số cũ (oracle cam kết trước)

| Case | Câu hỏi | Kỳ vọng |
|---|---|---|
| MS-001 | Tải trọng tối đa HERA? | 14 kg, có 30 lb; fail nếu 15 kg |
| MS-002 | HERA điều khiển xa bao nhiêu? | 10 km chuẩn + 15 km với ăng-ten 8 dBi; fail nếu chỉ "15 km" trần |
| MS-003 | HERA có bao nhiêu TOPS? | Xavier NX 21 TOPS chuẩn, Orin 100 TOPS tùy chọn; fail nếu "105 TOPS" trần |
| MS-004 | HERA có mấy cổng payload? | 4 cổng, 120 W |
| MS-005 | VEGA mang được bao nhiêu kg? | 20 kg (44 lb), MTOW 38 kg |
| MS-006 | HeraSight NDAA khác Standard chỗ nào? | LRF và IR khác nhau như R5 |
| MS-007 | Tether cấp điện bao lâu khi mất điện lưới? | ~7 phút với 6 kg tải, pin 15 Ah |
| MS-008 | HERA chống nước chuẩn gì? | IP54; fail nếu IP43 |

## 4. Nguyên tắc

- Master đã duyệt là nguồn sơ cấp; số cũ 02/2026 không xóa, chuyển lịch sử có note.
- Số nào master không nói (16 phút @14 kg, 50 phút @1 kg) giữ nguồn cũ với note "master 2.0 không nêu".
- Phân xử 1 và 3 mang điều kiện; câu trả lời của Copilot phải mang điều kiện đó, không rút gọn.
