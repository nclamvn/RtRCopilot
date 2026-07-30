# TIP-002 · Production Platform Scaffold

## HEADER

- **TIP-ID:** TIP-002
- **Project:** RtR Copilot V2
- **Module:** `v2/`
- **Depends on:** TIP-001 verified
- **Priority:** P0
- **Status:** VERIFIED READY · 30/07/2026

## CONTEXT

- Working directory: `/Users/os/RtR/KnowledgeBase/RtR_Copilot`
- Blueprint: `vibecode_v2/02_BLUEPRINT_RTR_COPILOT_V2.md`
- Dựng V2 song song; không sửa `phase1_pilot`, kernel, GOI packs hoặc dữ liệu thật.
- Stack đã approved: Next.js/React/TypeScript strict; FastAPI/Python; PostgreSQL +
  pgvector; S3-compatible MinIO; Redis; Python worker; Docker Compose.
- TIP này chỉ chứng minh runtime, reproducibility, connectivity và health. Identity,
  business schema, ingestion, RAG và product UI thuộc TIP sau.

## TASK

Tạo production scaffold tối thiểu dưới `v2/`:

```text
v2/
├── README.md
├── Makefile
├── .env.example
├── .gitignore
├── compose.yaml
├── package.json
├── pnpm-workspace.yaml
├── pnpm-lock.yaml
├── apps/
│   ├── web/
│   │   ├── package.json
│   │   ├── next.config.ts
│   │   ├── tsconfig.json
│   │   ├── eslint.config.mjs
│   │   └── src/app/
│   └── backend/
│       ├── pyproject.toml
│       ├── uv.lock
│       ├── src/rtr_copilot/
│       │   ├── config.py
│       │   ├── api/main.py
│       │   ├── api/health.py
│       │   ├── infra/dependencies.py
│       │   └── worker/main.py
│       └── tests/
├── infra/docker/
│   ├── web.Dockerfile
│   └── backend.Dockerfile
└── scripts/
    ├── wait-ready.sh
    └── verify-scaffold.sh
```

Compose có bảy service: `postgres`, `redis`, `minio`, `minio-init`, `api`, `worker`,
`web`. Chỉ web/API và MinIO console tùy chọn được bind `127.0.0.1`; database, Redis
và MinIO API không publish ra host.

## HEALTH CONTRACT

- `/health/live`: phản ánh process/event loop, không phụ thuộc external service.
- `/health/ready`: probe PostgreSQL, Redis và bucket MinIO với timeout ngắn.
- Healthy trả 200; thiếu dependency trả 503 nhưng không lộ hostname, username hoặc
  secret.
- Mọi API response có `X-Request-ID`; structured log dùng cùng ID.
- Worker có heartbeat và một test job `system.ping` tất định, không side effect.

## ACCEPTANCE CRITERIA

### AC-002.1 · Boundary

Mọi file mới nằm dưới `v2/`; legacy, kernel và GOI packs không đổi byte; không commit
cache, generated file hoặc secret.

### AC-002.2 · Cold start

Từ checkout sạch và `.env` tạo từ example, `make dev` làm bảy service healthy/init
completed trong 120 giây. Chạy lần hai idempotent.

### AC-002.3 · Locked installs

`pnpm install --frozen-lockfile` và `uv sync --frozen` exit 0, không đổi lockfile.
Image/base được pin version, không dùng `latest`.

### AC-002.4 · Quality

`make verify` đạt web lint/typecheck/build/test và backend Ruff/mypy/pytest; Docker
images build pass. Completion Report ghi số test cụ thể.

### AC-002.5 · Live/ready separation

Khi Redis, PostgreSQL hoặc MinIO lần lượt dừng, API live vẫn 200, ready thành 503
trong 10 giây; web ready phản ánh dependency; khi service trở lại, readiness tự phục
hồi không rebuild.

### AC-002.6 · Configuration

Thiếu biến bắt buộc hoặc URL sai schema làm API/worker fail-fast trước khi serve.
Thông báo chỉ nêu key, không in secret. `.env.example` phủ 100% required variables.

### AC-002.7 · Network containment

Không service nhạy cảm bind `0.0.0.0`; container không mount KnowledgeBase, kernel,
home directory, credential files hoặc Docker socket.

### AC-002.8 · Worker

Worker register/heartbeat pass; `system.ping` trả request/job ID; retry không tạo
side effect. Không thêm business job.

### AC-002.9 · API contract

OpenAPI validate; chỉ có service info, live, ready và ping test contract. Schemas
typed, error machine-readable, request ID hiện diện; không tạo endpoint dữ liệu giả.

### AC-002.10 · Persistence/shutdown

`make down` rồi `make dev` giữ marker test trong named volumes và shutdown sạch.
`make clean` không xóa volume; thao tác reset dữ liệu phải tách riêng và có confirm.

### AC-002.11 · Minimal UI

Web ghi rõ “V2 foundation · chưa có dữ liệu”, hiển thị dependency status, dùng token
nền của Design DNA; responsive smoke 360/1440 px và keyboard focus visible. Không
giả tính năng Ask/Files/Documents.

### AC-002.12 · Onboarding

README có prerequisites, setup, start/verify/stop, URL, service map, health semantics,
ba failure scenarios và boundary với TIP-003/004. Người mới làm đúng README đạt
healthy stack mà không sửa source.

## CONSTRAINTS

- Không tạo package/migration/model nghiệp vụ rỗng để “giữ chỗ”.
- Không dựng reverse proxy production, OIDC, RAG hoặc observability backend đầy đủ.
- Queue implementation dùng Redis và giữ contract worker; muốn đổi framework báo L2.
- Nếu image không hỗ trợ máy build, báo L2 trước khi đổi service family.

## REPORT FORMAT

Completion Report chuẩn Vibecode gồm 12 AC, test counts, `docker compose ps`, fault
injection/recovery time, frozen-lock diff, image versions, ports, mounts, volumes và
proof legacy không đổi.
