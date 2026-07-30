# TIP-005 · Ingestion & Renditions

## HEADER

- **TIP-ID:** TIP-005
- **Project:** RtR Copilot V2
- **Module:** `v2/apps/backend` + `v2/apps/worker` + ingestion toolchain trong `v2/`
- **Depends on:** TIP-003 VERIFIED; TIP-004 VERIFIED
- **Priority:** P0
- **Status:** VERIFIED · READY

## CONTEXT

- Working directory: `/Users/os/RtR/KnowledgeBase/RtR_Copilot`
- Blueprint: `vibecode_v2/02_BLUEPRINT_RTR_COPILOT_V2.md`
- Task Graph: `vibecode_v2/03_TASK_GRAPH.md`
- Identity/policy contract: `vibecode_v2/TIP-003_IDENTITY_POLICY.md`
- Data/object/audit contract:
  `vibecode_v2/TIP-004_DATA_OBJECT_AUDIT_FOUNDATION.md`
- V2 dùng FastAPI, PostgreSQL, Redis worker và S3-compatible object storage.
- TIP-004 đã định nghĩa immutable object blob, document/version, rendition metadata,
  resource projection, ACL, audit và consistency giữa PostgreSQL với object storage.
- Blueprint yêu cầu file gốc bất biến; mọi rendition, text, OCR và transcript phải
  trỏ về đúng checksum/version nguồn.
- TIP này hoàn thành backend ingestion/rendition foundation và viewer-facing
  contract. Files UI/viewer thực tế thuộc TIP-008.

### Ranh giới với TIP-003 và TIP-004

1. TIP-003 policy engine vẫn là nơi duy nhất quyết định allow/deny. Handler, worker,
   object repository và rendition service không tự suy quyền từ owner, filename,
   email hoặc role name.
2. Upload chỉ bắt đầu khi subject được allow action `upload` trên parent
   source/workspace context. `view`, `download` và `render` được kiểm độc lập.
3. TIP-004 tiếp tục sở hữu identity, resource, ACL, immutable object/version và
   append-only audit invariants. TIP này chỉ thêm migration additive cần cho job,
   pipeline metadata và constraints của rendition.
4. File đang `quarantined` không bao giờ được trả bytes, presign URL, extracted text
   hoặc preview cho client. Người upload chỉ được xem trạng thái đã sanitize nếu
   policy cho phép.
5. Rendition là resource riêng nhưng kế thừa security attributes và effective ACL
   từ document version nguồn. Không tạo đường bypass bằng ACL riêng lỏng hơn.
6. TIP này chưa tạo `records`, `record_versions`, `evidence_spans`, `chunks`, vector
   index nghiệp vụ hoặc publish SOT. Các output extraction chỉ là artifact có
   locator; TIP-006/007 chịu trách nhiệm diễn giải, publish và index.
7. Không build Files UI, PDF.js screen, spreadsheet grid, media player hoặc Evidence
   Rail trong TIP này. TIP-008 chỉ được dùng contract đã kiểm thử ở đây.

## TASK

### 1. Pipeline tổng thể và state machine

Implement pipeline fail-closed:

```text
authorize upload
  → stream vào quarantine key
  → server-side size + SHA-256
  → sniff magic bytes / structural validation
  → archive safety checks
  → malware scan
  → create immutable document version
  → enqueue idempotent extraction/render jobs
  → extract/OCR/transcribe/render trong sandbox
  → verify output checksum + manifest
  → publish rendition metadata atomically
  → viewer manifest available theo policy
```

Upload state tối thiểu:

```text
receiving → quarantined → validating → scanning → accepted
          ↘ rejected
          ↘ failed
```

Ingestion job state tối thiểu:

```text
pending → leased → running → succeeded
                   ├──────→ retry_wait → pending
                   ├──────→ failed
                   └──────→ quarantined
```

Rules:

- Chỉ `accepted` object đã HEAD/checksum verify mới được nối vào document version.
- Version chỉ chuyển sang lifecycle có thể xem sau khi malware scan sạch và toàn bộ
  validation bắt buộc pass.
- Rendition độc lập có thể `pending`, `ready`, `failed` hoặc `quarantined`; failure
  của một optional rendition không làm original sạch trở thành malware.
- Required preview failure giữ file ở trạng thái rõ `processing_failed`; không trả
  fallback bytes nguy hiểm dưới nhãn preview.
- Mọi state transition dùng compare-and-set hoặc row lock, có timestamp, reason code,
  request/job ID và audit event.
- Retry không được tạo version, blob hoặc rendition duplicate.

### 2. Upload quarantine

#### API contract

Các endpoint tối thiểu:

- `POST /api/v1/files/uploads`
  - multipart hoặc streaming request body qua backend;
  - nhận parent context, logical name, optional declared MIME/checksum;
  - trả `202` với `upload_id`, `job_id`, trạng thái và status URL;
  - không trả object-store key hoặc quarantine URL.
- `GET /api/v1/files/uploads/{upload_id}`
  - trả state/progress/sanitized error/created resource IDs khi hoàn tất;
  - policy-check resource/parent trước khi trả.
- `POST /api/v1/files/uploads/{upload_id}/retry`
  - chỉ cho retry lỗi retryable và phải idempotent;
  - malware/rejected validation không retry nếu input không đổi.
- `GET /api/v1/files/versions/{version_id}/viewer-manifest`
  - contract cho TIP-008, chỉ trả rendition `ready` được phép.
- `GET /api/v1/files/renditions/{rendition_id}/content`
  - authorization ở thời điểm request;
  - stream hoặc short-lived capability/presign;
  - không expose bucket/key/path nội bộ.

OpenAPI phải typed, có machine-readable error code và request ID. Không giữ toàn bộ
upload trong RAM.

#### Quarantine invariants

- Mọi byte mới đi vào bucket/prefix quarantine private, key sinh từ UUID.
- Quarantine bucket/prefix không có public access, client presign hoặc CDN route.
- Original filename chỉ là metadata hiển thị sau normalize Unicode; không tham gia
  filesystem path, command, object key hoặc authorization.
- SHA-256 và byte count được tính server-side khi stream. Declared checksum hoặc
  `Content-Length` sai bị từ chối.
- Upload đứt quãng không tạo active version; staged bytes được reconciliation nhận
  diện và dọn theo retention cấu hình.
- Tên rỗng, control character, NUL, bidi-control nguy hiểm, path separator và tên quá
  dài phải normalize hoặc reject theo code xác định.
- Log/audit không chứa raw bytes, full original path, signed URL hoặc secret.

### 3. Content detection và validation

Không tin file extension, browser MIME hoặc multipart `Content-Type`.

Server phải:

1. Sniff magic bytes bằng thư viện maintained.
2. Kiểm cấu trúc định dạng với parser phù hợp trong sandbox.
3. So declared MIME, filename extension và detected MIME.
4. Chọn pipeline chỉ từ detected type + structural result.
5. Reject unknown, ambiguous hoặc polyglot đáng ngờ; mismatch không được âm thầm
   đổi pipeline.

Allowlist định dạng:

- image: PNG, JPEG, WebP, TIFF;
- document: PDF, DOCX;
- spreadsheet: XLSX;
- presentation: PPTX;
- video: MP4, WebM;
- audio/voice: MP3, M4A/AAC, WAV, OGG/Opus.

Không chấp nhận executable, script, HTML/SVG active content, arbitrary archive,
legacy binary Office hoặc macro-enabled Office trong TIP này. Muốn mở thêm định
dạng là L2 security change kèm hostile fixtures mới.

Giới hạn đều cấu hình server-side theo type:

- request bytes và actual streamed bytes;
- image pixel count/dimensions;
- PDF pages và object count;
- Office archive entry count, expanded bytes, compression ratio và nesting;
- sheet/row/column/cell count;
- slide count;
- media duration, resolution, frame/sample rate và decoded output budget;
- parser/render/transcode wall time, CPU, memory và temporary disk.

Khi chưa có business limit production, Builder dùng conservative documented default
và config validation; không dùng “unlimited”.

### 4. ZIP/package, parser và malware safety

DOCX/XLSX/PPTX là ZIP-based packages nên chỉ được mở bởi safe package inspector:

- từ chối absolute path, drive prefix, `..`, mixed separator traversal, NUL,
  symlink/hardlink và duplicate/conflicting entry;
- canonicalize target và chứng minh mọi entry nằm trong per-job temp directory;
- cấm nested archive ngoài cấu trúc OOXML được allow;
- enforce entry count, per-entry size, total expanded bytes, compression ratio và
  cumulative extraction budget trước và trong lúc giải nén;
- validate OOXML content types/required parts;
- không execute macro, formula, embedded executable, OLE object, external
  relationship, remote image/font hoặc data connection;
- không truy cập network khi parse/render.

Malware scanning đi qua adapter, mặc định dùng scanner self-hosted trong private
network:

- signature/database age có health check và metric;
- scanner unavailable, timeout hoặc malformed response là fail-closed;
- infected/suspicious result giữ object quarantined và không enqueue render;
- scan result lưu engine/version/signature version/timestamp/result code, không lưu
  raw scanner dump cho client;
- EICAR test fixture chỉ tồn tại trong test fixture/encoded generation path được
  scanner test nhận diện; không phát tán vào artifact production.

Parser/renderer/transcoder chạy bằng process/container không đặc quyền:

- non-root, read-only root filesystem khi khả thi;
- network disabled;
- per-job temp directory;
- resource/time limits;
- command arguments truyền bằng structured argv, không shell interpolation;
- kill toàn process group khi timeout;
- temp cleanup cả success, failure và worker crash.

### 5. Persistent jobs và idempotency

Thêm migration additive cho `ingestion_jobs` và metadata cần thiết. Shape tối thiểu:

#### `ingestion_jobs`

- `job_id uuid PRIMARY KEY`
- `version_id uuid REFERENCES document_versions`
- `job_type text`: `validate`, `extract`, `ocr`, `transcribe`, `render`
- `pipeline_version text NOT NULL`
- `idempotency_key text UNIQUE NOT NULL`
- `status text`: `pending`, `leased`, `running`, `retry_wait`, `succeeded`,
  `failed`, `quarantined`, `cancelled`
- `attempt integer`, `max_attempts integer`
- `lease_owner`, `lease_expires_at`, `heartbeat_at`
- `next_attempt_at`
- `requested_by uuid`, `request_id`
- `input_sha256 char(64)`
- `progress smallint CHECK (progress BETWEEN 0 AND 100)`
- `error_code`, `error_fingerprint`
- `created_at`, `started_at`, `finished_at`, `updated_at`

Không lưu raw exception, tool stdout/stderr, local path hoặc secret trong
`ingestion_jobs`.

Rendition metadata được mở rộng additive nếu contract TIP-004 chưa đủ:

- `pipeline_fingerprint`
- `source_sha256`
- `manifest_object_id`
- `quality_state`: `complete`, `partial`, `low_confidence`
- `quality_summary jsonb`

Unique constraint phải ngăn hai output cùng:

```text
(version_id, kind, pipeline_fingerprint)
```

Redis chỉ vận chuyển at-least-once; PostgreSQL là source of truth cho job state.
Enqueue phải dùng transactional outbox hoặc cơ chế tương đương chứng minh được rằng
DB commit/worker delivery không làm mất job. Worker:

- claim bằng atomic lease;
- heartbeat và reclaim lease hết hạn;
- retry bounded với exponential backoff + jitter;
- phân loại retryable/permanent/quarantine;
- kiểm input checksum trước mỗi attempt;
- commit output blob/rendition theo idempotency key;
- acknowledge delivery chỉ sau durable state;
- không overwrite rendition `ready`;
- worker crash ở mọi điểm đều recover không tạo duplicate visible output.

Cancel chỉ best-effort cho job đang chạy; không xóa original/version/audit.

### 6. Extraction, OCR và transcript

Mọi extraction output phải là immutable object có SHA-256 và một rendition record.
Payload text/JSON dùng schema versioned, UTF-8, deterministic khi cùng input,
pipeline version và config.

#### Native extraction

- PDF: text theo page, reading-order indicator, page dimensions và character count.
- DOCX: paragraph/table/header/footer/footnote text cùng stable structural locator.
- XLSX: workbook/sheet names, visible cell values, formula text riêng khỏi cached
  value, row/column coordinates và merged-range metadata.
- PPTX: text theo slide/shape/note, slide number và reading-order indicator.
- Image: metadata an toàn; không coi EXIF text là verified content.
- Audio/video: container/codec/duration metadata bằng probe an toàn.

Không evaluate spreadsheet formula, macro, embedded script hoặc external link.

#### OCR

- OCR chạy cho image và page/slide không có đủ native text theo heuristic cấu hình.
- Output giữ page/region/bounding box, language, text, per-region confidence và
  aggregate confidence.
- Coordinate system, rotation và page dimensions phải được khai báo trong manifest.
- Không silently trộn OCR với native text; mỗi segment có origin `native` hoặc `ocr`.
- Language packs là config/dependency locked; thiếu language trả warning/error rõ.

#### Transcript

- Audio, voice và video tạo transcript JSON + WebVTT khi provider hỗ trợ.
- Segment giữ start/end milliseconds, text, confidence khi có và speaker label chỉ
  khi thực sự được suy ra; không bịa speaker name.
- Provider đi qua adapter, không hard-code vendor. Nếu dùng external provider sau
  này phải có L3 approval cho data egress, DPA/region và classification policy.
- Default private deployment không gửi bytes ra Internet.

### 7. Rendition matrix

Mỗi output có manifest, source checksum, output checksum, generator/version,
pipeline fingerprint, created timestamp, quality và warnings.

| Input | Required preview outputs | Optional/conditional outputs | Deep locator |
|---|---|---|---|
| PNG/JPEG/WebP/TIFF | normalized safe preview + thumbnail | OCR JSON/text | image region/bounding box |
| PDF | sanitized preview PDF hoặc page raster set + thumbnails; page text JSON | OCR cho scanned pages | page + bounding box |
| DOCX | PDF preview + page thumbnails + structured text JSON | OCR embedded/scanned pages | page/paragraph/table locator |
| XLSX | workbook manifest + bounded safe sheet JSON/HTML preview | PDF snapshot + thumbnails | sheet + cell/range |
| PPTX | PDF preview + slide images/thumbnails + structured text JSON | OCR image-only slides | slide + shape/region |
| MP4/WebM | normalized browser-safe MP4 hoặc HLS package + poster | transcript JSON/WebVTT + waveform | millisecond time range/frame |
| MP3/M4A/WAV/OGG | normalized browser-safe audio + waveform | transcript JSON/WebVTT | millisecond time range |

Rules:

- Original không bị biến đổi hoặc overwrite.
- Preview không mang macro, script, external link, embedded file hoặc active content.
- Image metadata nhạy cảm không copy sang normalized preview mặc định.
- XLSX preview chỉ render bounded ranges; truncation phải hiện trong manifest, không
  giả vờ workbook đã hiển thị toàn bộ.
- PDF/Office page geometry có mapping đủ để TIP-008 highlight locator.
- Video/audio transcode giữ duration mapping; drift vượt tolerance cấu hình làm
  rendition fail hoặc warning định lượng.
- Thumbnail/poster/waveform không được thay thế artifact text/transcript.
- Optional output fail không được ghi `ready`; viewer manifest vẫn nêu capability
  unavailable bằng sanitized reason code.

### 8. Viewer manifest contract, chưa build UI

`GET /api/v1/files/versions/{version_id}/viewer-manifest` trả schema versioned:

```json
{
  "schema_version": 1,
  "version_id": "uuid",
  "source_sha256": "hex",
  "detected_mime": "application/pdf",
  "viewer_kind": "pdf",
  "state": "ready",
  "capabilities": {
    "preview": true,
    "text": true,
    "search_within_file": true,
    "deep_link": true,
    "download_original": false
  },
  "renditions": [
    {
      "rendition_id": "uuid",
      "kind": "preview_pdf",
      "mime_type": "application/pdf",
      "byte_size": 123,
      "sha256": "hex",
      "quality_state": "complete",
      "content_url": "/api/v1/files/renditions/uuid/content"
    }
  ],
  "locator_schema": "rtr.locator.v1",
  "quality": {},
  "warnings": []
}
```

Contract rules:

- Response không có bucket, object key, filesystem path, scanner detail, stack trace
  hoặc unauthorized rendition.
- `content_url` là application endpoint hoặc capability ngắn hạn, không phải durable
  public URL.
- Download original là capability riêng từ policy action `download`; quyền preview
  không suy ra quyền download.
- `search_within_file` chỉ phản ánh extracted text sẵn có; chưa gọi hybrid RAG.
- Locator schema hỗ trợ `page`, `sheet/cell/range`, `slide/shape`,
  `time_start_ms/time_end_ms`, `image_region`.
- ETag/cache key của manifest gắn với version/checksum/policy context; `private,
  no-store` cho nội dung restricted nếu chưa có cache policy an toàn.
- Quarantined/deleted/unknown resource trả typed deny/not-ready, không trả manifest
  chứa metadata nhạy cảm.

TIP-008 có thể dùng fixture manifests để build UI nhưng không được bypass endpoint
authorization hoặc tự dựng object-store URL.

### 9. Provenance, quality và sanitized errors

Mỗi rendition manifest phải có:

- source `version_id`, `object_id`, SHA-256 và detected MIME;
- output `rendition_id`, `object_id`, SHA-256, byte size và MIME;
- generator name/version, pipeline version/config fingerprint;
- created timestamp, job ID và attempt;
- extraction/OCR/transcript origin;
- locator schema/version;
- quality metrics, warnings, truncation/partial flags;
- upstream rendition IDs nếu output sinh từ output khác.

Provenance này mô tả kỹ thuật tạo artifact, chưa phải SOT evidence hay fact approval.

Quality tối thiểu:

- extracted unit count so với expected page/sheet/slide/duration;
- native/OCR coverage;
- OCR/transcript confidence khi engine cung cấp;
- failed/skipped/truncated units;
- media duration drift;
- warning codes theo allowlist.

Không biến “pipeline chạy xong” thành “nội dung đáng tin”. Low confidence và partial
phải machine-readable; TIP-006/007 được phép chặn publish/index dựa trên quality.

Client-facing error chỉ gồm:

- stable `error_code`;
- retryable boolean;
- user-safe message;
- request/job ID;
- optional failed stage.

Raw exception, subprocess command, stdout/stderr, host path, object key, presign URL,
secret, token, file content và malware signature detail chỉ ở restricted operational
telemetry sau redaction. Unknown exception map thành generic code; cùng lỗi có
fingerprint phục vụ điều tra mà không lộ payload.

### 10. Audit và observability

Audit event tối thiểu:

- upload requested/completed/rejected/failed;
- detected-type mismatch;
- malware clean/infected/scanner failure;
- ingestion job create/claim/retry/succeed/fail/quarantine/cancel;
- rendition create/ready/fail;
- viewer manifest allow/deny;
- rendition/original content allow/deny;
- reconciliation/cleanup action.

Event dùng actor user/service phù hợp, request/job/resource ID và reason code; không
ghi raw file text hoặc secrets. Privileged state transition và audit commit cùng
Unit of Work khi đều ở PostgreSQL; external object/scanner/tool action dùng correlated
start/success/failure events như TIP-004.

Metrics tối thiểu:

- upload bytes/count/rejection theo reason và detected type;
- quarantine age/depth;
- scanner health/signature age/duration;
- queue depth, lease expiry, retry/dead-letter;
- stage latency và success/failure;
- rendition throughput/size;
- OCR/transcript quality distribution;
- orphan/staged object count.

Không dùng filename, email hoặc extracted content làm metric label.

### 11. Hostile fixture suite

Commit fixture generators hoặc tiny safe fixtures; không commit dữ liệu công ty.
Suite tối thiểu:

- extension/MIME mismatch và double extension;
- executable đổi tên thành PDF/image;
- truncated/corrupt header và malformed parser input;
- polyglot/suspicious multi-format sample;
- declared size/checksum mismatch và streaming oversize;
- decompression bomb mô phỏng, extreme ratio, quá nhiều entries, nested archive;
- ZIP traversal với `../`, absolute path, Windows drive/backslash, NUL, symlink và
  duplicate canonical path;
- OOXML có macro/OLE/external relationship/remote resource;
- PDF active action/embedded file/external reference;
- SVG/HTML/script upload;
- image pixel bomb/invalid dimensions;
- media duration/resolution/codec vượt limit và malformed container;
- parser/render/transcode timeout, memory/disk exhaustion mô phỏng;
- scanner unavailable/timeout/stale signature/malformed response;
- EICAR scanner fixture;
- worker duplicate delivery, crash trước/sau blob upload, lease expiry và retry race;
- unauthorized manifest/content/download; admin non-bypass;
- error/log payload chứa token/path/object key để chứng minh redaction.

Mọi hostile case phải có expected machine-readable result và chứng minh không có
active version/rendition, path escape, network call, public object hoặc unsanitized
client error.

## CONFIGURABLE OPERATIONAL DECISIONS

Các giá trị sau phải có conservative defaults cho development/test và cấu hình
server-side; Human/Operator chốt trước production:

- per-format upload, page/cell/slide/duration/pixel và expansion limits;
- accepted OCR languages;
- malware signature maximum age;
- retry count/backoff/dead-letter retention;
- quarantine/orphan retention và infected-sample destruction workflow;
- allowed media codecs và output quality profiles;
- external transcription/OCR provider, data residency và egress policy;
- restricted-content cache/presign TTL.

Các quyết định này không chặn việc xây schema/job/security foundation. Không có giá
trị production thì hệ thống dùng preservation + fail-closed: không unlimited, không
external egress, không auto-release quarantine và không physical delete ngoài policy
đã duyệt.

## ACCEPTANCE CRITERIA

### AC-005.1 · Authorized streaming quarantine

**Given** subject được/không được phép upload vào parent resource
**When** stream file hợp lệ, file quá giới hạn hoặc request bị ngắt
**Then** chỉ subject được phép nhận `202`; bytes đi vào private quarantine bằng UUID,
SHA-256/size tính server-side; oversize dừng sớm; interruption không tạo active
version; response/log không lộ storage key.

### AC-005.2 · Magic-byte allowlist

**Given** toàn bộ allowlist và mismatch/unknown/polyglot fixtures
**When** upload với extension và client MIME tùy ý
**Then** pipeline chọn từ magic-byte + structural validation; đúng type được nhận,
mismatch/unknown/suspicious bị reject bằng stable code; executable/script không được
parse như tài liệu.

### AC-005.3 · Archive and OOXML safety

**Given** valid OOXML cùng zip-bomb, traversal, absolute path, mixed separator,
symlink, duplicate path, nested archive, macro/OLE/external-link fixtures
**When** package validation chạy
**Then** valid package pass; mọi hostile fixture fail trước unsafe extraction, không
file nào thoát temp root, không network call và resource budget không bị vượt.

### AC-005.4 · Malware fail-closed

**Given** clean, EICAR, scanner timeout/unavailable/stale/malformed fixtures
**When** scan chạy
**Then** chỉ clean input được accepted; infected/suspicious ở quarantine; mọi scanner
failure fail-closed; không enqueue render hoặc phát capability; audit/metric ghi
reason đã sanitize.

### AC-005.5 · Immutable accepted version

**Given** upload sạch đã verify
**When** finalize
**Then** blob SHA-256/size/MIME khớp phép tính độc lập, document version/resource
được tạo transactionally, original không đổi; injected DB/S3 failure không để broken
active version và reconciliation thấy orphan/staged state.

### AC-005.6 · Persistent idempotent delivery

**Given** duplicate Redis delivery, concurrent worker, lease expiry và worker crash
ở từng failure point
**When** cùng idempotency key được xử lý lại
**Then** có đúng một logical successful job và tối đa một visible rendition cho mỗi
pipeline fingerprint; không mất job sau DB commit; retry/reclaim tiến triển tới
terminal state mà không overwrite output ready.

### AC-005.7 · Retry and terminal semantics

**Given** retryable tool timeout và permanent malformed input
**When** worker xử lý
**Then** timeout retry bounded với backoff/jitter rồi success hoặc failed; permanent
input không loop; progress/state transition hợp lệ; retry API không nhân job và
malware input không retry khi checksum không đổi.

### AC-005.8 · Extraction fidelity

**Given** golden PDF/DOCX/XLSX/PPTX fixtures có expected text/structure
**When** native extraction chạy hai lần với cùng pipeline fingerprint
**Then** output schema/checksum deterministic; page/paragraph/table/sheet-cell/
slide-shape locators đúng; formula không được evaluate; external content không tải;
coverage và truncation được báo định lượng.

### AC-005.9 · OCR provenance and quality

**Given** scanned image/PDF nhiều rotation và language fixture
**When** OCR chạy
**Then** segment có origin, page/region/bounding box, coordinate system, language và
confidence; native/OCR không bị trộn mơ hồ; thiếu language/low confidence tạo
machine-readable warning thay vì giả thành complete.

### AC-005.10 · Transcript and media safety

**Given** golden audio/voice/video và malformed/oversize/timeout fixtures
**When** probe, transcode và transcription chạy
**Then** browser-safe output, poster/waveform và transcript/WebVTT theo matrix; segment
timecode nằm trong duration tolerance; không bịa speaker; resource limit kill toàn
process group; default không có Internet egress.

### AC-005.11 · Supported rendition matrix

**Given** ít nhất một golden fixture cho từng supported input type
**When** pipeline hoàn tất
**Then** 100% required outputs trong matrix có object checksum, rendition ready và
manifest; active content/metadata nhạy cảm không mang sang preview; optional failure
được biểu diễn rõ, không giả ready.

### AC-005.12 · ACL inheritance and non-bypass

**Given** staff/leader/curator/admin, owner/non-owner, classification, explicit deny,
expired entitlement và quarantined/deleted states
**When** lấy upload status, viewer manifest, rendition content hoặc original download
**Then** policy result giống TIP-003 PostgreSQL contract; rendition không rộng quyền
hơn version nguồn; admin không bypass; quyền preview không suy ra download; deny
không lộ sự tồn tại/metadata ngoài contract.

### AC-005.13 · Viewer manifest contract

**Given** ready, partial, processing, failed, quarantined và unsupported fixtures
**When** gọi viewer-manifest
**Then** response khớp schema/OpenAPI, capability và locator đúng format; chỉ rendition
authorized/ready xuất hiện; không có bucket/key/path/stack; content endpoint
re-authorize và capability hết hạn không dùng lại được.

### AC-005.14 · Provenance and quality completeness

**Given** mọi successful rendition
**When** kiểm manifest và database
**Then** 100% có source/output checksum, immutable IDs, generator/pipeline/config
fingerprint, job/attempt, locator schema và quality fields; upstream chain truy được
về original version; partial/low-confidence không được nâng thành complete.

### AC-005.15 · Sanitized errors and audit

**Given** hostile filenames, parser stderr, secrets, local paths, object keys và raw
file text được inject vào failure
**When** đọc API, database job, application log và audit
**Then** client/job/audit chỉ có allowlisted code/fingerprint/request ID; zero secret,
presign, raw content hoặc host path; required lifecycle/security events đủ actor,
resource, action, result và correlation.

### AC-005.16 · Sandbox and cleanup

**Given** renderer cố network, fork child, ghi ngoài temp root, chạy quá CPU/time/disk
và worker bị kill
**When** sandbox tests chạy
**Then** network/path escape/privilege bị chặn, process group bị dừng, temp artifacts
được cleanup hoặc reconciliation liệt kê; worker/API không chạy tool bằng shell
interpolation.

### AC-005.17 · Restart and reconciliation

**Given** pending/running/retry jobs, staged outputs và ready renditions
**When** restart Redis, worker, API và object storage theo failure matrix
**Then** durable job state không mất; expired lease được reclaim; ready artifact giữ
checksum; staged/orphan report chính xác; repair/delete cần explicit mode và audit.

### AC-005.18 · Technical and boundary health

**Given** implementation hoàn tất
**When** chạy full verify
**Then** migration fresh/upgrade/downgrade, Ruff, mypy, pytest unit/integration,
OpenAPI contract, dependency/container scan, Docker build và Compose health đều pass
với count cụ thể; hostile matrix 100% expected result; TIP-003 policy regressions và
TIP-004 object/audit regressions không fail; không có Files UI, SOT record, evidence,
chunk/index, company data, secret hoặc generated quarantine artifact được commit.

## CONSTRAINTS

- Không sửa public identity/policy contract TIP-003 hoặc object/audit invariants
  TIP-004 nếu chưa L2 approval.
- Không tin extension, client MIME, filename, Content-Length, ETag hoặc client
  checksum như nguồn sự thật.
- Không expose quarantined bytes hoặc presigned URL cho client.
- Không chạy parser/Office/FFmpeg/OCR bằng shell command ghép chuỗi hoặc có network.
- Không execute macro, formula, script, embedded binary hoặc external relationship.
- Không dùng OCR/transcript/extracted text như verified SOT fact.
- Không tạo record/evidence/chunk/vector index/publish gate sớm.
- Không build Files UI/viewer trong TIP này.
- Không gửi file ra external AI/OCR/transcription provider nếu chưa L3 approval.
- Không hard-code limits, retention, codec, provider hoặc language trong handler.
- Không deduplicate checksum xuyên trust zone và không leak file-existence side
  channel.
- Không chạm legacy pilot, kernel, GOI packs hoặc KnowledgeBase source data.

## MINIMUM VERIFY EVIDENCE

- Migration history/current và fresh + downgrade/upgrade logs.
- OpenAPI upload/status/retry/viewer/content schemas.
- Supported-format matrix: input count, required/optional output count và checksum.
- Magic-byte/structural mismatch results.
- Hostile archive/OOXML/PDF/image/media fixture matrix với expected/actual code.
- Malware scanner clean/EICAR/unavailable/stale/timeout evidence.
- Sandbox network/path/resource-limit probes và temp cleanup inventory.
- Duplicate delivery/crash-point/lease/retry tests với logical/output row counts.
- Golden extraction/OCR/transcript locator and quality comparisons.
- TIP-003 ACL matrix parity, admin non-bypass và preview-vs-download probes.
- Provenance completeness query và source-to-output checksum chain.
- Error/log/audit forbidden-field/value scans.
- Restart/reconciliation results.
- Ruff/mypy/pytest, dependency/container audit, Docker/Compose counts.
- Git diff chứng minh không có UI/SOT/chunk/legacy/kernel/GOI drift.

## ESCALATION

- **L2:** Cần đổi TIP-003 action/resource contract hoặc cách policy engine nhận
  inherited ACL.
- **L2:** Cần đổi immutable object/version/rendition/audit contract TIP-004.
- **L2:** Muốn thêm định dạng, parser, browser-active preview, arbitrary archive,
  macro-enabled Office hoặc cross-zone deduplication.
- **L2:** Job persistence không thể chứng minh atomic delivery/idempotency bằng
  PostgreSQL + Redis contract hiện tại.
- **L3/Human:** Cho phép external OCR/transcription/AI egress, chọn data region/DPA
  hoặc cho classified content rời private runtime.
- **L3/Human:** Chốt production limits, quarantine/infected retention/destruction,
  malware risk acceptance hoặc cho phép format active content.

## REPORT

Builder nộp Completion Report chuẩn Vibecode gồm:

- Files changed.
- 18 AC pass/fail và severity mỗi fail.
- Migration/schema/job transition counts.
- Supported rendition matrix và output checksum counts.
- Hostile fixture + malware + sandbox results.
- Idempotency/crash/retry/restart metrics.
- Extraction/OCR/transcript fidelity, locator và quality results.
- ACL/viewer/download policy matrix.
- Provenance/redaction/audit evidence.
- Issues, deviations và suggestions.

## DECISION LOG

- **L2 · 2026-07-30 · APPROVED:** Implement private offline transcription with Vosk
  and a small model pinned by version, license and SHA-256. The model may be acquired
  at build time or through a repository-safe artifact mechanism, but never fetched at
  runtime. No external egress or company data is permitted. Builder must report image
  footprint and dependency evidence. This implements the already-approved private
  transcript contract; it does not add a new provider or change the architecture.
