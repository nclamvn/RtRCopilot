# COMPLETION REPORT · TIP-001 Security Containment

**STATUS:** DONE
**Ngày:** 30/07/2026

## Files changed

- `phase1_pilot/auth.py`
- `phase1_pilot/copilot_server.py`
- `phase1_pilot/ui.html`
- `phase1_pilot/test_copilot.py`
- `tools/render_doc.py`
- `RtR_Copilot_UI_Preview.html` — generated
- `Phase1_Pilot_Kit.zip` — generated kit đồng bộ source

## Implemented

- Auth default-deny cho mọi data API; route/action không khai bị chặn.
- Normal account mode fail-closed; migration và bootstrap phải bật explicit.
- Missing/corrupt/no-admin store giữ process sống nhưng health/data API trả 503.
- GAP chỉ leader/admin; used-by và audit áp privacy theo role.
- Staff issues/audit được cô lập bằng stable email `user_id`, không display name.
- Legacy log thiếu `user_id` fail-closed với staff.
- Generated download owner-only; admin không mặc định đọc chéo.
- Ownership metadata tồn tại qua restart.
- Generated DOCX/XLSX và owner registry có file mode `0600`.
- UI gửi auth trên search/record/templates/download và ẩn GAP khỏi staff.

## Acceptance results

| AC | Result |
|---|---|
| AC-001 Anonymous matrix | PASS |
| AC-002 Role matrix và row isolation | PASS |
| AC-003 Download ownership | PASS |
| AC-004 Corrupt auth store | PASS |
| AC-005 Regression | PASS |

## Test results

- Full regression/security/refine suite: **288 pass, 0 fail**
- Python compile: PASS
- Rebuild/export/selftest/ZIP sync: PASS
- Candidate QA: 123 cards, 0 hard error, 5 pre-existing soft warnings
- `git diff --check`: PASS

## Deviations

- Ownership tạm dùng email + `_rendered/.owners.json`; migrate immutable UUID và
  transactional DB ở TIP-004.
- Generated preview và ZIP được cập nhật vì cổng anti-drift yêu cầu artifact khớp
  source.
