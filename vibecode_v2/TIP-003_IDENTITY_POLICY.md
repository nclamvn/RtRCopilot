# TIP-003 · Identity, Session và Policy Engine

## HEADER

- **TIP-ID:** TIP-003
- **Project:** RtR Copilot V2
- **Module:** `v2/apps/backend` + auth shell tối thiểu trong `v2/apps/web`
- **Depends on:** TIP-002
- **Priority:** P0
- **Status:** VERIFIED · READY

## CONTEXT

- Identity default đã approved: Google Workspace OIDC cho `rtrobotics.com` và
  `rtrobotics.me`; local admin chỉ là break-glass.
- V2 foundation đã có FastAPI, Redis, typed errors, request ID và Next.js shell.
- TIP-004 mới tạo business database schema. TIP này dùng repository interfaces +
  Redis session; test adapters in-memory. Không tạo business migrations trước TIP-004.
- Pilot ba-role là input migration, không phải policy model đích.

## TASK

### 1. OIDC

Implement authorization-code flow với PKCE, state và nonce:

- Configurable issuer/discovery URL, client ID và secret.
- Chỉ chấp nhận email verified thuộc allowlist domain.
- Subject key là `(issuer, sub)`, không dùng display name làm identity.
- Cùng subject login lại giữ immutable UUID.
- User mới nhận quyền thấp nhất; không tự nâng quyền từ client input.
- Provider error/timeout trả lỗi an toàn, không lộ token/secret.

Tests dùng fake OIDC provider/transport; không cần credential Google thật.

### 2. Sessions

- Opaque random session ID lưu Redis, TTL cấu hình.
- Cookie `HttpOnly`, `Secure` ở production, `SameSite=Lax` hoặc chặt hơn, path `/`.
- Rotate session sau login/role change; logout/revoke có hiệu lực ngay.
- Không lưu access/id token trong browser storage.
- CSRF/state replay bị chặn.

### 3. Subject model

Subject attributes tối thiểu:

- immutable `user_id`
- email/canonical domain
- status
- roles
- groups
- departments
- projects
- temporary entitlements với expiry

Các role nền: `staff`, `leader`, `curator`, `admin`. `admin` là quyền quản trị, không
tự động được đọc mọi classified resource.

### 4. Policy engine

Policy decision input:

```text
subject + action + resource attributes + context
```

Resource attributes: owner, classification/tier, department, project, source zone,
lifecycle state. Actions tối thiểu: ask, search, view, upload, download, render,
approve, curate, manage_users, manage_policies.

Invariants:

- Default deny.
- Explicit deny thắng allow.
- Expired entitlement bị bỏ.
- Owner không vượt classification.
- Admin không bypass content ACL nếu không có entitlement.
- Decision trả `allow/deny`, reason code và matched policy IDs.
- Mọi privileged decision có audit event không chứa secret/token.

### 5. API và web shell

Backend:

- `/auth/login`
- `/auth/callback`
- `/auth/logout`
- `/auth/me`
- endpoint dev/test provider chỉ tồn tại khi `APP_ENV=development|test`

Web:

- Trạng thái signed-out/signed-in thật.
- Nút đăng nhập công ty, logout và user identity.
- Không dựng admin UI hoặc tính năng nghiệp vụ giả.

## ACCEPTANCE CRITERIA

### AC-003.1 · OIDC security

Valid fake-provider flow login được; invalid/replayed state, nonce mismatch, PKCE
failure, unverified email và domain ngoài allowlist đều bị chặn.

### AC-003.2 · Immutable identity

Cùng issuer/sub qua nhiều login giữ một UUID; hai account trùng display name vẫn là
hai UUID; đổi email theo provider policy không tạo self-escalation.

### AC-003.3 · Session safety

Cookie attributes đúng; browser storage không có token; logout/revoke/role-change
làm session cũ chết; TTL và rotation được test.

### AC-003.4 · Role mapping

User mới là staff; group mapping server-side tạo role/department/project đúng;
client không inject role; account disabled bị deny.

### AC-003.5 · Policy matrix

Test ít nhất 40 scenario qua staff/leader/curator/admin, classifications, owner,
department/project, temporary entitlement và deny precedence. Unknown action/resource
default deny.

### AC-003.6 · Admin non-bypass

Admin quản trị user/policy được nhưng không đọc resource restricted nếu thiếu content
entitlement. Curator ghi workflow được nhưng không tự approve fact do chính mình đề xuất
nếu policy separation-of-duties bật.

### AC-003.7 · Audit

Login success/fail, logout, session revoke, role mapping và privileged policy decision
có actor/user ID, action, result, reason, request ID và timestamp; không log token,
cookie, secret hoặc raw OIDC payload.

### AC-003.8 · Fail-fast/config

Production thiếu issuer/client/secret/canonical URL hoặc dùng HTTP callback thì không
start. Error chỉ nêu key/reason. Development provider không thể bật ở production.

### AC-003.9 · API contract

OpenAPI typed; 401/403 có machine-readable code + request ID. Protected test route
chứng minh middleware/policy chạy thật, không chỉ unit-test engine.

### AC-003.10 · Web/browser

Playwright kiểm signed-out, fake login, signed-in identity, logout và protected-route
deny; mobile/desktop không overflow, keyboard focus visible.

### AC-003.11 · Technical health

Frozen locks, full dependency audit sạch, Ruff/mypy/pytest, ESLint/type/Vitest,
Playwright và Docker builds đều pass. Không chạm legacy/kernel/GOI.

## CONSTRAINTS

- Không gọi Google thật hoặc ghi credential vào repo.
- Không dùng email/display name làm row ownership.
- Không hard-code domain/group/role trong handler; đi qua config/mapping.
- Không tạo bảng business trước TIP-004; repository port phải thay adapter được.
- Break-glass disabled mặc định, chỉ explicit config, localhost/private path và audit.
- Không cấp superuser content bypass.

## REPORT

Completion Report phải ghi test counts theo OIDC/session/policy/API/browser, dependency
audit, cookie evidence, OpenAPI paths, log-redaction probes và mọi deviation.
