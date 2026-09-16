# TIP-046 · Phase 1 Completion Report (Builder)

**Date:** 16/09/2026
**Builder:** Claude (cloud workspace), Homeowner áp lên máy
**Phạm vi:** registry kernel (specs, capabilities, l3_facts, source_hashes) và source_canonical/master_spec. Chưa chạm ứng dụng, chưa onboarding.
**Trạng thái:** BUILT · dry-run sạch · chờ Homeowner áp và commit

## 1. Kết quả dry-run (mirror kernel trong cloud, cùng validate.py và provenance_guard.py của registry)

| Kiểm | Kết quả |
|---|---|
| `validate.py` | 366 entry, 0 issue, 0 duplicate ID, 0 fact thiếu provenance. 9 hash master khớp. Cảnh báo drift chỉ do mirror cloud có mtime khác máy Homeowner, trên máy thật sẽ hết |
| `provenance_guard.py` (A3) | Sạch. SPEC.HERA.RANGE.EXTENDED giữ dạng `claim` + `verified_value: null` vì chờ Quoc Luong |
| Adapter `kernel_adapter.convert_registry --curated` (stub backend, chỉ phân loại, không emit) | ready 235 → 325 (+90). specs strict 7 → 98, soft 4 → 2, needs_curation 8 → 7. Không record nào đang ready bị rớt |
| Em-dash | 0 trong nội dung mới; en-dash chỉ còn trong `raw_text` chép nguyên văn từ master |

Record đổi tầng: SPEC.HERA.PAYLOAD.MAX soft → strict; SPEC.HERA.PAYLOAD.BAYS needs_curation → strict (giải cờ CONFLICT); SPEC.HERA.FLIGHT.MISSION_PAYLOAD soft → strict; SPEC.HERA.EDGE_AI.TOPS claim → strict. Record mới không ready duy nhất: SPEC.HERA.RANGE.EXTENDED (chủ ý).

## 2. Thay đổi theo file

**specs.yaml** 19 → 107 fact. Sửa 10 record HERA cũ (đơn vị lb → kg cho WEIGHT.EMPTY/TAKEOFF, MTOW 31 → 29,6 kg, PAYLOAD.MAX nguồn master + `value_lb: 30` + `value_kg_exact: 13.6`, PAYLOAD.BAYS 4 cổng 120 W, FLIGHT.MISSION_PAYLOAD 40 phút @6 lb verified_primary, EDGE_AI.TOPS 21 Xavier NX). Thêm 88 record: HERA 2.0 (33), HeraHub 2.0 (7), VEGA + VegaHub (17), HeraSight NDAA/Standard (12), HeraSight61 NDAA (5), LS1 (6), S1 (7), Tether (9). Mỗi record mới có `source.file/sheet/cell/raw_text` để đạt tầng strict. `canonical_sources` thêm 9 master; khối `master_spec_sync` ghi ba phân xử.

**capabilities.yaml** HC-001 (HERA), HC-002 (VEGA), HC-020 (Edge AI, đổi tên), HC-015 (LS1: 106 dB @3 m thay 120 dB @300 m) viết lại theo master, có `notes` trỏ SPEC.*; `last_updated` 2026-09-16.

**l3_facts.yaml** Mới: L3F.REG.016 bảng chuẩn HERA 2.0 hiện hành (approved_internal). Viết lại: L3R.K.007 tầm điều khiển hai số có điều kiện, thêm `provenance_level: approved_internal` để adapter không rơi vào provenance_missing. Ngoặc cập nhật ở đầu content, giữ nguyên văn phía sau: L3F.REG.009, L3R.1.010, L3R.2.028, L3R.2.014. Sửa câu: L3F.CMP.001 (TOPS có điều kiện, bỏ em-dash), L3F.PRD.001 (số nền theo master), L3F.REG.006 (câu cuối về 15 km).

**source_hashes.yaml** thêm 9 dòng `master_spec/*` (sha256 16 ký tự, mtime, size đo trên máy Homeowner sau khi copy lúc 03:08:02 16/09).

**source_canonical/master_spec/** 9 workbook đã copy vào máy Homeowner (thuộc repo kernel cha, không phải repo registry).

## 3. Phát hiện ngoài kế hoạch

1. **Trùng số TIP.** Trong lúc phiên này lập kế hoạch với số 041/042, các phiên khác (28/08 đến 03/09) đã dùng TIP-041 (US Proclamation 11055, COMPLETE, runtime revision 6), TIP-042 (Product hardening), TIP-043, TIP-044, TIP-045. Gói này đổi thành TIP-046, gói NJ questionnaire thành TIP-047. Hai file cũ `TIP-041_MASTER_SPEC_SYNC.md` và `TIP-042_NJ_SECURITY_QUESTIONNAIRE.md` (untracked) cần xóa.
2. **SOT revision hiện hành là 6, không phải 4.** Phase 2 dùng `--revision 7` sau khi kiểm SQL.
3. **R7, bộ ghi hiện trường Tây Ninh 24/08** (`vanban_noibo/BoGhiHienTruong_BayThuNghiem_TayNinh_25-29-08-2026.docx/.pdf`, cũng là nguồn của L3F.REG.009) ghi "Tầm điều khiển HERA 15 km" trần, "10 km (đó là VEGA)" và "số chính thức hiện hành là 15 km". Theo phân xử 16/09 cả ba câu này là số cũ. Không sửa file nguồn (đã băm hash). Cần Homeowner cho biết bộ ghi này đã gửi Sở KHCN Tây Ninh chưa; nếu đã gửi, ghi nhận sai lệch trong ledger và phát hành bản 2 kèm điều kiện ăng-ten.
4. **Website** đang ghi LS1 "120 dB ở 300 m", mâu thuẫn master (106 dB @3 m, tầm 400 m). Ghi vào HC-015 notes, chưa sửa website.
5. **Factsheet báo chí 14/07/2026** (L3R.2.028) dùng số trước master (MTOW 30,5 kg, 15 km, 105 TOPS). Cần cập nhật trước lần phát hành sau.
6. **Ledger `03_TASK_GRAPH.md`** dừng ở TIP-038; các hàng 039 đến 045 chưa ghi. Bổ sung ở commit này theo header của từng packet, không tự suy verdict.

## 4. Deferred (có REQ-ID)

| ID | Việc | Chờ |
|---|---|---|
| TIP-046.D1 | Nâng SPEC.HERA.RANGE.EXTENDED lên VERIFIED/verified_primary, sửa note L3F.REG.016 và L3R.K.007 | Quoc Luong xác nhận HERA đạt 15 km với ăng-ten 8 dBi |
| TIP-046.D2 | Bộ ghi hiện trường Tây Ninh bản 2 (điều kiện ăng-ten, bỏ "10 km là VEGA") | Homeowner cho biết trạng thái đã gửi |
| TIP-046.D3 | Website LS1 và factsheet báo chí đồng bộ master | Owner nội dung |
| TIP-046.D4 | HeraSight61 Standard (master cbc7a63b90f8) mới có hash, chưa atomize fact | Phase 1b nếu cần |

## 5. Không làm

Không sửa file nguồn nào trong source_canonical. Không chạm ứng dụng, DB, worker, secret. Không gọi LLM ngoài. Không xóa file trên máy Homeowner (bridge không xóa được, lệnh xóa để Homeowner chạy).
