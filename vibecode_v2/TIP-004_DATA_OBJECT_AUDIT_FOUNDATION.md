# TIP-004 · Data, Object & Audit Foundation

## HEADER

- **TIP-ID:** TIP-004
- **Project:** RtR Copilot V2
- **Module:** `v2/apps/backend` + hạ tầng dữ liệu trong `v2/`
- **Depends on:** TIP-002 VERIFIED; TIP-003 VERIFIED
- **Priority:** P0
- **Status:** VERIFIED · READY

## CONTEXT

- Working directory: `/Users/os/RtR/KnowledgeBase/RtR_Copilot`
- Blueprint: `vibecode_v2/02_BLUEPRINT_RTR_COPILOT_V2.md`
- V2 foundation đã có FastAPI, PostgreSQL, Redis, MinIO, worker, typed errors,
  request ID và Docker Compose.
- TIP-003 định nghĩa identity/session/policy và dùng repository interfaces với
  in-memory adapter. TIP này cung cấp PostgreSQL adapter cho đúng các interface đó.
- TIP này xây nền persistence, object metadata, resource/ACL projection và audit
  append-only. Không làm ingestion/extraction, SOT publish, RAG hoặc product UI.

### Ranh giới với TIP-003

1. Không sửa OIDC flow, Redis session, cookie, role mapping hoặc policy evaluation.
2. Không đổi public repository interface của TIP-003 để chiều database. Nếu port
   thiếu primitive cần cho transaction, Builder phải báo L2.
3. `(issuer, sub)` là natural uniqueness; `user_id UUID` là identity bất biến.
   Email và display name chỉ là thuộc tính có thể thay đổi.
4. Policy engine quyết allow/deny. Data layer chỉ lưu và trả subject, resource,
   entitlement và ACL attributes.
5. Unknown, deleted hoặc quarantined resource phải dẫn tới default-deny.
6. Audit sink của TIP-003 được thay bằng PostgreSQL append-only adapter, không lưu
   token, cookie, secret hoặc raw OIDC payload.

## TASK

### 1. Database runtime và Alembic

- Thêm SQLAlchemy 2 async, Alembic và asyncpg; pin và khóa dependencies.
- Tách hai database credential:
  - Migration DSN có quyền DDL, chỉ dùng cho Alembic và maintenance.
  - Runtime DSN chỉ có quyền CRUD tối thiểu, không DDL và không được
    `UPDATE`, `DELETE` hoặc `TRUNCATE` audit.
- API/worker không tự chạy migration. Startup chỉ kiểm database revision bằng code
  head; schema lệch làm readiness trả `503 database_schema_outdated`.
- Cung cấp `make migrate`, `make migration-check`, `make db-verify`.
- One-shot Compose service `migrate` được phép nằm trong profile `tools`; không biến
  API thành schema owner.

Các revision tối thiểu:

1. `0001_extensions`: `pgcrypto`, `vector`. Vector chỉ là nền hạ tầng; chưa tạo
   chunks hoặc vector index nghiệp vụ.
2. `0002_identity_persistence`: bảng và adapter theo TIP-003 ports.
3. `0003_resource_object_foundation`: resource projection, ACL, source, object,
   document version và rendition metadata.
4. `0004_append_only_audit`: audit table, indexes, trigger và grants.

Mỗi revision phải có upgrade/downgrade thật, chạy trong transaction; không tạo
migration rỗng hoặc placeholder.

### 2. Quy ước schema

- Mọi business primary key là UUID sinh phía server.
- Mọi timestamp là `timestamptz` UTC.
- Enum nghiệp vụ dùng `text` + `CHECK` ở giai đoạn này để migration an toàn.
- JSONB chỉ dùng cho thuộc tính mở rộng; field cốt lõi phải có cột riêng.
- Filename, URI, email và display name không bao giờ là identity hoặc ownership key.
- Index phải phục vụ policy pre-filter và lookup theo UUID; không tối ưu RAG sớm.

### 3. Identity persistence — storage adapter cho TIP-003

#### `subjects`

- `user_id uuid PRIMARY KEY`
- `issuer text NOT NULL`
- `provider_sub text NOT NULL`
- `email text`
- `canonical_domain text`
- `display_name text`
- `status text CHECK (status IN ('active','disabled','pending'))`
- `created_at`, `updated_at`, `last_seen_at`
- `UNIQUE (issuer, provider_sub)`

Không đặt email hoặc display name làm primary/ownership key.

#### `groups`

- `group_id uuid PRIMARY KEY`
- `issuer`, `provider_group_key`, `name`, `status`
- `created_at`, `updated_at`
- `UNIQUE (issuer, provider_group_key)`

#### `roles`

- `role_id uuid PRIMARY KEY`
- `key text UNIQUE`, `description`, `status`
- Seed idempotent `staff`, `leader`, `curator`, `admin` nếu repository contract của
  TIP-003 dùng đúng các role key này.

#### `subject_groups`, `subject_roles`

- Composite uniqueness cho membership.
- `assigned_by uuid NULL`, `valid_from`, `expires_at`, timestamps.

#### `policies`, `entitlements`

- Bám đúng persistence shape của TIP-003 repository ports.
- Mỗi object có UUID/version bất biến, effect/action/conditions/priority/active.
- Entitlement có subject, resource/action/effect, expiry, granted_by và reason.
- Không tái triển khai matcher hay deny precedence trong SQL.
- Mọi privileged mutation phải ghi audit trong cùng Unit of Work.

Session, OIDC tokens và provider payload vẫn ở boundary TIP-003/Redis; không tạo
bảng session hoặc token trong PostgreSQL.

### 4. Authorization resource projection

#### `resources`

- `resource_id uuid PRIMARY KEY`
- `resource_type text NOT NULL`
  - Phạm vi TIP này: `source`, `document`, `document_version`, `object`, `rendition`
- `owner_subject_id uuid NULL`
- `classification text CHECK`:
  - `public_internal`
  - `internal`
  - `restricted`
  - `highly_restricted`
- `source_zone text CHECK`:
  - `sot`
  - `research`
  - `private_context`
- `department_id uuid NULL`
- `project_id uuid NULL`
- `lifecycle_state text CHECK`:
  - `draft`
  - `active`
  - `superseded`
  - `quarantined`
  - `deleted`
- `created_at`, `updated_at`, `deleted_at`
- `retention_until timestamptz NULL`
- `legal_hold boolean NOT NULL DEFAULT false`

`department_id` và `project_id` là opaque identity/group references; TIP này không
tạo business model phòng ban hoặc dự án.

Index tối thiểu:

- `(classification, source_zone, lifecycle_state)`
- `owner_subject_id`
- `department_id`
- `project_id`

#### `acl_entries`

- `acl_id uuid PRIMARY KEY`
- `resource_id uuid REFERENCES resources`
- `principal_type text CHECK`:
  - `user`, `group`, `role`, `department`, `project`
- `principal_id uuid NOT NULL`
- `action text NOT NULL`
- `effect text CHECK (effect IN ('allow','deny'))`
- `conditions jsonb NOT NULL DEFAULT '{}'`
- `valid_from`, `expires_at`
- `granted_by uuid NULL`
- `reason text`
- `created_at`
- Unique key đủ ngăn duplicate grant giống hệt.

Expired rows được giữ để audit. ACL repository trả các row đang áp dụng; policy
engine TIP-003 vẫn chịu trách nhiệm explicit-deny precedence và admin non-bypass.

### 5. Sources, immutable objects và document versions

#### `sources`

- `source_id uuid PRIMARY KEY REFERENCES resources`
- `kind`, `name`, `canonical_uri`
- `metadata jsonb`
- timestamps

URI là locator, không phải identity. Absolute local path không được lộ qua client API.

#### `object_blobs`

- `object_id uuid PRIMARY KEY REFERENCES resources`
- `bucket text NOT NULL`
- `object_key text UNIQUE NOT NULL`
- `sha256 char(64) NOT NULL`
- `byte_size bigint CHECK (byte_size >= 0)`
- `mime_type text NOT NULL`
- `etag text NULL`
- `encryption_key_ref text NULL`
- `storage_state text CHECK`:
  - `staged`, `available`, `quarantined`, `missing`, `deleted`
- `created_by uuid`
- `created_at`, `verified_at`

ETag không được thay SHA-256. Object key sinh từ UUID, không phụ thuộc filename hoặc
path người dùng. TIP này không deduplicate checksum xuyên trust zone để tránh side
channel xác nhận file tồn tại.

#### `documents`

- `document_id uuid PRIMARY KEY REFERENCES resources`
- `source_id uuid NULL REFERENCES sources`
- `logical_name text NOT NULL`
- `current_version_id uuid NULL`
- timestamps

#### `document_versions`

- `version_id uuid PRIMARY KEY REFERENCES resources`
- `document_id uuid REFERENCES documents`
- `version_no integer CHECK (version_no > 0)`
- `object_id uuid REFERENCES object_blobs`
- `original_filename`, `mime_type`, `sha256`, `byte_size`
- `created_by`, `created_at`
- `effective_at`, `review_after`, `expires_at`
- `supersedes_version_id uuid NULL`
- `UNIQUE (document_id, version_no)`
- `UNIQUE (document_id, object_id)`

Version đã active là bất biến. Nội dung mới luôn tạo version mới; current pointer
được đổi transactionally. Hai writer đồng thời phải dùng row/advisory lock để không
tạo trùng version number hoặc mất current pointer.

#### `renditions`

- `rendition_id uuid PRIMARY KEY REFERENCES resources`
- `version_id uuid REFERENCES document_versions`
- `kind`, `object_id`, `mime_type`
- `status text CHECK`:
  - `pending`, `ready`, `failed`, `quarantined`
- `generator`, `generator_version`
- timestamps
- `error_code` đã sanitize

TIP này chỉ định nghĩa metadata contract. Render, OCR và transcript thuộc TIP-005.

Không tạo trong TIP này:

- `records`, `record_versions`, `evidence_spans`
- `chunks`, vector indexes nghiệp vụ
- ingestion jobs
- generated files
- bất kỳ bảng giả nào chỉ để giữ chỗ cho TIP sau

### 6. Object repository và consistency

- S3 adapter stream upload vào UUID staging key.
- SHA-256 và byte size được tính server-side trong lúc stream.
- Nếu client gửi checksum, mismatch phải fail-closed.
- HEAD verify object trước khi transactionally đánh dấu `available` và tạo version.
- Upload lỗi không được tạo active document version.
- Database rollback sau upload để object ở `staged` hoặc orphan state có thể reconcile;
  không được silently available.
- Download/presign chỉ nhận authorization decision/capability từ policy boundary;
  repository không tự coi owner hoặc admin là allow.
- Original filename chỉ là metadata hiển thị và phải được normalize.
- Reconciliation command mặc định read-only. Repair/delete cần flag explicit và audit.

### 7. Append-only audit

#### `audit_events`

- `sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE`
- `event_id uuid PRIMARY KEY`
- `occurred_at timestamptz NOT NULL DEFAULT now()`
- `actor_kind text CHECK`:
  - `user`, `service`, `anonymous`
- `actor_user_id uuid NULL`
- `action text NOT NULL`
- `result text CHECK`:
  - `allow`, `deny`, `success`, `failure`
- `reason_code text NOT NULL`
- `request_id text NOT NULL`
- `session_fingerprint text NULL`
- `resource_id uuid NULL`
- `resource_type text NULL`
- `matched_policy_ids uuid[] NOT NULL DEFAULT '{}'`
- `details jsonb NOT NULL DEFAULT '{}'`
- `previous_hash char(64) NULL`
- `event_hash char(64) NOT NULL`
- `serialization_version integer NOT NULL`

Invariants:

- Runtime role chỉ có `INSERT` và `SELECT`.
- Runtime role không có `UPDATE`, `DELETE`, `TRUNCATE`.
- Database trigger fail-closed khi update/delete.
- Audit insert đi qua repository/stored function đã kiểm field.
- Hash chain được gán trong transaction dưới advisory lock ở quy mô đầu.
- Verify command phải recompute toàn chain.
- Privileged database mutation và audit event commit/rollback cùng transaction.
- External S3 action ghi staged/success/failure events bằng cùng request/job ID.

Key denylist/redaction tối thiểu, kể cả nested payload:

- `token`
- `cookie`
- `authorization`
- `password`
- `secret`
- `code_verifier`
- `raw_oidc`
- `access_token`
- `id_token`

### 8. Backup và restore

Backup tạo manifest phiên bản hóa gồm:

- UTC timestamp
- application version
- Alembic revision
- PostgreSQL custom-format dump và SHA-256
- MinIO inventory: bucket, key, size và checksum metadata
- audit event count, sequence và head hash

Consistency gate ban đầu dùng maintenance/write-pause:

1. Chặn mutation.
2. Dump database.
3. Mirror object set.
4. Verify inventory/checksum.
5. Ghi manifest.
6. Mở mutation lại.

Không được tuyên bố snapshot atomic nếu không có write-pause hoặc cơ chế tương đương.

Restore:

- Chỉ chạy vào database và bucket đích được khai rõ, đang trống.
- `--force` nếu có phải kèm typed target confirmation.
- Không default tới production.
- Restore xong kiểm Alembic head, row counts, current-version links, object
  HEAD/size/checksum metadata, audit chain và repository smoke reads.
- Secret, credential, local `.env`, raw token không nằm trong archive.

## CONFIGURABLE BUSINESS DECISIONS

Các quyết định sau cần Human/authority chốt trước production rollout nhưng **không
chặn việc xây schema foundation**:

1. Thời gian retention mặc định theo classification/resource type.
2. Ai có quyền đặt và gỡ legal hold; quy trình dual-control nếu cần.
3. Physical purge cadence và ngoại lệ pháp lý.
4. Backup destination, vùng địa lý, encryption/KMS và quyền operator.
5. RPO/RTO mục tiêu, lịch backup và thời gian giữ từng generation.

Trong TIP-004:

- Các giá trị trên phải configurable, không hard-code policy kinh doanh.
- Nếu chưa cấu hình, hệ thống chọn chế độ bảo toàn: không physical purge; legal hold
  được enforce; backup command yêu cầu destination explicit.
- Schema, migration, repository, append-only audit và restore drill vẫn phải hoàn tất.
- Production enablement thiếu các quyết định này được ghi deferred sang readiness
  gate, không được ghi là đã chốt.

## FILE/PATTERN PREVIEW

```text
v2/apps/backend/
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── src/rtr_copilot/
│   ├── db/
│   │   ├── engine.py
│   │   ├── models.py
│   │   └── uow.py
│   ├── repositories/
│   │   ├── identity_postgres.py
│   │   ├── resources.py
│   │   ├── objects.py
│   │   └── audit.py
│   ├── storage/s3.py
│   └── commands/
│       ├── migration_check.py
│       ├── reconcile_objects.py
│       └── verify_audit.py
└── tests/
    ├── unit/
    ├── integration/
    └── migration/

v2/scripts/
├── backup-data.sh
└── restore-data.sh
```

Exact adapter filenames phải theo repository ports thực tế sau TIP-003; không tạo
duplicate parallel interface.

## ACCEPTANCE CRITERIA

### AC-004.1 · Clean migration

**Given** PostgreSQL trống dùng image pgvector
**When** chạy `alembic upgrade head`
**Then** bốn revision chạy transactionally, extensions/tables/indexes/grants tồn
tại, current revision bằng head; chạy lần hai là no-op.

### AC-004.2 · Upgrade/downgrade safety

**Given** database ở từng revision
**When** downgrade một revision rồi upgrade lại head
**Then** schema và fixture thuộc contract revision đó còn đúng; migration failure
rollback hoàn toàn, không để half-created schema. Destructive downgrade phải cảnh báo.

### AC-004.3 · Runtime least privilege

**Given** runtime credential
**When** thử `CREATE`, `ALTER`, `DROP`, hoặc mutation audit
**Then** tất cả bị từ chối. API không cần migration DSN để serve khi schema đã ở head;
schema drift làm readiness 503 thay vì auto-migrate.

### AC-004.4 · Immutable identity adapter

**Given** TIP-003 repository contract suite
**When** chạy cùng suite trên PostgreSQL adapter
**Then** cùng `(issuer,sub)` luôn trả cùng UUID; hai subject trùng display name có hai
UUID; đổi email giữ UUID; disabled subject không tự active lại.

### AC-004.5 · UUID và resource invariants

**Given** các create operation hợp lệ
**When** tạo subject/source/document/version/object/rendition/ACL/audit
**Then** mọi ID là UUID sinh server-side; filename/path/display name không trở thành
ID, key hoặc owner. Classification/zone/lifecycle sai bị database từ chối.

### AC-004.6 · ACL projection integration

**Given** resource attributes và ACL rows
**When** round-trip qua repository
**Then** không mất field; expired row bị loại khỏi active query; unknown/deleted/
quarantined resource dẫn tới default-deny. Ít nhất 40 TIP-003 policy scenarios chạy
với PostgreSQL adapter cho kết quả giống memory adapter, gồm admin non-bypass và
explicit deny precedence.

### AC-004.7 · Object integrity

**Given** fixture có checksum biết trước
**When** stream upload
**Then** stored size/SHA-256 khớp phép tính độc lập, HEAD thành công, key chứa UUID
không chứa filename. Declared checksum sai fail-closed; không active version nào
tham chiếu object missing hoặc mismatch.

### AC-004.8 · Version concurrency và immutability

**Given** hai writer đồng thời tạo version cho một document
**When** cả hai commit
**Then** sinh hai version number tuần tự, không duplicate/lost current pointer.
Activated version không sửa content/checksum/object FK; supersede tạo row mới và giữ
version cũ theo ACL/retention.

### AC-004.9 · Failure và orphan handling

**Given** injected S3 failure, database rollback và interruption giữa upload/finalize
**When** chạy workflow
**Then** không broken version nào active; reconciliation read-only báo staged orphan;
repair/delete cần explicit mode và ghi audit.

### AC-004.10 · Audit completeness và redaction

**Given** TIP-003 auth/policy events và TIP-004 mutations
**When** đọc audit
**Then** event có actor/action/result/reason/request/time/resource và matched policy
IDs khi áp dụng. Nested secret probes tạo zero forbidden key/value trong database/log.
Anonymous/service event không cần fake user UUID.

### AC-004.11 · Append-only và tamper evidence

**Given** runtime role
**When** thử update/delete/truncate audit
**Then** đều fail. Full chain verify pass sau insert thường và concurrent. Một controlled
tamper bằng migration owner trong isolated test database phải bị verifier phát hiện.

### AC-004.12 · Transactional mutation audit

**Given** subject role/entitlement, ACL hoặc current-version mutation
**When** inject failure trước commit
**Then** state và audit cùng rollback. Khi thành công, cả hai cùng commit; không có
privileged state thiếu audit event.

### AC-004.13 · Retention và legal hold

**Given** resource có retention hoặc legal hold
**When** soft-delete hoặc yêu cầu purge
**Then** soft-delete không xóa blob/version/audit; purge trước retention hoặc khi
legal hold bật bị từ chối. Chưa có business defaults thì hệ thống bảo toàn và không
physical purge.

### AC-004.14 · Restart persistence

**Given** fixtures identity/resource/ACL/document/object/audit
**When** `make down` rồi `make dev`
**Then** UUID, current version, object bytes/checksum, ACL và audit head còn nguyên.
Redis session lifecycle vẫn thuộc TIP-003.

### AC-004.15 · Backup/restore drill

**Given** fixture stack và destination explicit
**When** backup rồi restore vào database/bucket trống biệt lập
**Then** Alembic ở head; 100% expected row counts/current links; 100% object inventory
HEAD/size/checksum metadata; audit chain/head/count đúng; repository smoke pass.
Report ghi duration, archive bytes và measured RPO window. Destructive target guard
phải được test.

### AC-004.16 · Technical và boundary health

**Given** implementation hoàn tất
**When** chạy full verify
**Then** frozen locks, dependency audit, Ruff, mypy, pytest, migration/integration,
Docker build và Compose health đều pass với count cụ thể. Legacy/kernel/GOI không
đổi; không có record/evidence/chunk placeholder, secret, dump, backup hoặc cache
được commit.

## CONSTRAINTS

- Không đổi identity/policy public contract của TIP-003 nếu chưa L2 approval.
- Không dùng email/display name/filename làm identity hoặc ownership.
- Không cho runtime app quyền DDL hoặc mutation audit.
- Không coi ETag là content checksum.
- Không deduplicate object xuyên trust zone trong TIP này.
- Không tạo ingestion, SOT, evidence, chunk hoặc generated-file model sớm.
- Không mount KnowledgeBase/kernel trực tiếp vào API hoặc database.
- Không hard-code retention, legal-hold authority hoặc backup destination.
- Không chạm legacy pilot, kernel hoặc GOI packs.

## MINIMUM VERIFY EVIDENCE

- Alembic history/current, fresh upgrade và downgrade/upgrade logs.
- Schema/index/grant inventory; runtime forbidden-operation outputs.
- TIP-003 memory/PostgreSQL repository parity count.
- Object SHA-256, injected failures và reconciliation report.
- Audit count, sequence, head hash, full-chain verify và forbidden mutation outputs.
- Backup manifest, empty-target proof, restore counts/checksums và measured durations.
- Compose volumes, ports, mounts.
- Test/lint/type/dependency-audit counts.
- Git diff chứng minh boundary.

## ESCALATION

- **L2:** TIP-003 repository ports không biểu đạt atomic Unit of Work hoặc immutable
  `(issuer,sub)` mapping.
- **L2:** Muốn đổi PostgreSQL/MinIO service family, giảm checksum/append-only
  guarantees hoặc thêm cross-zone deduplication.
- **L3/Human:** Chốt retention duration, legal-hold authority, purge policy,
  backup destination/encryption/KMS và production RPO/RTO.

## REPORT

Builder nộp Completion Report chuẩn Vibecode gồm:

- Files changed.
- 16 AC pass/fail, severity mỗi fail.
- Migration, schema, grant và repository contract counts.
- Object integrity/failure-injection results.
- Audit append-only/redaction/hash-chain results.
- Backup/restore drill metrics.
- Issues, deviations và suggestions.
