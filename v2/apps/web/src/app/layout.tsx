import type {Metadata} from "next";
import {cookies} from "next/headers";
import {I18nProvider} from "../i18n/provider";
import {LOCALE_COOKIE, resolveLocale} from "../i18n/messages";
import "./styles.css";

export const metadata: Metadata = {
  title: "RtR Copilot",
  description: "Không gian làm việc tri thức nội bộ của RtR",
};

export default async function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  const locale = resolveLocale((await cookies()).get(LOCALE_COOKIE)?.value);
  return <html lang={locale}><body>
    <I18nProvider initialLocale={locale}>{children}</I18nProvider>
  </body></html>;
}
