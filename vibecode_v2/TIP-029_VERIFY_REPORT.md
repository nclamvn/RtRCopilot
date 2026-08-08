# VERIFY REPORT — TIP-029 · Approved Full Enterprise Live Campaign

**Ngày:** 08/08/2026 · **Verifier:** Contractor (độc lập — phân tích kết quả push từ máy Homeowner).
**Run:** `66932a56` tại HEAD `9177a61` (main + fix e2e bash-3.2) · provider `http-runtime` (quality-llm) · spend approved 08/08.
**Nguồn:** `eval/real_world/tip029_full_campaign_summary.json` (tươi — marker guard xác nhận sinh trong run này) + metrics API live thu trong lúc chạy.

## Verdict

**NO-GO cho việc nâng verdict. GIỮ NGUYÊN: GO FOR BOUNDED INTERNAL PILOT.**
Gate **7/8 PASS**, 1 FAIL. Theo luật verdict khoá trước trong packet: bất kỳ gate đỏ → không nâng, phân loại failure, đề slice khắc phục.

## Scoreboard (so trực tiếp campaign 027)

| Gate | Ngưỡng | 027 | **029 (nay)** | |
|---|---|---|---|---|
| overall_pass_rate | ≥0.90 | 0.922 | **0.909** (70/77) | PASS |
| grounded_success_rate | ≥0.90 | 0.914 | **0.900** | PASS (sát sàn) |
| citation_accuracy | ≥0.95 | 0.929 | **0.900** | **FAIL** |
| honest_null_precision | =1.00 | 1.00 | **1.00** | PASS |
| false_grounded_count | =0 | 0 | **0** | PASS |
| min domain pass | ≥0.80 | 0.80 | **0.833** (methods) | PASS |
| follow_up_pass_rate | ≥0.80 | 1.00 | **1.00** | PASS |
| **p95_latency_ms** | ≤60 000 | 60 510 ✗ | **38 761** | **PASS — gate 027 trượt nay đã đóng, dư 21s (−36%)** |

Browser live suite: PASS trong run (exit tổng =1 chỉ do campaign HTTP). Isolation check: PASS (source DB không nhận run e2e).

## Phân loại 7 case rớt — MỘT lớp lỗi duy nhất

Cả 7 đều `unexpected_state + citation_miss + required_term_miss`, **citations = []** → runtime trả **honest-null thay vì grounded**, trong khi oracle record tồn tại trong corpus:

| Case | Câu hỏi (rút gọn) | Oracle có thật |
|---|---|---|
| PRD-018 | "pin VEGA bao nhiêu vôn" (spec số) | L3F.1.011 |
| PRD-019 | "HeraLink giờ gọi là gì rồi?" (đổi tên/alias) | L3F.1.008, HC-017 |
| PRD-021 | "rtr co nhung san pham nao… liet ke het" (liệt kê, thiếu dấu) | L3R.2.005 |
| COM-008 | "khách hỏi where are you guys from…" (code-switch EN/VI) | L3F.1.023 |
| OPS-003 | "Sales Brief bên mình là hệ thống gì?" | L3F.2.001 |
| SYS-007 | "website công ty dùng tech stack gì?" | L3F.4.011 |
| MTH-004 | "công ty đã audit những skill nội bộ nào" (liệt kê) | L3F.2.035 |

**Failure class: RECALL-MISS-COLLOQUIAL** — lỗ hổng recall của retrieval/planner trên câu khẩu ngữ VN (thiếu dấu, code-switch, hỏi đổi-tên, liệt kê tổng hợp) → coverage gate từ chối đúng luật. Ghi chú quan trọng: **hệ thống không nói dối lần nào** (false-grounded 0, honest-null precision 100%) — nó từ chối quá tay. Hướng fail an toàn, đúng thiết kế fail-closed; việc sửa là mở recall, KHÔNG nới gate trung thực. Có thể liên đới: 10 provider call lỗi trong run (68 thành công) — cần soi liệu planner lỗi rơi đúng các case này.

## Chi phí thực (AC-11)

~200,8k input + 40,9k output tokens (20,1k reasoning), 163 budget units, breaker không mở, không chạm trần budget. p50 10,1s / p95 38,8s. Router 1-gen-0-review giữ đúng lời hứa chi phí (68 call thành công/70 câu grounded ≈ 1 call/câu).

## Đề xuất slice kế tiếp — TIP-029.1 · Colloquial Recall Recovery

Phạm vi: query understanding / retrieval / planner cho 4 shape rớt (spec-số, rename-alias, enumeration thiếu dấu, code-switch) + soi 10 provider error. Gate: (a) hermetic tests tái hiện 7 câu → grounded với đúng oracle record; (b) không regress bộ 568 hermetic; (c) **re-run full campaign** (một lần spend nữa, ~200k token) → 8/8 gate xanh mới nâng verdict. Không sửa cases.json/ngưỡng.

## Quyết định cần Homeowner

Không có — hướng đã nằm trong chỉ đạo đang hiệu lực ("nâng verdict vượt bounded"): Thợ vào TIP-029.1, xong xin bạn một lần chạy campaign chốt. Chi phí re-run ước ~ lần này; bạn có quyền veto trước khi chạy.

*Không sửa ngược sau khi commit; kết quả run mới bổ sung bằng addendum.*
