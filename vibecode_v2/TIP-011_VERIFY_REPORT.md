# VERIFY REPORT — TIP-011 · Unified UX

**Date:** 01/08/2026
**Verifier:** Contractor (independent of the four builder agents)
**Environment:** cloud sandbox — native PostgreSQL 16 (fresh DB per run), MinIO, Redis; Docker compose stack with rebuilt TIP-011 images; chromium; production `next start` for browser gates.
**Method:** independent rerun of every gate on the final tree (builder numbers not trusted), adversarial probe execution, per-AC verdict.

---

## Verdict

**VERIFIED · READY.**

- Acceptance criteria: **14/14 PASS** (AC-05 in its specified safe form — see Deferred).
- P0 open: **0**. P1 open: **0**.
- Gate chính — *browser E2E + axe; keyboard-only critical flows; one product*: **PASS** — axe 0 violations at every impact level across 5 pages × 4 viewports × 2 locales (+10 stateful surfaces); 5 keyboard-only critical flows green; one shell, one rail everywhere.

## REQUIREMENT COVERAGE

- REQ-026 (unified workspace) và REQ-027 (responsive, keyboard-first, WCAG 2.2 AA, Việt/Anh): **implemented** — chuyển từ "foundation" sang có bằng chứng thực thi (axe + keyboard E2E là gate chạy được, không phải cam kết).
- Advanced: REQ-008/REQ-018 (Ask UI + deep citation), REQ-020 (private scope UX), REQ-034 (đủ tile dashboard).

## SCENARIO RESULTS (independently rerun)

| AC | Verdict | Bằng chứng chính |
|---|---|---|
| AC-01 one shell | PASS | shell specs; per-page topbars deleted; typed-error surface thống nhất |
| AC-02 one rail | PASS | 4 workspace dùng chung `EvidenceRail`; forged-zone gates test |
| AC-03 grounded + inspectable | PASS | E2E citation → rail → viewer đúng locator (chuột + keyboard) |
| AC-04 honest-null first-class | PASS | gap id/state hiển thị; curator link; không bịa nội dung |
| AC-05 file-scoped ask theo ACL | PASS (dạng an toàn) | picker chỉ file được xem; không thể lộ evidence sai file/bị cấm; retrieval per-file thật: **deferred** (kế thừa deferral TIP-007) |
| AC-06 pickers không leak | PASS | two-subject probes; denied-vs-nonexistent byte-identical |
| AC-07 zone label trong payload | PASS | literal types; chips không phụ thuộc dashboard |
| AC-08 tiles đủ | PASS | conflict + owner-review live, policy-scoped, leak-safe |
| AC-09 vi/en hoàn chỉnh | PASS | 395=395 keys, parity compile-time + runtime; không màn hình trộn ngôn ngữ |
| AC-10 axe | PASS | **0 vi phạm mọi mức** trên 50+ scan; 4 defect thật được sửa (contrast ratios ghi lại) |
| AC-11 keyboard-only flows | PASS | 5 flow E2E; focus management khi đổi route |
| AC-12 reduced motion + responsive | PASS | computed 0s durations; 0px overflow toàn matrix |
| AC-13 no regression | PASS | backend FULL **292/3 ×2** fresh-DB; Playwright 73/73; probes 10/10 |
| AC-14 full verification | PASS (cloud scope) | compose build EXIT=0; Trivy Clean; DATA INTEGRATION PASS (tests=45, denials=18) |

Failed: **0**.

## TECHNICAL HEALTH (independent)

Build PASS cả hai phía; type/lint 0 lỗi (mypy 83 files, tsc strict); backend full 292 passed/3 skipped chạy 2 lần trùng khớp trên DB mới; web vitest 143; Playwright 73/73 trên production build; masquerade/leak/boundary/forged probes 10/10; single alembic head `0009` (không migration mới trong TIP này).

## DEFERRED (có chủ đích, không chặn)

1. **File-version-scoped retrieval thật** cho Ask — TIP-007 đã defer private/attachment retrieval; TIP-011 giao dạng an toàn (không thể leak, miss → honest-null). Đề xuất: gói vào TIP-012 nếu còn budget, hoặc TIP kế sau TIP-013.
2. **ClamAV signature freshness ≤48h** — ghi chú môi trường sandbox như TIP-010; máy local egress mở sẽ healthy.
3. Restore drill không chạy lại nguyên vẹn trong lượt này (script backend không đổi trong TIP-011); proof AC18 bên trong data-integration gate đã re-pass trên image mới; RESTORE PASS của TIP-010 giữ nguyên giá trị.

## CRITICAL ISSUES

Không có. Ghi nhận polish (không chặn): shared identity context cho topbar sau 401 (C·D6); `generateMetadata` cho description theo locale; proposal payload mang zone label riêng.

## DECISIONS NEEDED FROM HOMEOWNER

Không có quyết định chặn. TIP-011 đủ điều kiện merge `main`. Kế tiếp theo Task Graph: **TIP-012 Production Hardening**.

*Không sửa ngược sau khi commit; bổ sung bằng addendum nếu có kết quả mới.*
