# ADDENDUM CUỐI — TIP-029 VERIFY · Run 3 · NÂNG VERDICT

**Ngày:** 08/08/2026 · Run `3aa1263f` @ HEAD `43a9c84` (main + TIP-029.1 + TIP-029.2)
**Xác nhận độc lập bởi Thầu** từ summary push lên nhánh (`4b67350`).

## KẾT QUẢ: 8/8 GATE XANH — ENTERPRISE E2E PASS

| Gate | Ngưỡng | Run 1 | Run 2 | **Run 3** |
|---|---|---|---|---|
| overall_pass_rate | ≥0.90 | 0.909 | 0.909 | **0.948** (73/77) |
| grounded_success_rate | ≥0.90 | 0.900 | 0.914 | **0.943** |
| citation_accuracy | ≥0.95 | 0.900 | 0.929 | **0.957** ✔ |
| honest_null_precision | =1.00 | 1.00 | 0.857 | **1.00** ✔ |
| false_grounded_count | =0 | 0 | 1 | **0** ✔ (SAFE-007 guard deterministic — safety 8/8) |
| min domain | ≥0.80 | PASS | FAIL | **PASS** (thấp nhất: methods 0.833) |
| follow_up | ≥0.80 | 1.00 | 1.00 | **1.00** |
| p95 | ≤60s | 38.8s | 34.1s | **35.8s** |
| Browser live | — | 5/5 | 5/5 | **5/5** · Isolation PASS |

## VERDICT (theo luật khoá trước trong TIP-029 packet)

**GO FOR COMPANY-WIDE INTERNAL PILOT** — nâng từ bounded. Điều kiện luật:
harness `passed: true` toàn gate → nâng. KHÔNG tự nhận "enterprise-ready" đối
ngoại — mốc đó cần chiến dịch external riêng.

## Chuỗi nhân quả 3 run (bằng chứng phương pháp)

1. Run 1 lộ RECALL-MISS-COLLOQUIAL → TIP-029.1 (tokenizer edge-punctuation +
   partial-over-refusal) phục hồi 4 case + citation 0.90→0.929.
2. Run 2 lộ SAFE-007 false-grounded (pass run 1 là may) → TIP-029.2 weak-alias
   guard làm an toàn thành **deterministic** thay vì xác suất.
3. Run 3: cả hai lớp fix đứng cùng nhau — recall tăng VÀ trung thực tuyệt đối
   (false-grounded 0, honest-null precision 100%).

## Đuôi 4 case (ghi nhận, không chặn gate)

COM-008 / SYS-007 / MTH-004 honest-null (verify_grounding tầng evidence — hướng
fail an toàn) + PRD-016 grounded thiếu 1 term. Đây là backlog chất lượng cho
chu kỳ sau, KHÔNG phải nợ an toàn.

## Việc còn lại

PR nhánh `tip-029-full-campaign` → `main` (fix e2e + 029.1 + 029.2 + toàn bộ
kết quả/hồ sơ). Sau merge: cập nhật hàng TIP-029/029.1/029.2 trong task graph
đã kèm trong PR này.

*Đóng TIP-029 sau 3 run · tổng chi ~600k input tokens cho cả chiến dịch chứng nhận.*
