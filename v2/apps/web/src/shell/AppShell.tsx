"use client";

/**
 * TIP-011 Task 1 — unified application shell.
 *
 * Adoption contract (Builders B/C):
 * - Wrap a route by placing its page under `src/app/(shell)/…` — the group
 *   layout renders `<AppShell>` around the page. The shell owns the skip
 *   link, the single topbar, the left nav and the `<main id="main">`
 *   landmark; pages render ONE `<PageHeader title=…/>` (the only H1) plus
 *   content. Pages must NOT render their own `<main>`, topbar or H1.
 * - Focus shortcut: F6 / Shift+F6 cycles every `[data-shell-region]`
 *   element (nav ⇄ work surface today). Builder B's Evidence Rail joins the
 *   cycle by adding `data-shell-region` + `tabIndex={-1}` to the rail.
 * - Active-area rules live in `activeArea()`; "/" counts as Files until
 *   Builder C moves the Files workspace to `/files`.
 */

import React, {useCallback, useEffect, useState} from "react";
import Link from "next/link";
import {usePathname, useSearchParams} from "next/navigation";
import {LOCALES, MessageKey} from "../i18n/messages";
import {useI18n} from "../i18n/provider";

type Identity = {user_id: string; email: string; display_name: string; roles: string[]};

export type ShellArea =
  | "ask" | "files" | "documents" | "knowledge" | "operations" | "admin";

export const NAV_AREAS: ReadonlyArray<{
  area: ShellArea; href: string; labelKey: MessageKey;
}> = [
  {area: "ask", href: "/ask", labelKey: "shell.nav.ask"},
  {area: "files", href: "/files", labelKey: "shell.nav.files"},
  {area: "documents", href: "/documents", labelKey: "shell.nav.documents"},
  {area: "knowledge", href: "/knowledge-ops?view=research", labelKey: "shell.nav.knowledge"},
  {area: "operations", href: "/knowledge-ops", labelKey: "shell.nav.operations"},
  {area: "admin", href: "/admin", labelKey: "shell.nav.admin"},
];

/**
 * D-011-01 nav split for Knowledge Ops: "Tri thức" targets the research
 * views (`?view=research|graduation`, already URL-restorable in that page);
 * every other knowledge-ops view belongs to "Vận hành".
 */
export function activeArea(pathname: string, view: string | null): ShellArea | null {
  if (pathname === "/ask" || pathname.startsWith("/ask/")) return "ask";
  if (pathname === "/" || pathname === "/files" || pathname.startsWith("/files/")) {
    return "files";
  }
  if (pathname === "/documents" || pathname.startsWith("/documents/")) {
    return "documents";
  }
  if (pathname === "/knowledge-ops" || pathname.startsWith("/knowledge-ops/")) {
    return view === "research" || view === "graduation" ? "knowledge" : "operations";
  }
  if (pathname === "/admin" || pathname.startsWith("/admin/")) return "admin";
  return null;
}

/** Consistent breadcrumb-less title row: the page's ONE H1. */
export function PageHeader({eyebrow, title, actions}: {
  eyebrow?: string; title: string; actions?: React.ReactNode;
}) {
  return <header className="page-head">
    <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1></div>
    {actions}
  </header>;
}

export function AppShell({children}: {children: React.ReactNode}) {
  const {locale, t, setLocale} = useI18n();
  const pathname = usePathname();
  const view = useSearchParams().get("view");
  const active = activeArea(pathname, view);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [lastPathname, setLastPathname] = useState(pathname);
  if (lastPathname !== pathname) {
    // Close the drawer on route change (render-time adjustment, no effect).
    setLastPathname(pathname);
    setNavOpen(false);
  }

  useEffect(() => {
    fetch("/api/auth/me", {cache: "no-store"})
      .then(async response => setIdentity(
        response.ok ? await response.json() as Identity : null,
      ))
      .catch(() => setIdentity(null)).finally(() => setAuthReady(true));
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
      if (event.key !== "F6") return;
      event.preventDefault();
      const regions = Array.from(
        document.querySelectorAll<HTMLElement>("[data-shell-region]"),
      );
      if (regions.length === 0) return;
      const current = regions.findIndex(
        region => region.contains(document.activeElement),
      );
      const step = event.shiftKey ? -1 : 1;
      const base = current === -1 ? (step === 1 ? -1 : 0) : current;
      const next = regions[(base + step + regions.length) % regions.length];
      if (next.id === "shell-nav") setNavOpen(true);
      next.focus();
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  const skipToMain = useCallback((event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    // focus() scrolls the landmark into view; no separate scroll call needed.
    document.getElementById("main")?.focus();
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", {method: "POST"});
    setIdentity(null);
  }

  return <div className="shell">
    <a className="skip-link" href="#main" onClick={skipToMain}>
      {t("shell.skipToContent")}
    </a>
    <header className="shell-topbar">
      <button className="shell-menu" type="button" aria-expanded={navOpen}
        aria-controls="shell-nav" onClick={() => setNavOpen(open => !open)}>
        {t("shell.menu")}
      </button>
      <Link className="brand nav-brand shell-brand" href="/">
        <span className="mark">RT</span><span>{t("shell.brand")}</span>
      </Link>
      {/* Global search affordance — placeholder routing to Ask (TIP OUT OF SCOPE). */}
      <Link className="shell-search" href="/ask">
        <span>{t("shell.search")}</span><code aria-hidden>/ask</code>
      </Link>
      <div className="lang-switch" role="group" aria-label={t("shell.language")}>
        {LOCALES.map(item => <button key={item} type="button" lang={item}
          aria-pressed={locale === item} onClick={() => setLocale(item)}>
          {item.toUpperCase()}
        </button>)}
      </div>
      <div className="identity">
        {identity && <>
          <strong>{identity.display_name || identity.email}</strong>
          <button type="button" onClick={() => void logout()}>{t("shell.logout")}</button>
        </>}
        {!identity && authReady && <>
          {/* OIDC requires a full navigation through the same-origin callback. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/api/auth/login">{t("shell.login")}</a>
        </>}
        {!identity && !authReady
          && <span role="status">{t("shell.sessionChecking")}</span>}
      </div>
    </header>
    <nav id="shell-nav" className={`shell-nav ${navOpen ? "open" : ""}`}
      aria-label={t("shell.navLabel")} tabIndex={-1} data-shell-region>
      <div className="shell-nav-head">
        <p className="eyebrow">{t("shell.navLabel")}</p>
        <button className="shell-nav-close" type="button"
          aria-label={t("shell.closeNav")} onClick={() => setNavOpen(false)}>×</button>
      </div>
      <ol>
        {NAV_AREAS.map(item => <li key={item.area}>
          <Link href={item.href}
            aria-current={active === item.area ? "page" : undefined}
            onClick={() => setNavOpen(false)}>{t(item.labelKey)}</Link>
        </li>)}
      </ol>
      <p className="shell-nav-hint">{t("shell.keyboardHint")}</p>
    </nav>
    <main id="main" className="shell-main" tabIndex={-1} data-shell-region>
      {children}
    </main>
    {navOpen && <button className="shell-scrim" type="button"
      aria-label={t("shell.closeNav")} onClick={() => setNavOpen(false)}/>}
  </div>;
}
