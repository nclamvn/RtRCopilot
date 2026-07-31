# RtR Copilot V2 · Production Platform Foundation

V2 hiện có nền tảng identity/policy, SOT/RAG và Files workspace đa định dạng. Dữ
liệu công ty không được tự động mount; `phase1_pilot`, kernel và GOI packs không
được sửa hoặc dùng làm fixture.

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

## Canonical SOT publish

TIP-006 chỉ nhận thư mục adapter-package xác định nằm dưới
`SOT_STAGING_ROOT`. Các boundary chính là stage, validate, publish và status tại
`/api/v1/sot/packages`; active records/evidence được đọc qua `/api/v1/sot/records`
và luôn đi qua policy TIP-003.

Production cần `SOT_SIGNING_SECRET` riêng, tối thiểu 32 byte. Nếu API container cần
nhận package bên ngoài thì chỉ bind-mount đúng staging directory ở chế độ read-only.
Không mount KnowledgeBase, toàn bộ home directory, credential file hoặc Docker
socket; live kernel không bao giờ được import hay dùng làm package production.

Probe kernel chỉ-đọc:

```bash
python -m rtr_copilot.commands.sot_kernel_guard \
  --root /Users/os/RtR/kernel --record-key L3F.ENT.002
```

## Files workspace

Người dùng đã đăng nhập mở Files tại web root. Trình duyệt chỉ gọi same-origin
`/api/files`; route này proxy có allowlist sang `/api/v1/files` và không chuyển
object key, token hay internal hostname.

Backend hỗ trợ:

- catalog policy-filtered và cursor có chữ ký: `GET /api/v1/files`;
- đích upload được phép: `GET /api/v1/files/upload-targets`;
- upload stream, status và retry tại `/api/v1/files/uploads`;
- viewer manifest và safe rendition content;
- tải original bằng quyền `download` riêng tại
  `/api/v1/files/versions/{version_id}/original`;
- single byte range cho rendition/original (`200`, `206`, `416`).

Mười bốn input được nhận: PNG/JPEG/WebP/TIFF, PDF, DOCX/XLSX/PPTX, MP4/WebM và
MP3/M4A/WAV/OGG. UI không mở original Office: DOCX/PPTX dùng PDF/text semantic
rendition và luôn cảnh báo bố cục có thể khác; XLSX dùng bounded semantic grid.
Audio/video dùng browser-safe rendition và transcript timecode.

Catalog, manifest, rendition và original đều resolve effective principals
user/group/role/department/project tại thời điểm request. Explicit deny thắng;
quyền xem không suy ra quyền tải. Nội dung trả `private, no-store`, `nosniff` và
không expose bucket/key.
