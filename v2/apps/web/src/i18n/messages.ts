/**
 * TIP-011 i18n foundation (D-011-05): Vietnamese-default typed string catalog.
 *
 * `vi` is the source of truth — its literal keys define `MessageKey`, so a key
 * missing from `en` (or an extra key in `en`) is a compile error. Runtime
 * parity is additionally guarded by `src/i18n/i18n.test.ts`.
 *
 * Migration pattern for later Builders (B/C/D): move a hard-coded Vietnamese
 * string into `vi` under a page namespace (`ask.*`, `files.*`, `documents.*`,
 * `ops.*`), add the English twin to `en`, then replace the literal with
 * `t("<key>")` from `useI18n()`. The type system lists every missing English
 * string as an error, which makes the sweep mechanical.
 */

export type Locale = "vi" | "en";
export const LOCALES: readonly Locale[] = ["vi", "en"];
export const DEFAULT_LOCALE: Locale = "vi";
/** Locale preference persists in this cookie only — never browser storage. */
export const LOCALE_COOKIE = "rtr_locale";

export function resolveLocale(value: string | null | undefined): Locale {
  return value === "en" ? "en" : DEFAULT_LOCALE;
}

const vi = {
  "shell.skipToContent": "Bỏ qua tới nội dung chính",
  "shell.brand": "RT ROBOTICS / COPILOT",
  "shell.navLabel": "Điều hướng chính",
  "shell.nav.ask": "Hỏi",
  "shell.nav.files": "Tệp",
  "shell.nav.documents": "Tài liệu",
  "shell.nav.knowledge": "Tri thức",
  "shell.nav.operations": "Vận hành",
  "shell.nav.admin": "Quản trị",
  "shell.search": "Tìm kiếm — hỏi Copilot",
  "shell.language": "Ngôn ngữ",
  "shell.menu": "Điều hướng",
  "shell.closeNav": "Đóng điều hướng",
  "shell.login": "Đăng nhập công ty",
  "shell.logout": "Đăng xuất",
  "shell.sessionChecking": "Đang kiểm tra phiên…",
  "shell.keyboardHint":
    "F6 / Shift+F6: chuyển tiêu điểm giữa điều hướng và vùng làm việc",
  "surface.loading": "Đang tải…",
  "surface.denied": "Bị từ chối theo chính sách",
  "surface.error": "Không tải được dữ liệu",
  "surface.retry": "Thử lại",
  "ask.eyebrow": "Trợ lý có căn cứ",
  "ask.title": "Hỏi",
  "ask.comingSoon":
    "Sắp có: đặt câu hỏi và nhận câu trả lời có trích dẫn sâu từ SOT công ty, "
    + "gắn với Evidence Rail dùng chung.",
  "ask.note":
    "Không gian này được TIP-011 Task 2 hoàn thiện; ô tìm kiếm trên cùng dẫn về đây.",
  "admin.eyebrow": "Bề mặt quản trị",
  "admin.title": "Quản trị",
  "admin.comingSoon":
    "Chưa có giao diện quản trị; các bề mặt API quản trị hiện có:",
  "admin.api.sources": "Nguồn nghiên cứu — đăng ký, kích hoạt, tạm dừng",
  "admin.api.settings": "Thiết lập quản trị — SLA và ngưỡng vận hành",
  "admin.api.gapPriority": "Ghi đè ưu tiên khoảng trống",
  "admin.api.subjects": "Tài khoản chủ thể và vai trò",
  "admin.api.jobs": "Sức khỏe job nền",
} as const;

export type MessageKey = keyof typeof vi;

const en: Record<MessageKey, string> = {
  "shell.skipToContent": "Skip to main content",
  "shell.brand": "RT ROBOTICS / COPILOT",
  "shell.navLabel": "Primary navigation",
  "shell.nav.ask": "Ask",
  "shell.nav.files": "Files",
  "shell.nav.documents": "Documents",
  "shell.nav.knowledge": "Knowledge",
  "shell.nav.operations": "Operations",
  "shell.nav.admin": "Admin",
  "shell.search": "Search — ask Copilot",
  "shell.language": "Language",
  "shell.menu": "Navigation",
  "shell.closeNav": "Close navigation",
  "shell.login": "Company sign-in",
  "shell.logout": "Sign out",
  "shell.sessionChecking": "Checking session…",
  "shell.keyboardHint":
    "F6 / Shift+F6: move focus between navigation and the work surface",
  "surface.loading": "Loading…",
  "surface.denied": "Denied by policy",
  "surface.error": "Could not load data",
  "surface.retry": "Retry",
  "ask.eyebrow": "Grounded assistant",
  "ask.title": "Ask",
  "ask.comingSoon":
    "Coming soon: ask questions and receive answers with deep citations from "
    + "the company SOT, wired to the shared Evidence Rail.",
  "ask.note":
    "This surface is completed by TIP-011 Task 2; the top search box routes here.",
  "admin.eyebrow": "Admin surface",
  "admin.title": "Administration",
  "admin.comingSoon": "No admin UI yet; existing admin API surfaces:",
  "admin.api.sources": "Research sources — register, activate, pause",
  "admin.api.settings": "Governance settings — SLA and operating thresholds",
  "admin.api.gapPriority": "Gap priority override",
  "admin.api.subjects": "Subject accounts and roles",
  "admin.api.jobs": "Background job health",
};

export const MESSAGES: Record<Locale, Record<MessageKey, string>> = {vi, en};
