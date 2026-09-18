# TIP-048 · Completion Report Phase 1 và Phase 2 (Builder)

**Date:** 18/09/2026
**Status:** DONE (dựng và kiểm trong cloud) · chờ Homeowner áp lên máy và commit
**Phạm vi:** luật provenance của kernel, cổng use-class, adapter, và 52 fact hạ tầng mới. Chưa chạm runtime, chưa onboarding.

## 1. Phân xử Homeowner đã nhận

18/09/2026: "cái gì cứng vẫn cần cứng". Sàn cứng giữ nguyên năm nhóm như mục 3.3 của packet. Hai tầng mới và trục use_class được chấp nhận.

## 2. Phase 1 · Luật

| File | Thay đổi |
|---|---|
| `registry/phase_a/provenance_rules.py` | Thêm `attested_practice` và `roadmap_commitment` vào STATUS_MAP (status `ATTESTED`, `ROADMAP`) và PROTECTED_STATUS. Thêm khối TIP-048: `CURATED_VALUE_TIERS`, `TIER_REQUIRED_FIELDS`, `ATTESTATION_TTL_DAYS`, `USE_CLASSES`, `TIER_MAX_USE`, sàn cứng (`HARD_FLOOR_ID_PREFIXES`, `HARD_FLOOR_PATTERN`), và sáu hàm `declared_tier`, `is_hard_floor`, `missing_tier_fields`, `attestation_expired`, `max_use_class`, `allowed_use_classes`, `use_class_violations`. Sửa `keeps_value` để hai tầng mới giữ `value`. |
| `registry/phase_a/provenance_guard.py` | Thêm `tip048_violations` và in kết quả trong cùng lần chạy với guard A3. Exit 2 khi có vi phạm, nên `check.sh` chặn publish. |

Ba luật được cài có răng:

1. **Trường bắt buộc.** `attested_practice` thiếu `attested_by` hoặc `attested_on` là FAIL. `roadmap_commitment` thiếu `owner` hoặc `target_date` là FAIL. Một lời chứng không có người đứng tên thì không phải lời chứng.
2. **Sàn cứng.** Fact thuộc năm nhóm (id bắt đầu `SPEC.`/`PRICE.`/`COST.`/`BOM.`, hoặc nội dung khớp mẫu chứng nhận, tuân thủ pháp lý, cư trú dữ liệu, thương mại) mà dùng tầng curated là FAIL.
3. **Hết hạn lời chứng.** `attested_on` quá 365 ngày thì fact tự rớt khỏi mọi ngữ cảnh. Chống con dấu cao su.

`use_class` chỉ thu hẹp được, không nới quá tầng.

## 3. Phase 2 · 52 fact hạ tầng

Nạp vào `l3_facts.yaml`, namespace `L3F.INF.001` đến `L3F.INF.094`. Nguồn: bản trả lời NJ questionnaire do team phần mềm soạn 18/09/2026.

| Nhóm | Số fact | Tầng |
|---|---|---|
| Kiến trúc hệ thống (cấu phần, AWS, ECS/EKS, dữ liệu vận hành không lưu cloud) | 5 | attested_practice |
| Mã hóa (TLS 1.2+, AES-256 đầu cuối, KMS envelope, Argon2id, Secrets Manager) | 6 | attested_practice |
| Truy cập và xác thực (MFA, SAML/OIDC, RBAC, mật khẩu 10 ký tự, IP allowlist) | 7 | attested_practice |
| Vòng đời phát triển (Git/PR/CI, tách môi trường, Ansible IaC, Dependabot, WAF, ký số) | 7 | attested_practice |
| Giám sát (CloudWatch, CloudTrail, log 365 ngày, nguồn threat intel, xếp ưu tiên CVSS) | 4 | attested_practice |
| Dự phòng (backup RDS, PITR, test khôi phục nửa năm, Multi-AZ, suy giảm có kiểm soát) | 5 | attested_practice |
| Thực hành tổ chức (NDA, onboarding/offboarding, đào tạo, Privacy Policy, IR Plan) | 9 | attested_practice |
| Endpoint (cấu hình laptop, thiết bị công ty, chặn BYOD, thiếu MDM tự nhận) | 4 | attested_practice |
| Cam kết lộ trình (MDM, pen test, đào tạo secure coding, quy trình rà soát, bảo hiểm mạng) | 5 | roadmap_commitment |

**Cố ý KHÔNG nạp ở đợt này**, vì thuộc sàn cứng và cần bằng chứng tài liệu hoặc chữ ký Homeowner:

- Cam kết cư trú dữ liệu ("toàn bộ dữ liệu bang nằm trong nước Mỹ"). Đây là cam kết hợp đồng, nhóm 3 của sàn cứng.
- Mọi tuyên bố về chứng nhận: FIPS 140 của AWS KMS, SOC 2 và ISO 27001 của nhà cung cấp. Fact `L3F.INF.067` cố ý nói về *thực hành rà soát* nhà cung cấp mà không nêu tên chứng nhận.
- Trạng thái Blue UAS, còn ba phiên bản mâu thuẫn (Phase 3).

## 4. Kiểm định

| Phép thử | Kết quả |
|---|---|
| Guard A3 + cổng TIP-048 trên toàn registry | **Sạch, exit 0.** Không fact cũ nào bị vỡ (tương thích ngược). |
| Cổng chặn thử: đặt `attested_practice` cho một fact `SPEC.*` | Chặn đúng: `hard_floor_needs_documentary_evidence` |
| Cổng chặn thử: nội dung chứa "SOC 2" với tầng curated | Chặn đúng |
| Cổng chặn thử: `attested_on` năm 2024 | Chặn đúng: `attestation_expired` |
| `validate.py` | 418 entry, 0 issue, 0 trùng id. Sáu dòng "Source missing" chỉ do mirror cloud không có `source_canonical/`; trên máy Homeowner sẽ sạch. |
| Adapter dry-run (`--curated`) | ready 325 lên **377** (+52). Cả 52 fact mới đều `ready`, tier soft, không fact nào rơi `needs_curation`. |
| `use_class` trên record phát ra | `attested_practice` cho ra `[sales, proposal]`; `SPEC.HERA.PAYLOAD.MAX` giữ đủ `[sales, proposal, attestation]`. |
| Em-dash trong 52 fact mới | 0 |

## 5. Deviations

| # | Việc | Lý do |
|---|---|---|
| D1 | `attested_by` ghi "Team phần mềm RtR" thay vì tên một kỹ sư | Tôi không có tên người. Trường vẫn đủ để audit tới cấp đội, nhưng Homeowner nên thay bằng tên cá nhân chịu trách nhiệm để lời chứng truy được tới người. |
| D2 | `owner` của 5 fact roadmap cũng để ở cấp đội | Như D1. |
| D3 | Task 1.5 (lọc theo `use_class` ở tầng trả lời) chưa làm | Record đã mang sẵn `use_class`, nhưng việc dạy answer layer nhận ngữ cảnh câu hỏi là thay đổi lớn hơn, tách sang Phase 4. Tới lúc đó, `use_class` là dữ liệu mô tả, chưa phải bộ lọc chạy được. |
| D4 | Fact kiến trúc nạp ở tầng `attested_practice` dù phân xử 1 (kiến trúc thật) chưa được chốt tường minh | Tầng này chỉ khẳng định "team kỹ thuật nói đây là kiến trúc", không khẳng định như cam kết pháp lý. Nếu Homeowner chốt khác, sửa `L3F.INF.001` và `002`. |

## 6. Việc còn lại

1. **Phase 3:** đóng cổng Blue UAS `L3F.REG.015`; nạp danh mục chứng nhận (ISO 9001, FCC DA 26-761, MIL-STD-810, DO-160G, ITAR, FAA Part 107) ở tầng có bằng chứng tài liệu; quyết cách khai cư trú dữ liệu và nhân sự Việt Nam.
2. **Phase 4:** onboarding revision mới; dạy answer layer lọc theo `use_class`; chạy bộ eval BU-001 đến BU-008.
3. Thay `attested_by` và `owner` bằng tên người (D1, D2).
