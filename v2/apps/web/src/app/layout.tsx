import type {Metadata} from "next";
import {cookies} from "next/headers";
import {I18nProvider} from "../i18n/provider";
import {LOCALE_COOKIE, resolveLocale} from "../i18n/messages";
import {resolveTheme, THEME_COOKIE} from "../shell/theme";
// Token foundation first, then the frozen legacy sheet, then the in-scope
// premium layers (shell chrome + ask/rail re-skin) so scoped overrides win.
import "./styles/tokens.css";
import "./styles/themes.css";
import "./styles/typography.css";
import "./styles/motion.css";
import "./styles.css";
import "./styles/shell.css";
import "./styles/ask.css";
// WP-B: theme-aware aliases for the frozen tokens (must load after styles.css).
import "./styles/legacy-bridge.css";

export const metadata: Metadata = {
  title: "RtR Copilot",
  description: "Không gian làm việc tri thức nội bộ của RtR",
};

export default async function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  const store = await cookies();
  const locale = resolveLocale(store.get(LOCALE_COOKIE)?.value);
  const theme = resolveTheme(store.get(THEME_COOKIE)?.value);
  return <html lang={locale} data-theme={theme}><body>
    <I18nProvider initialLocale={locale}>{children}</I18nProvider>
  </body></html>;
}
