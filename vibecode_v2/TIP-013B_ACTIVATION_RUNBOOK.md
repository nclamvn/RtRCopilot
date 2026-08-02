# TIP-013B · Real-Activation Runbook (Phase B cutover)

> **Người thực hiện:** Homeowner (Nguyễn Cảnh Lâm) + curator được ủy quyền
> **Trạng thái:** cơ chế đã sẵn sàng · **chờ đầu vào thật của anh**
> **Nguyên tắc:** agent KHÔNG chạy `--apply` (không giữ credential thật). Tài
> liệu này biến việc activate thành MỘT bước có kiểm soát, đã diễn tập.

Bài diễn tập migrate đã chạy sạch trên dữ liệu kernel thật (DRY-RUN): dưới
chính sách nới đã duyệt, **38/259 fact sẵn sàng** (5 strict + 33 soft), 6 gói
qua cổng publish (valid, 0 finding), 41 fact còn cần curation cơ học, 180 fact
`claim` chờ quyết định promotion. Runbook này là đường từ 38-ready-dry-run →
activate thật.

---

## 1. Đầu vào anh cần cung cấp (agent không bịa được)

Điền vào một file `.env.production` (KHÔNG commit) — mọi giá trị `[MUST-CHANGE]`:

| Khóa | Ý nghĩa | Ai cấp |
|---|---|---|
| `POSTGRES_PASSWORD`, `POSTGRES_RUNTIME_PASSWORD` (+ trong `MIGRATION_DSN`/`POSTGRES_DSN`) | Mật khẩu DB thật | anh (H6) |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Khóa object storage thật | anh (H6) |
| `SOT_SIGNING_SECRET` | Bí mật ký attestation gói SOT, ≥32 byte ngẫu nhiên riêng | anh (H6) — **quan trọng nhất cho onboarding** |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Tenant Google Workspace thật | anh (H1) |
| `OIDC_ALLOWED_DOMAINS` | `rtrobotics.com,rtrobotics.me` (đã set sẵn) | xác nhận |
| `DEV_OIDC_ENABLED=false` | Production từ chối `true` | đặt false |
| `PUBLIC_BASE_URL=https://<hostname production>` | Origin ingress thật | anh (H2) |
| Cert TLS thật | Đặt vào `infra/ingress/certs/`, trỏ `INGRESS_TLS_MODE` sang file cert | anh (H2) |

Boot guard sẽ **từ chối khởi động** nếu còn bất kỳ giá trị mặc định nào — đây
là lưới an toàn, không phải lỗi.

## 2. Curation trước khi activate (đã có worklist)

`TIP-013B_CURATION_WORKLIST.md` liệt kê 41 fact `curate` hữu hạn. Ba nhóm:

- **32 `l3_facts.kernel_refs`** thiếu provenance → resolve mỗi cái theo `kernel_ref` của nó.
- **3 fact drift đơn vị lb/kg** (specs) → sửa đơn vị, tự động lên `strict`.
- **3 flag + 3 derived thiếu source** → gắn nguồn/quyết định provenance.

180 fact `claim` là quyết định promotion riêng (không phải lỗi) — anh chọn cái
nào nâng thành fact công ty qua cổng graduation.

Agent hỗ trợ được phần cơ học của curation (đọc kernel read-only, đề xuất sửa,
vẫn dry-run tới khi sạch) — chỉ cần anh yêu cầu.

## 3. Trình tự activate (turnkey)

```bash
cd v2
# (a) nạp secret thật
cp .env.example .env.production   # rồi điền mọi [MUST-CHANGE] ở mục 1
set -a; . ./.env.production; set +a

# (b) dựng lại package từ kernel THẬT (không phải snapshot) sau khi curate
python eval/migrate/run_migration.py \
    --kernel-root /đường/dẫn/tới/kernel/registry \
    --out /tmp/curated-packages --report-json /tmp/curated.json
#   → xem lại readiness; lặp curation tới khi số ready đạt mong muốn

# (c) DRY-RUN qua cổng trên manifest đã curate (mặc định, chưa activate)
scripts/onboard-batch.sh --manifest /tmp/curated-manifest.json
#   → phải thấy status=validated, activated_count=0, mọi item planned_valid

# (d) ACTIVATE THẬT — chỉ khi (c) sạch, dưới curator đã xác thực
scripts/onboard-batch.sh --manifest /tmp/curated-manifest.json \
    --apply --approve --report /tmp/ledger.json
```

**Lưới an toàn có sẵn** (đã chứng minh ở Phase A): two-phase fail-closed (một
item lỗi → cả batch bị chặn, zero partial activation); attestation phải do
curator thật ký bằng `SOT_SIGNING_SECRET`; guard `claim_masquerades` chặn claim
giả làm fact verified; idempotent; mọi bước audit. Reindex outbox đưa fact vào
RAG sau khi activate.

## 4. Sau activate

- Chạy lại `make parity` (embedding + provider thật) so V1 oracle trên 137/162
  record thật → tiêu chí go/no-go AC-B2.
- Chạy lại `make eval` trên corpus thật → AC-B3 (leak vẫn phải = 0).
- Câu trả lời dựa trên fact `soft` sẽ tự hiện dòng caveat "cần kiểm chứng lại"
  (TIP-013B Part B) — đúng ý anh: chỉ ở câu chưa đủ căn cứ chặt.
- Chạy lại drill hardened (RPO/RTO, rollback) trên deployment thật → AC-B4.
- Mở pilot theo nhóm quyền, thu 5 chỉ số → AC-B5.
- Ký `TIP-013_GO_NO_GO.md` → AC-B6.

## 5. Điều agent sẽ / sẽ không làm

- **Sẽ:** hỗ trợ curation cơ học (dry-run), dựng manifest, chạy dry-run kiểm tra,
  giải thích mọi finding, chuẩn bị mọi thứ tới sát bước `--apply`.
- **Sẽ không:** chạy `--apply`, nhập secret/cert/OIDC thật thay anh, hay ký
  go/no-go. Launch authority là anh.

*Khi anh gửi các giá trị mục 1 (hoặc nói "curate tiếp"), tôi đi bước kế.*
