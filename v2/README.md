# RtR Copilot V2 · Production Platform Foundation

Đây là scaffold M1, chưa có dữ liệu và chưa giả lập Ask, Files hoặc Documents. V2
chạy song song; `phase1_pilot`, kernel và GOI packs không được mount hoặc sửa.

## Prerequisites

- Docker Desktop/Engine có Compose
- Node.js 22+ và Corepack/pnpm 11
- Python 3.12 và `uv`
- `curl`, tối thiểu 8 GB RAM trống cho Docker

## Start

```bash
cp .env.example .env
# đổi toàn bộ giá trị change-this-*
make dev
```

`make dev` build và khởi động bảy service, chờ tối đa 120 giây và chạy idempotent.

- Web: http://127.0.0.1:3000
- API/OpenAPI: http://127.0.0.1:8000/docs
- MinIO console tùy chọn: http://127.0.0.1:9001
- PostgreSQL, Redis và MinIO API chỉ tồn tại trong private Compose network.

## Service map và health

| Service | Vai trò | Ready |
|---|---|---|
| postgres | persistence foundation | `pg_isready` |
| redis | queue/cache | `PING` |
| minio | private object storage | MinIO live probe |
| minio-init | tạo private bucket idempotent | exit 0 |
| api | typed FastAPI boundary | `/health/ready` |
| worker | heartbeat + `system.ping` | Redis heartbeat |
| web | honest foundation UI | `/api/status` phản ánh API ready |

`/health/live` chỉ phản ánh process. `/health/ready` probe PostgreSQL, Redis và bucket
MinIO; dependency lỗi trả 503 nhưng không lộ endpoint hay secret. Mọi API response có
`X-Request-ID`, cùng ID xuất hiện trong structured log.

## Verify, stop và persistence

```bash
make verify
make ps
make logs
make down
make dev       # named volumes vẫn còn
make clean     # không xóa volumes
make reset     # destructive, bắt buộc gõ RESET-V2
```

Frozen installs không được đổi lockfile:

```bash
pnpm install --frozen-lockfile
cd apps/backend && uv sync --frozen
```

## Failure drills

1. `docker compose stop redis`: API live vẫn 200, ready/web thành 503; `docker compose
   start redis` thì tự phục hồi.
2. Làm tương tự với `postgres`.
3. `docker compose stop minio`: live vẫn 200, ready/web thành 503; khởi động lại để
   hồi phục, không rebuild.

Không chạy `make reset` để chữa readiness; reset xóa dữ liệu local.

## Configuration rules

`.env.example` là danh mục đầy đủ biến bắt buộc. API và worker validate URL/schema
trước khi serve; lỗi chỉ nêu key, không in giá trị secret. Không commit `.env`.

## Boundary với TIP sau

- TIP-003 thêm OIDC và policy; scaffold này không có user giả.
- TIP-004 thêm business schema, object metadata và durable audit.
- Không mount KnowledgeBase, kernel, home directory, credential file hoặc Docker socket.
