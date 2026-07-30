# TIP-001 · Security Containment cho Pilot

## HEADER

- **TIP-ID:** TIP-001
- **Project:** RtR Copilot V2
- **Module:** `phase1_pilot`
- **Depends on:** None
- **Priority:** P0
- **Status:** VERIFIED READY · 30/07/2026

## CONTEXT

- Working directory: `/Users/os/RtR/KnowledgeBase/RtR_Copilot`
- Key files: `phase1_pilot/copilot_server.py`, `phase1_pilot/auth.py`,
  `phase1_pilot/test_copilot.py`, `phase1_pilot/e2e_tester.py`
- Baseline: 263 pass, 0 fail.
- Service hiện không chạy trên port 8787/8788 tại thời điểm SCAN.

## TASK

Đóng hai lỗ hổng P0 mà không thay kiến trúc pilot:

1. Mọi `/api/*` endpoint phải đi qua authentication mặc định, chỉ allowlist rõ các
   endpoint bootstrap không nhạy cảm.
2. Search/record/gaps/usedby/templates phải kiểm action permission tương ứng.
3. Download phải kiểm danh tính và ownership/authorization, không chỉ basename.
4. Auth mode là cấu hình fail-closed; account store lỗi/mất/corrupt không được rơi
   về anonymous/passcode/users fallback ngoài migration mode explicit.
5. Giữ hành vi hiện tại sau đăng nhập và không làm hỏng 263 regression tests; sửa
   test nào đang kỳ vọng truy cập anonymous.

## ACCEPTANCE CRITERIA

### AC-001 · Anonymous matrix

**Given** không có token/passcode hợp lệ
**When** gọi từng API dữ liệu
**Then** tất cả trả 401/403; không có record, gap, template metadata hoặc file bytes.

### AC-002 · Role matrix

**Given** user staff/leader/admin
**When** gọi toàn bộ endpoint
**Then** quyền khớp duy nhất với permission table; action chưa khai bị deny.

### AC-003 · Download ownership

**Given** hai user tạo hai tài liệu
**When** user A đoán hoặc lấy filename của user B
**Then** user A không tải được; audit ghi attempt; admin behavior theo policy rõ ràng.

### AC-004 · Corrupt auth store

**Given** account store missing, unreadable, invalid JSON hoặc không có active admin
**When** server khởi động hoặc protected request được gọi
**Then** service fail-closed/503 và health báo unhealthy; không anonymous fallback.

### AC-005 · Regression

**Given** bản vá hoàn tất
**When** chạy test suite và security matrix
**Then** 263 regression cũ (đã cập nhật auth expectation) cùng test mới đều pass;
không giảm ranh giới staff/leader hoặc document gate.

## CONSTRAINTS

- Không dựng V2 trong TIP này.
- Không đổi tech stack.
- Không đưa secret/account/log vào Git.
- Không mở server ra LAN để test.
- Nếu ownership cần metadata mới, chọn thay đổi tối thiểu và ghi DEVIATION; schema
  production thuộc TIP-004.

## REPORT FORMAT

Builder nộp Completion Report chuẩn Vibecode, gồm file thay đổi, test count,
acceptance result, issues, deviations và suggestions.
