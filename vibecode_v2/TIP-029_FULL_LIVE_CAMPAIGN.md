# TASK INSTRUCTION PACK — TIP-029 · Approved Full Enterprise Live Campaign

**Ngày:** 08/08/2026 · **Role cycle:** Thầu (packet+verify) → Thợ (runner) → Homeowner (chạy trên máy có stack) → Thầu (verify kết quả).
**Spend approval:** Homeowner phê duyệt trong phiên 08/08/2026 ("duyệt chi chạy full 77+ live campaign") — điều kiện treo của TIP-027.5 đã được đáp ứng.

## Bối cảnh

- Campaign full gần nhất (kỷ nguyên TIP-027): **71/77 (92.2%)** — **NO-GO** vì trượt
  đúng 2 gate: citation accuracy 92.9% < 95% và p95 60.51s > 60s.
- TIP-027.5 xây deterministic exact path + router 1-generation-0-review + spend
  guard **nhắm thẳng vào 2 gate đó**; bounded recert 12-case: citation 100%,
  false-grounded 0, browser 5/5.
- Giả thuyết cần kiểm chứng: runtime 027.5 trên `main` (4bbb3fa) giờ qua được
  **toàn bộ** gate của campaign trên tập đầy đủ.

## Task

Chạy full campaign qua harness sẵn có (không sửa harness, không sửa ngưỡng):

```bash
E2E_APPROVE_FULL=1 E2E_ENV_FILE=.env.demo ./scripts/run-enterprise-e2e.sh
```

qua wrapper `scripts/run-tip029-full-campaign.sh` (Thợ viết): preflight → chạy →
chốt kết quả vào `eval/real_world/tip029_full_campaign_summary.json` + log đuôi →
tự commit + push nhánh `tip-029-full-campaign` để Thầu verify độc lập.

## Acceptance Criteria — dùng NGUYÊN ngưỡng tự chấm của harness (cases.json)

| Gate | Ngưỡng | Mốc 027 (để so) |
|---|---|---|
| overall_pass_rate | ≥ 0.90 | 0.922 ✓ |
| grounded_success_rate | ≥ 0.90 | 0.914 ✓ |
| **citation_accuracy** | **≥ 0.95** | 0.929 ✗ → 027.5 phải đóng |
| honest_null_precision | = 1.00 | 1.00 ✓ |
| false_grounded_count | = 0 | 0 ✓ |
| minimum_domain_pass_rate | ≥ 0.80 mọi domain | company 80% (sát sàn) |
| follow_up_pass_rate | ≥ 0.80 | 1.00 ✓ |
| **p95_latency_ms (http)** | **≤ 60 000** | 60 510 ✗ → 027.5 phải đóng |
| Browser live suite | toàn bộ PASS | 5/5 ✓ |
| E2E isolation check | source DB không nhận run e2e | ✓ (harness tự chặn) |

**AC-11 (cost, theo TIP-027.5 §4):** provider calls/tokens per-case không vượt
mốc campaign trước (router 1-gen-0-review phải rẻ hơn, không đắt hơn).

## Luật verdict (định trước, không xê dịch sau khi có số)

- Harness `passed: true` (mọi gate xanh) → Thầu nâng verdict:
  **GO FOR COMPANY-WIDE INTERNAL PILOT** (thay bounded). Vẫn KHÔNG tự nhận
  "enterprise-ready" đối ngoại — đó là mốc khác, cần chiến dịch external riêng.
- Bất kỳ gate nào đỏ → verdict GIỮ NGUYÊN bounded; Thầu phân loại failure class
  và đề xuất slice khắc phục (như chu trình 026.x). Không "coi như xong".
- Kết quả dù PASS hay FAIL đều được commit + push (paper trail hai chiều).

## Điều kiện tiên quyết (Homeowner, một lần)

1. `v2/.env.demo` có **key LLM đã rotate** (`ANTHROPIC_API_KEY` hoặc
   `OPENAI_API_KEY`) — thiếu key campaign rơi về evidence-only và chắc chắn
   trượt gate chất lượng; runner sẽ chặn từ preflight.
2. Docker Desktop đang chạy.

## Ràng buộc

- Không sửa `cases.json`/ngưỡng/harness trong slice này — đo bằng thước cũ để so
  được với 027. Muốn đổi thước là TIP riêng.
- Runner mặc định **build lại image** (`E2E_SKIP_BUILD=0`) để runtime đúng
  `main@4bbb3fa`; cho phép override khi cần chạy nhanh.
- Key không bao giờ vào commit (`.env.demo` đã gitignore; runner không echo env).
