# VERIFY REPORT — TIP-010 · Governance & Research

**Date:** 01/08/2026
**Verifier:** Contractor (independent of the five builder agents)
**Verification environment:** Anthropic cloud sandbox — native PostgreSQL 16 at
migration 0009, MinIO, Redis; Python 3.12/uv; Node 22/pnpm; chromium.
**Method:** independent rerun of every gate (not trusting builder-reported
numbers), adversarial probe execution, code-boundary inspection, per-AC
verdict. Container-image gates could not run here (see Deferred).

---

## Verdict

**READY — với deferred (3 mục môi trường, liệt kê bên dưới).**

- Acceptance criteria: **13/16 PASS đầy đủ · 3/16 PASS trong phạm vi cloud với
  phần môi trường deferred (AC-13, AC-15, AC-16)**.
- P0 open: **0**. P1 open: **0**.
- Gate chính — *research never masquerades as RtR fact*: **PASS, 0 hits** trên
  toàn bộ probe suite, kiểm độc lập.
- Điều kiện trước khi merge `tip-010` vào `main`: chạy `make verify` trên máy
  local (compose build + Trivy + containerized data-integration) và chạy
  Playwright trên stack sống. Homeowner quyết định sau khi gate local xanh.

## REQUIREMENT COVERAGE

- REQ trực tiếp của TIP-010: **7/7 advanced** — REQ-033, REQ-034 (từ chưa có →
  implementation end-to-end); REQ-009, REQ-011, REQ-012, REQ-016, REQ-032
  (foundation → có workflow/enforcement thật).
- REQ-026/027 được đẩy thêm qua workspace mới nhưng quyền sở hữu vẫn thuộc
  TIP-011 — không tính vào coverage của TIP này.

## SCENARIO RESULTS (per-AC, independently rerun)

| AC | Verdict | Bằng chứng chính |
|---|---|---|
| AC-01 honest-null → governed gap | PASS | RAG 13/13 + gap dedupe/occurrence tests; policy-safe digest |
| AC-02 gap lifecycle append-only + SLA | PASS | transition matrix, immutable decline, history tests |
| AC-03 freshness queue live | PASS | boundary tests; stale row cannot mask live expiry |
| AC-04 conflict queue two-sided, gate-only resolution | PASS | disputed/superseded surfacing; no in-place mutation exists |
| AC-05 research import fail-closed | PASS | 7 contract-violation classes → whole-package reject, audited, zero partial rows; idempotent re-import |
| AC-06 records immutable, tiered, evidence-linked | PASS | DB triggers + zero update path + tests |
| AC-07 zone labels unforgeable | PASS | CHECK constraints both sides; `Literal["research"]` models; client-edge `zone_label_forged` gate |
| AC-08 SOT-scoped retrieval excludes research | PASS | masquerade probe 0 hits (adversarial shared tokens); `chunks CHECK source_zone='sot'`; no `FROM chunks` in research/ (grep-verified) |
| AC-09 graduation cannot bypass publish gate | PASS | draft candidate `claim` staged via TIP-006 `stage()`; injection tests green; no auto-activation |
| AC-10 separation of duties under races | PASS | proposer≠decider row-lock; concurrent/duplicate/stale decision tests |
| AC-11 admin cannot touch truth | PASS | boundary tarpit 7 families typed-403+audit, independently rerun; surface-inventory test pins route set |
| AC-12 dashboard live + leak-safe | PASS | two-subject scoping, zero-leak stranger, live-reflection tests; tiles recompute (no stored aggregate) |
| AC-13 Knowledge Ops UX operable | PASS (cloud scope) · deferred phần live-stack | vitest 67; Playwright mocked 28/28 gồm keyboard, 4 viewport overflow/focus, drawers; **live-stack E2E + axe: deferred local** |
| AC-14 policy/DLP races fail closed | PASS | classification-revocation mid-flow tests (source lever); recheck-before-commit proven |
| AC-15 recovery covers governance | PASS (schema scope) · deferred drill | 0009 trong backup/restore manifest + grants restoration tests; **full containerized restore drill: deferred local** |
| AC-16 full verification | PASS (native scope) · deferred compose | full suite **278 passed / 3 skipped, chạy độc lập 2 lần giống hệt**; unit 210/71; web 67 + build PASS; **compose build + Trivy + containerized gate: deferred local** |

Failed: **0**. Untestable-in-environment (deferred): các phần môi trường của
AC-13/15/16 nêu trên.

## TECHNICAL HEALTH (independent reruns)

- Build: web production build PASS; backend import/OpenAPI clean.
- Type errors: **0** (mypy --strict, 83 source files).
- Lint errors: **0** (ruff; eslint).
- Tests: **278 passed / 3 skipped** full-suite với live infra (Contractor rerun
  ×2, kết quả trùng khớp tuyệt đối); 210/71 unit-phase; vitest 67/67;
  Playwright mocked 28/28. 3 skip là fixture môi trường, trùng baseline TIP-009.
- Alembic: single head `0009_governance_research`; upgrade/downgrade/re-upgrade
  đã được builder chứng minh trên DB có dữ liệu, Contractor xác nhận head.

## DEFERRED (điều kiện hoàn tất trên máy local trước merge)

1. `make verify` trọn vẹn — compose image build bị chặn bởi TLS-intercepting
   proxy của sandbox tại tầng tải Vosk model (image fail-closed đúng thiết kế;
   đây là giới hạn môi trường, không phải lỗi code). Gồm cả Trivy scan và
   containerized data-integration.
2. Playwright trên stack sống (`PLAYWRIGHT_BASE_URL=http://localhost:3000`
   hoặc `next start`) + axe pass cho `/knowledge-ops`.
3. Restore drill containerized (`make restore-drill`) xác nhận 7 bảng mới.

## CRITICAL ISSUES

Không có P0/P1. Ghi nhận theo dõi (không chặn): OIDC re-sync ghi đè admin
binding ở lần login kế (4a·D2 — inherent TIP-003, TIP-012 cân nhắc
`entitlements`); dashboard scan bound 1000 rows (TIP-012/013); crashed-approval
edge có audit + recovery bằng re-proposal.

## DECISIONS NEEDED FROM HOMEOWNER

1. Chạy `make verify` + Playwright live-stack + restore drill trên máy local;
   nếu xanh → merge `tip-010` vào `main` và TIP-010 chuyển VERIFIED · READY
   không điều kiện.
2. Xác nhận REQ intent: admin được phép gán role `admin` cho subject khác
   (primitive có sẵn của TIP-003 — 4a khuyến nghị xác nhận).

*Verify Report này lập trên branch `tip-010` (5 commit builder). Không sửa
ngược sau khi commit; kết quả gate local sẽ được ghi bổ sung, không ghi đè.*
