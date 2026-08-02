# RtR Copilot V2 — GO / NO-GO Decision Document

> **Loại tài liệu:** Release gate · Homeowner decision
> **Ngày lập:** 01/08/2026
> **Trạng thái:** Phase A (cơ chế) đã VERIFIED · **Phase B (dữ liệu thật) CHỜ HOMEOWNER**
> **Người ký go/no-go:** Nguyễn Cảnh Lâm (Homeowner) — *không phải agent*

Tài liệu này là cổng cuối. Agent đã dựng và kiểm chứng **cơ chế** phát hành trên
dữ liệu tổng hợp (TIP-001…013 Phase A). Nó **không** tự tuyên bố GO. GO chỉ xảy
ra khi anh cung cấp các đầu vào thật bên dưới, các tiêu chí thoát được đo trên
dữ liệu thật, và anh ký.

---

## 1. Trạng thái nền tảng (đã chứng minh — Phase A)

| Trục | Bằng chứng |
|---|---|
| 34/34 REQ | Ma trận `TIP-013_REQ_MATRIX.md`: 33 implemented, 1 partial (REQ-020), 0 deferred — mỗi dòng neo vào code/test/gate |
| Bảo mật vận hành | TLS ingress 15/15 probe, boot guard fail-closed secret, rate/body/cost limits, circuit breaker (TIP-012) |
| Quan sát & phục hồi | Prometheus + 11 alert rule, audit export, restore RTO ~236s, rollback drill (TIP-012) |
| Chất lượng trả lời | Eval synthetic: grounded 100%, honest-null 100%, **leak 0**, citation 100% |
| Parity V1 | 6/7 (scoped asks khớp tuyệt đối; 1 lệch là artifact embedding offline, đo lại ở Phase B) |
| Onboarding an toàn | Batch qua cổng curator fail-closed; batch lỗi bị chặn, zero partial activation |
| Regression | Backend full 394/18/0 ×2; Playwright 73/73; data-integration PASS; Trivy Clean |

**Kết luận Phase A:** cơ chế sẵn sàng. Không P0/P1 mở trong phạm vi cơ chế.

---

## 2. Đầu vào CHỈ HOMEOWNER cung cấp được (chặn Phase B)

Không có các mục này thì không thể cutover. Agent không được bịa.

| # | Đầu vào | Trạng thái | Ghi chú |
|---|---|---|---|
| H1 | **Tenant Google Workspace OIDC thật** + allowed domains (`rtrobotics.com`, `rtrobotics.me`) — client id/secret, issuer | ☐ AWAITING HOMEOWNER | Hiện dùng dev-OIDC; production guard đã sẵn, chỉ cần config thật |
| H2 | **Chứng chỉ TLS thật** cho hostname production | ☐ AWAITING HOMEOWNER | Caddy đã có đường cắm cert file; local đang dùng internal CA |
| H3 | **Batch dữ liệu SOT thật** (137 nhân viên + 162 lãnh đạo + kernel), đã curator duyệt + phân loại + provenance | ☐ AWAITING HOMEOWNER | Onboarding tool sẵn sàng; anh chỉ định owner từng batch |
| H4 | **KnowledgeBase thật** (~1.454 file / 1,19 GB) theo đợt qua quarantine | ☐ AWAITING HOMEOWNER | Không index thẳng; theo batch có owner |
| H5 | **Research corpus thật** (~587 record) qua Refinery adapter → graduation gate | ☐ AWAITING HOMEOWNER | Không tự thành fact RtR |
| H6 | **Secret production thật** (DB, Redis, S3, OIDC, SOT) thay mọi giá trị `[MUST-CHANGE]` | ☐ AWAITING HOMEOWNER | Boot guard sẽ từ chối nếu còn default |
| H7 | **Nhóm pilot** + câu hỏi thật + phân quyền khác nhau | ☐ AWAITING HOMEOWNER | Đo 5 chỉ số vận hành trên nhóm này |
| H8 | **Thẩm quyền ký go/no-go** | ☐ AWAITING HOMEOWNER | Chính anh |

---

## 3. Tiêu chí thoát — đo trên DỮ LIỆU THẬT (Phase B)

GO chỉ khi tất cả xanh (hoặc defer có owner+ngày, và không P0/P1):

- ☐ **AC-B1** Batch thật onboard bởi curator; zero activation trái phép (chạy lại onboarding tool ở chế độ `--apply` trên dữ liệu thật).
- ☐ **AC-B2** Parity chấp nhận được trên 137/162 record thật (chạy lại `make parity` với embedding + provider thật).
- ☐ **AC-B3** Eval đạt ngưỡng trên corpus đại diện thật: grounded rate ≥ ngưỡng, honest-null quality cao, **leak = 0**, citation-accuracy cao (chạy lại `make eval`).
- ☐ **AC-B4** OIDC tenant thật + cert thật live; chạy lại drill hardened (RPO/RTO, rollback) trên deployment thật.
- ☐ **AC-B5** Pilot staged xong; thu 5 chỉ số: time-to-evidence, grounded rate, honest-null quality, document cycle time, leakage/authorization failures.
- ☐ **AC-B6** Zero P0/P1 mở; deferred P2/P3 có owner+ngày; quyết định rollback ghi lại; **Homeowner ký**.

---

## 4. Ledger deferred cần đóng trước hoặc trong pilot

Từ `TIP-013_DEFERRED_LEDGER.md` — không mục nào là P0/P1:

- **Fix-in-pilot:** `restore-data.sh` `mc mirror` (giữ per-object marker); DB pool re-baseline trên phần cứng thật (knee ~15 reads/s local); CSP nonce; calibrate real-provider latency + cost budget; ClamAV freshness (egress mở); **REQ-020** file-version/attachment retrieval (cân nhắc TIP kế hoặc trong pilot).
- **Accept-with-owner:** bật branch-protection "require verify job" trên GitHub; external penetration test (đầu vào go/no-go).

---

## 5. Khuyến nghị của Tổng công trình sư

1. **Phase A đủ điều kiện merge `main`** — cơ chế phát hành đã chứng minh.
2. Bắt đầu Phase B theo thứ tự rủi ro thấp→cao: H6 secret → H2 cert → H1 OIDC → H3/H4/H5 dữ liệu theo batch nhỏ có owner → H7 pilot.
3. Chạy lại đúng ba harness Phase A (`onboard-batch`, `parity`, `eval`) trên dữ liệu thật — chúng được thiết kế để tái dùng nguyên vẹn.
4. Chỉ gọi "production-ready / GO" sau khi mục 3 (tiêu chí thoát) xanh và anh ký mục H8/AC-B6.
5. Giữ V1 read-only làm oracle cho tới khi AC-B2 đạt trên dữ liệu thật.

**Ô ký:**

```
GO / NO-GO:  ___________     Ngày: ___________
Homeowner (Nguyễn Cảnh Lâm): ______________________
Điều kiện/deferred kèm theo: ______________________
```

*Agent dừng ở đây theo thiết kế. Launch authority là con người.*
