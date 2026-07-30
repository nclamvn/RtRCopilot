# VERIFY REPORT · TIP-001 Security Containment

**Verifier:** Independent Builder
**Ngày:** 30/07/2026
**OVERALL STATUS:** READY

## Requirement coverage

- Total acceptance criteria: 5
- Passed: 5
- Failed: 0
- Coverage: **100%**

## Scenario results

- Regression suite: **288 pass / 0 fail**
- Independent security probes: **25 pass / 0 fail**
- Python compile: **4/4 pass**
- ZIP synchronization: **6/6 changed artifact byte-match**
- UI preview: sinh chính xác từ `ui.html`

## Verified controls

- Corrupt store không làm process crash; health và protected API trả 503.
- Không fallback anonymous/passcode ngoài migration mode.
- Hai account trùng tên không đọc issue/audit của nhau.
- Anonymous, prefix lạ, encoded path và query confusion đều bị chặn.
- Authentication chạy trước file-existence check.
- Owner download 200; cross-user/admin/anonymous bị chặn.
- Ownership persistence qua process mới.
- Generated documents và `.owners.json` có mode `0600`.

## Residual

**P3 deferred:** thư mục `_rendered` mới còn mode `0755`. Nội dung và metadata bên
trong là `0600`, nhưng local user có thể liệt kê filename. Đặt directory `0700` trong
TIP-012 hardening hoặc sớm hơn nếu pilot được mở cho máy nhiều local account.
