# TIP-039 · Production Cutover Execution

**Status:** PLANNED · chờ Homeowner cung cấp input Phase A
**Date:** 23/08/2026
**Priority:** P0
**Depends on:** TIP-035 (đường phát hành + 10 gate preflight đã dựng, fail-loud), TIP-035.12 (AI-surrogate E2E), TIP-035.18 (production configuration validator)
**Method:** Vibecode Kit v6.1 — Contractor / Builder / Homeowner

## 1. Bối cảnh và quyết định định hướng

Preflight `scripts/verify-tip035-release.sh` còn 3 nhóm gate mở: `tip034_usefulness`,
`production_configuration`, `target_operational_drills + homeowner_go`.

**Quyết định Homeowner 23/08/2026:** lùi chiến dịch usefulness với nhân viên thật;
hoàn thiện trước mọi gate không cần người thật. Gate 6 đi bằng đường AI-surrogate
mà TIP-035 đã thiết kế sẵn, với nhãn trung thực bắt buộc
(`human_usefulness_measured=false` + residual risk tự khai). Chiến dịch người thật
vẫn là nghĩa vụ sau cutover, không bị xóa.

## 2. Phạm vi

- IN: đóng gate 6 (surrogate), 8 (production configuration), 9 (drills), 10 (homeowner GO);
  chạy preflight tới `ready`; deploy production đầu tiên.
- OUT: chiến dịch usefulness người thật (packet riêng sau cutover); connector doanh nghiệp
  (giữ feature-off, gate 7 yêu cầu active=0); TIP-014RE.1 (backlog chất lượng, không chặn).

## 3. Phase A — `production_configuration` (gate 8)

Validator: `scripts/validate_production_env.py` + `verify-production-configuration.sh`
(đọc `.env.production`, KHÔNG commit file này — secrets ở ngoài git).

### A0 · Input chỉ Homeowner cung cấp được — CRITICAL PATH

| # | Input | Ràng buộc từ validator |
|---|---|---|
| 1 | Máy chủ deploy production (nội bộ RtR hoặc VPS) | chạy được Docker compose hardened profile |
| 2 | Hostname công khai (vd `copilot.rtr-robotics.com`) | không phải localhost/IP nội bộ (`reserved_host_forbidden`, `non_routable_host_forbidden`) |
| 3 | OIDC tenant thật (Google Workspace / Entra ID) | `OIDC_ISSUER` HTTPS; `OIDC_CLIENT_ID/SECRET`; `OIDC_ALLOWED_DOMAINS` domain email công ty; `OIDC_GROUP_MAPPING` role admin/curator |
| 4 | TLS certificate cho hostname | openssl kiểm: cert khớp hostname, key khớp cert, hạn còn >7 ngày (`-checkend 604800`); hoặc `INGRESS_TLS_MODE` ACME nếu dùng Let's Encrypt qua Caddy |
| 5 | Bộ secrets production MỚI (postgres, redis, s3, oidc, `SOT_SIGNING_SECRET` ≥32 bytes) | không trùng `KNOWN_DEFAULT_SECRETS`, không trùng nhau; sinh bằng `openssl rand -base64 48` |
| 6 | OPENAI_API_KEY production (+ ANTHROPIC nếu có, cho reviewer xoay họ provider) | thiếu → `grounded_answering=evidence_only`; key thứ 2 đã được TIP-030 nâng ưu tiên (OPS-010 1-key fragility) |

### A1 · Builder dựng `.env.production` (làm được ngay sau A0)

- `APP_ENV=production`, `DEV_OIDC_ENABLED=false`, `SESSION_COOKIE_SECURE=true`,
  `RTR_BUILD_SHA` = build identity sạch, `EXPECTED_SCHEMA_REVISION` = alembic head hiện hành,
  `RAG_PROVIDER_MODE=external` + `RAG_EXTERNAL_CLASSIFICATION_ALLOWLIST=internal`
  + `RAG_EXTERNAL_ENDPOINT_POLICY`/`RAG_EXTERNAL_CREDENTIAL_SOURCE` (config.py bắt buộc ở production),
  `RAG_EMBEDDING_PROVIDER=openai`, sàn `RAG_MIN_VECTOR_SCORE` giữ giá trị đã hiệu chỉnh.
- `MAINTENANCE_MODE=false`, `RETENTION_POLICY_JSON` theo chính sách công ty.

### A2 · Exit condition Phase A

`PRODUCTION_ENV_FILE=.env.production ./scripts/verify-production-configuration.sh`
→ `status=pass` (validator 0 lỗi + compose materialization pass + application settings
xác nhận `app_env=production` từ trong container).

## 4. Phase B — `target_operational_drills` (gate 9)

Chạy trên máy chủ production (hoặc staging cùng cấu hình), hardened profile.
4 drill, mỗi drill có dòng PASS máy in ra làm bằng chứng:

| Drill | Lệnh | Bằng chứng pass |
|---|---|---|
| B1 Hardened bring-up | `docker compose -f compose.yaml -f compose.hardened.yaml --profile hardened up -d` + `scripts/wait-ready-hardened.sh` | chỉ ingress publish port; HTTPS 200; api/worker/web/clamav healthy |
| B2 Load + SLO | k6 5 scenario + `scripts/evaluate-slo.sh` | SLO evaluator exit 0 trên kết quả thật |
| B3 Restore RTO | `make restore-drill` (backup → restore vào target scratch, typed confirmation `RESTORE:<target>`) | dòng `RESTORE PASS ... row_counts=100% checksums=100% audit_chain=valid`; RTO ≤300s (035.16 đã chứng minh 49s) |
| B4 Rollback | `scripts/deploy.sh` phiên bản N rồi `scripts/rollback.sh` về N-1 theo `deploy/versions.log` | health xanh sau rollback; version ledger ghi đủ 2 chiều |

Exit: cả 4 dòng PASS lưu vào `eval/runtime/` → Homeowner attest
`TIP035_TARGET_DRILLS_ATTESTED=1`.

## 5. Phase C — `tip034_usefulness` bằng AI-surrogate (gate 6, đường lùi-người-thật)

1. Homeowner duyệt tường minh: `TIP035_AI_SURROGATE_APPROVED=1` (quyết định có hồ sơ, ghi vào packet này).
2. Chạy surrogate campaign trên ĐÚNG candidate build: 27/27 case technical +
   27/27 UI e2e (bộ TIP-035.12 đã dựng).
3. Report bắt buộc mang: `tester_kind=ai_surrogate_not_human_attestation`,
   `human_usefulness_measured=false`, `human_ledger_modified=false`,
   `external_calls_executed=0`, residual risk chứa
   `"human_subjective_usefulness_not_measured"` — preflight từ chối report thiếu các field này.
4. **Ghi sổ trung thực:** verdict cutover sẽ mang nhãn surrogate. Chiến dịch người thật
   là follow-up bắt buộc trong 30 ngày đầu vận hành (dùng chính pilot production).

## 6. Phase D — Preflight `ready` + Homeowner GO (gate 1-5, 7, 10)

1. Đóng băng candidate: commit sạch → rebuild `api worker migrate web` → `docker compose run --build --rm migrate`.
2. Gate kỹ thuật tự lật theo build mới: `candidate_build`, `migration_graph`, `runtime_exact`
   (`verify-answer-runtime.sh`), `isolated_pilot_database` (`verify-pilot-database.sh`),
   `tip033_latency` (chạy lại 5-case immutable trên build này — cần `TIP033_APPROVE_EXTERNAL=1`
   vì export 5 câu hỏi ra provider), `connector_boundary` (active=0 sẵn).
3. `./scripts/verify-tip035-release.sh` → kỳ vọng 9/10 pass, blocked còn `homeowner_go`.
4. Homeowner rà report content-free → ký `TIP035_HOMEOWNER_GO=1` → preflight `ready`.
5. `scripts/deploy.sh` lên production; xác nhận `/health/operational ok:true`,
   `grounded_answering=ready`; ghi verdict + version vào ledger.

## 7. Thứ tự và ước lượng

```text
A0 (Homeowner, critical path) ──► A1-A2 (Builder, ~1 buổi sau khi đủ input)
                                        │
                                        ▼
                              B1-B4 drills (~1 buổi, trên máy chủ thật)
                                        │
              C surrogate (song song B, sau khi Homeowner duyệt) 
                                        │
                                        ▼
                              D preflight + GO + deploy (~nửa buổi)
```

Tổng phần máy: ~2-3 buổi làm việc. Nút cổ chai duy nhất: A0 (tài khoản OIDC, domain, cert, máy chủ).

## 8. Rủi ro và biện pháp

- **OIDC tenant cấu hình sai** → khóa cửa toàn bộ user: test bằng 1 tài khoản thật
  trên staging hardened trước khi cutover; giữ `dev` compose local làm đường chẩn đoán.
- **Cert/hostname lệch** → validator chặn từ Phase A, không tới được deploy.
- **Chi phí LLM production** → budget ngày + breaker đã có; đặt `RAG_*_BUDGET` theo
  quy mô pilot; theo dõi `provider_usage` tuần đầu.
- **Verdict surrogate bị hiểu nhầm là chứng nhận người thật** → mọi báo cáo/ledger
  nhắc rõ nhãn `human_usefulness_not_measured`; follow-up 30 ngày là bắt buộc.

## 9. Audit trail

Packet này + quyết định Homeowner (lùi human test, duyệt surrogate) + 4 dòng PASS drill
+ report preflight `ready` + version deploy tạo thành hồ sơ cutover. Mỗi phase xong
cập nhật hàng TIP-039 trong `03_TASK_GRAPH.md`.
