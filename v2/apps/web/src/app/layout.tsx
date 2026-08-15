import type {Metadata} from "next";
import {cookies} from "next/headers";
import {I18nProvider} from "../i18n/provider";
import {LOCALE_COOKIE, resolveLocale} from "../i18n/messages";
import {readThemeCookie, THEME_COOKIE} from "../shell/theme";
// Token foundation first, then the frozen legacy sheet, then the in-scope
// premium layers (shell chrome + ask/rail re-skin) so scoped overrides win.
import "./styles/tokens.css";
import "./styles/themes.css";
import "./styles/typography.css";
import "./styles/motion.css";
import "./styles.css";
import "./styles/shell.css";
import "./styles/ask.css";
import "./styles/admin.css";
// WP-B: theme-aware aliases for the frozen tokens (must load after styles.css).
import "./styles/legacy-bridge.css";
// TIP-024.5: explicit recovery boundary, imported last so the content-aware
// responsive and readability contracts override frozen TIP-011 legacy rules.
import "./styles/ux-recovery.css";
// TIP-024.5: achromatic palette + provenance line grammar. Kept last so the
// product-wide refinement also reaches legacy workspaces through their bridge.
import "./styles/monochrome-premium.css";
// TIP-026.4: moderate compact density. Imported last so chrome geometry is
// consistent across both migrated and legacy-bridge workspaces.
import "./styles/compact-density.css";
// TIP-026.11: conversation-first Ask workspace; the final Ask-only layer.
import "./styles/chat-workspace.css";
// TIP-026.12: final cross-workspace geometry contract. This is intentionally
// last: it retires conflicting legacy grid/focus rules without widening the
// component API or coupling individual pages to stylesheet import order.
import "./styles/workspace-consistency.css";
import "./styles/intelligence.css";

export const metadata: Metadata = {
  title: "RtR Copilot",
  description: "Không gian làm việc tri thức nội bộ của RtR",
};

export default async function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  const store = await cookies();
  const locale = resolveLocale(store.get(LOCALE_COOKIE)?.value);
  // No cookie → omit data-theme so CSS resolves the OS prefers-color-scheme
  // (no flash). suppressHydrationWarning: the attribute may differ from SSR
  // once an explicit choice is made client-side.
  const theme = readThemeCookie(store.get(THEME_COOKIE)?.value);
  return <html lang={locale} data-theme={theme ?? undefined} suppressHydrationWarning><body>
    <I18nProvider initialLocale={locale}>{children}</I18nProvider>
  </body></html>;
}
