import {Suspense} from "react";
import {cookies} from "next/headers";
import {AppShell} from "../../shell/AppShell";
import {resolveCollapsed, resolveTheme, SIDEBAR_COOKIE, THEME_COOKIE} from "../../shell/theme";

/**
 * TIP-011 shell route group: every page placed under `(shell)/` renders inside
 * the unified AppShell. Theme + sidebar density are read from cookies here (a
 * server component) and handed to the client shell so the first paint already
 * matches the persisted preference — no flash, no hydration mismatch.
 */
export default async function ShellLayout({children}: Readonly<{children: React.ReactNode}>) {
  const store = await cookies();
  const initialTheme = resolveTheme(store.get(THEME_COOKIE)?.value);
  const initialCollapsed = resolveCollapsed(store.get(SIDEBAR_COOKIE)?.value);
  return <Suspense>
    <AppShell initialTheme={initialTheme} initialCollapsed={initialCollapsed}>
      {children}
    </AppShell>
  </Suspense>;
}
