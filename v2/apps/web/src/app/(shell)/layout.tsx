import {Suspense} from "react";
import {AppShell} from "../../shell/AppShell";

/**
 * TIP-011 shell route group: every page placed under `(shell)/` renders
 * inside the unified AppShell. Builder C migrates files/documents/
 * knowledge-ops here; until then those routes keep their own topbars and the
 * shell wraps only /ask and /admin (no double-H1/landmark anywhere).
 */
export default function ShellLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <Suspense><AppShell>{children}</AppShell></Suspense>;
}
