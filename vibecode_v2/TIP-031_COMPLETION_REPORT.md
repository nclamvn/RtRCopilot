# TIP-031 · Completion Report

**Ngày:** 11/08/2026

**Kết quả:** IMPLEMENTED · CONDITIONAL PILOT GO

**Phạm vi:** P0 runtime recovery → P1 governance/Documents OS → P2 connector foundation

## Outcome

TIP-031 khôi phục một checkout có kiến trúc tốt nhưng chưa nhất quán thành một baseline
pilot có thể kiểm chứng. Các thay đổi không vá riêng HERA/VEGA hay một prompt: chúng đóng
gate ở build identity, embedding profile, database schema, corpus inventory, governance
activation, document lifecycle và connector contract.

## Những gì đã hoàn thành

### 1. Runtime và dữ liệu pilot

- Capability-safe Ask autoscroll; không crash ở jsdom/browser thiếu API.
- Preflight answer runtime đối chiếu credential, policy, revision, build SHA, provider,
  embedding model và dimension trong DB.
- Configured embedding adapter được dùng cho backfill.
- Pilot environment tách compose project, ports và volumes khỏi development.
- ClamAV healthcheck và fail-loud ingestion được khôi phục.

### 2. Enterprise corpus governance

- Release plan: 5 domain / 17 cases, activation chỉ sau full pass.
- Release run `ca307aa8-1e19-4642-be3e-3d0bdb26dfbe`: 17/17 PASS.
- Inventory snapshot DB-backed với stable digest
  `e14d045079a40f22003a1348358c1c81abdb0d403d2b48a5322309c46bc86274`.
- Snapshot: 219 canonical SOT records; 43 approved documents / 9.046 chunks; 1.928
  research records (1.838 TheSkyWatch); 5 active domains; 73 open gaps.

### 3. Documents OS

- Bổ sung forward repair migration `0014_document_outbox_repair` cho database bị drift
  dù Alembic đã báo head.
- Startup/dependency guard kiểm physical schema thay vì chỉ tin revision string.
- Runtime proof `pilot.factsheet` đã render, approve, issue và revoke; mỗi chuyển trạng
  thái có audit, checksum và immutable identifiers.

### 4. Connector và federation foundation

- Registry schema và validator cho CRM/MRP/HRM/IP.
- Contract bắt buộc read-only, không direct DB, có ACL/ABAC/DLP purpose, deletion,
  freshness, provenance, cursor và cost budget.
- Planner tách company/research/federated, giữ nguyên trust-zone label và cấm research
  tự động thành SOT.
- CRM/MRP/IP contract-ready; HRM blocked; active production connectors = 0.

## Artifacts chính

- `v2/scripts/verify-answer-runtime.sh`
- `v2/scripts/local-demo.sh`
- `v2/scripts/verify-pilot-database.sh`
- `v2/scripts/build-identity.sh`
- `v2/apps/backend/migrations/versions/0014_document_outbox_repair.py`
- `v2/apps/backend/src/rtr_copilot/commands/bootstrap_enterprise_release.py`
- `v2/apps/backend/src/rtr_copilot/commands/snapshot_enterprise_inventory.py`
- `v2/apps/backend/src/rtr_copilot/commands/prove_document_lifecycle.py`
- `v2/apps/backend/src/rtr_copilot/enterprise_corpus/connectors.py`
- `v2/eval/enterprise_corpus/runtime_snapshot.json`
- `v2/eval/enterprise_corpus/connector_readiness.json`
- `v2/eval/document_os/runtime_lifecycle_proof.json`

## Không nằm trong completion claim

- Không connector nào đã được cấu hình endpoint/credential production.
- Chưa xác nhận authoritative HRM repository và owner.
- Chưa chạy lại bounded live LLM tail campaign do chưa có quyền rõ ràng để chuyển
  nội dung nội bộ tới endpoint ngoài trong phiên này.
- `../_to_delete/` là thay đổi có sẵn của Homeowner và không bị can thiệp.

## Handoff tuần tự

1. Cấp quyền cho đúng 5 live tail cases và endpoint đã cấu hình; recertify với budget cap.
2. Dựng `.env.pilot`, chạy pilot DB check và một vòng operator smoke không đụng dev DB.
3. Kích hoạt CRM read-only connector trước; đo freshness/deletion/ACL và cost.
4. Làm tương tự cho MRP, IP; chỉ mở HRM sau khi source/owner được xác nhận.
5. Chỉ sau các bước trên mới cân nhắc default federated Ask hoặc production rollout.
