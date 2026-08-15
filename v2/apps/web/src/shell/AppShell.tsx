"use client";

/**
 * Unified application shell — PRD UI/UX v1.0 premium rebuild.
 *
 * Preserved TIP-011 contracts (unchanged behaviour, new chrome):
 * - Skip link is the first focusable element and moves focus to `#main`.
 * - ONE primary `<nav aria-label>` holding the six areas as `<ol>` links with
 *   `aria-current="page"` on the active area; `activeArea()` rules unchanged.
 * - F6 / Shift+F6 cycles every `[data-shell-region]` (nav ⇄ main ⇄ rail).
 * - Locale switch flips strings, `<html lang>` and the `rtr_locale` cookie
 *   only (never browser storage). Anonymous sessions get the sign-in link.
 * - Pages still render ONE `<PageHeader>` (the only H1); the shell owns the
 *   single topbar, nav and `<main>` landmark.
 *
 * New (PRD): light/dark theme switch (cookie), collapsible sidebar (cookie),
 * workspace switcher, new-question button, grouped icon navigation, recent
 * conversations, system-integrity card, pinned user profile, and a ⌘K command
 * palette. Theme + density arrive pre-resolved from the server layout.
 */

import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import Link from "next/link";
import {usePathname, useRouter, useSearchParams} from "next/navigation";
import {LOCALES, Locale, MessageKey} from "../i18n/messages";
import {useI18n} from "../i18n/provider";
import {formatDateTime} from "../i18n/format";
import {
  askQuery,
  ConversationListPage,
  parseConversationList,
} from "../ask/contracts";
import {Icon, IconName} from "./Icon";
import {SIDEBAR_COOKIE, Theme, THEME_COOKIE} from "./theme";

type Identity = {user_id: string; email: string; display_name: string; roles: string[]};

export type ShellArea =
  | "ask" | "intelligence" | "files" | "documents"
  | "knowledge" | "operations" | "admin";

export const NAV_AREAS: ReadonlyArray<{
  area: ShellArea; href: string; labelKey: MessageKey; icon: IconName;
}> = [
  {area: "ask", href: "/ask", labelKey: "shell.nav.ask", icon: "ask"},
  {area: "intelligence", href: "/intelligence",
    labelKey: "shell.nav.intelligence", icon: "intelligence"},
  {area: "files", href: "/files", labelKey: "shell.nav.files", icon: "files"},
  {area: "documents", href: "/documents", labelKey: "shell.nav.documents", icon: "documents"},
  {area: "knowledge", href: "/knowledge-ops?view=research", labelKey: "shell.nav.knowledge", icon: "knowledge"},
  {area: "operations", href: "/knowledge-ops", labelKey: "shell.nav.operations", icon: "operations"},
  {area: "admin", href: "/admin", labelKey: "shell.nav.admin", icon: "admin"},
];

/** Role-scoped information architecture. Unknown/no-role users get only the
 * ordinary workspace; privileged surfaces never become dead-end navigation. */
export function visibleAreas(identity: Identity | null): ReadonlyArray<(typeof NAV_AREAS)[number]> {
  const roles = new Set(identity?.roles ?? []);
  return NAV_AREAS.filter(item => {
    if (item.area === "admin") return roles.has("admin");
    if (item.area === "knowledge" || item.area === "operations") {
      return roles.has("curator") || roles.has("admin");
    }
    return true;
  });
}

const GROUPS: ReadonlyArray<{titleKey: MessageKey; areas: ShellArea[]}> = [
  {titleKey: "shell.group.workspace", areas: ["ask", "intelligence", "files", "documents"]},
  {titleKey: "shell.group.governance", areas: ["knowledge", "operations", "admin"]},
];

/**
 * D-011-01 nav split for Knowledge Ops: "Tri thức" targets the research
 * views (`?view=research|graduation`); every other view belongs to "Vận hành".
 */
export function activeArea(pathname: string, view: string | null): ShellArea | null {
  if (pathname === "/ask" || pathname.startsWith("/ask/")) return "ask";
  if (pathname === "/intelligence" || pathname.startsWith("/intelligence/")) {
    return "intelligence";
  }
  if (pathname === "/files" || pathname.startsWith("/files/")) return "files";
  if (pathname === "/documents" || pathname.startsWith("/documents/")) return "documents";
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

function initials(source: string): string {
  const clean = source.trim();
  if (!clean) return "?";
  const parts = clean.split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

type Command = {
  id: string; label: string; icon: IconName; hint?: string;
  href?: string; run: () => void;
};

function CommandPalette({commands, onClose, onAsk, askPrefix, placeholder, emptyText}: {
  commands: Command[]; onClose: () => void; onAsk: (query: string) => void;
  askPrefix: string; placeholder: string; emptyText: string;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const filtered = useMemo<Command[]>(() => {
    const q = query.trim().toLowerCase();
    const matching = q ? commands.filter(c => c.label.toLowerCase().includes(q)) : commands;
    if (!q) return matching;
    return [{
      id: "ask-query", label: `${askPrefix}: “${query.trim()}”`, icon: "ask",
      hint: "↵", href: `/ask?q=${encodeURIComponent(query.trim())}`,
      run: () => onAsk(query.trim()),
    }, ...matching];
  }, [commands, query, askPrefix, onAsk]);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(index => (index + 1) % Math.max(filtered.length, 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(index => (index - 1 + filtered.length) % Math.max(filtered.length, 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      filtered[active]?.run();
    }
  };

  return <div className="pc-palette-scrim" role="presentation"
    onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="pc-palette" role="dialog" aria-modal="true" aria-label={placeholder}
      onKeyDown={onKeyDown}>
      <div className="pc-palette-input-row">
        <Icon name="search"/>
        <input ref={inputRef} type="text" value={query} placeholder={placeholder}
          aria-label={placeholder}
          onChange={event => { setQuery(event.target.value); setActive(0); }}/>
        <kbd className="pc-kbd">Esc</kbd>
      </div>
      {filtered.length === 0
        ? <p className="pc-palette-empty">{emptyText}</p>
        : <ul className="pc-palette-list">
            {filtered.map((command, index) => {
              const content = <>
                <span className="pc-nav-ico"><Icon name={command.icon}/></span>
                <span>{command.label}</span>
                {command.hint && <kbd className="pc-kbd pc-palette-hint">{command.hint}</kbd>}
              </>;
              return <li key={command.id}>
                {command.href
                  ? <a className="pc-palette-item" href={command.href}
                      data-active={index === active}
                      onMouseEnter={() => setActive(index)}>
                      {content}
                    </a>
                  : <button type="button" className="pc-palette-item"
                      data-active={index === active}
                      onMouseEnter={() => setActive(index)} onClick={command.run}>
                      {content}
                    </button>}
              </li>;
            })}
          </ul>}
    </div>
  </div>;
}

/** True when a keystroke target is a text field — the `?` hotkey stays inert there. */
function isTextInput(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable;
}

const HELP_ROWS: ReadonlyArray<[string, MessageKey]> = [
  ["⌘K", "shell.help.search"],
  ["⌘N", "shell.help.newq"],
  ["⌘1 / ⌘2 / ⌘3", "shell.help.nav"],
  ["F6 / ⇧F6", "shell.help.regions"],
  ["[ / ]", "shell.help.cite"],
  ["Esc", "shell.help.close"],
];

function HelpDialog({t, onClose}: {t: (key: MessageKey) => string; onClose: () => void}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, []);
  return <div className="pc-palette-scrim" role="presentation"
    onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="pc-help" role="dialog" aria-modal="true" aria-label={t("shell.help.title")}>
      <div className="pc-help-head">
        <h2>{t("shell.help.title")}</h2>
        <button ref={closeRef} type="button" className="pc-iconbtn"
          aria-label={t("shell.help.close")} onClick={onClose}>✕</button>
      </div>
      <ul className="pc-help-list">
        {HELP_ROWS.map(([keys, key]) => <li key={keys}>
          <span className="pc-help-keys">
            {keys.split(" / ").map(part => <kbd key={part} className="pc-kbd">{part}</kbd>)}
          </span>
          <span>{t(key)}</span>
        </li>)}
      </ul>
    </div>
  </div>;
}

export function AppShell({children, initialTheme = "dark", initialCollapsed = false}: {
  children: React.ReactNode; initialTheme?: Theme; initialCollapsed?: boolean;
}) {
  const {locale, t, setLocale} = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const view = useSearchParams().get("view");
  const active = activeArea(pathname, view);

  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const helpBtnRef = useRef<HTMLButtonElement>(null);
  const [recent, setRecent] = useState<ConversationListPage["items"]>([]);
  const [health, setHealth] = useState<{
    ok: boolean;
    status: string;
    answerQuality: "ready" | "evidence_only" | "configuration_required";
  } | null>(null);
  const [lastPathname, setLastPathname] = useState(pathname);
  const searchRef = useRef<HTMLButtonElement>(null);

  if (lastPathname !== pathname) {
    setLastPathname(pathname);
    setNavOpen(false);
    setPaletteOpen(false);
  }

  // Identity, recent conversations and system integrity (all best-effort).
  useEffect(() => {
    fetch("/api/auth/me", {cache: "no-store"})
      .then(async response => setIdentity(response.ok ? await response.json() as Identity : null))
      .catch(() => setIdentity(null)).finally(() => setAuthReady(true));
    fetch("/api/status", {cache: "no-store"})
      .then(async response => {
        const body = await response.json().catch(() => null) as {
          ok?: boolean;
          status?: string;
          answer_quality?: string;
        } | null;
        setHealth(body ? {
          ok: body.ok === true,
          status: body.status ?? "unavailable",
          answerQuality: body.answer_quality === "ready"
            ? "ready"
            : body.answer_quality === "evidence_only"
              ? "evidence_only"
              : "configuration_required",
        } : null);
      }).catch(() => setHealth({
        ok: false, status: "unavailable", answerQuality: "configuration_required",
      }));
  }, []);

  useEffect(() => {
    if (!identity) return;
    let active2 = true;
    fetch("/api/ask/conversations?limit=5", {cache: "no-store"})
      .then(async response => {
        if (!active2 || !response.ok) return;
        const body: unknown = await response.json().catch(() => null);
        try { setRecent(parseConversationList(body).items.slice(0, 5)); } catch { /* ignore */ }
      }).catch(() => undefined);
    return () => { active2 = false; };
  }, [identity, pathname]);

  // Focus the new content after a real route change (query-only stays put).
  const focusPathname = useRef(pathname);
  useEffect(() => {
    if (focusPathname.current === pathname) return;
    focusPathname.current = pathname;
    document.getElementById("main")?.focus();
  }, [pathname]);

  // F6 / Shift+F6 region cycle (nav ⇄ main ⇄ rail).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "F6") return;
      event.preventDefault();
      const regions = Array.from(document.querySelectorAll<HTMLElement>("[data-shell-region]"));
      if (regions.length === 0) return;
      const current = regions.reduce(
        (found, region, index) => region.contains(document.activeElement) ? index : found, -1);
      const step = event.shiftKey ? -1 : 1;
      const base = current === -1 ? (step === 1 ? -1 : 0) : current;
      const next = regions[(base + step + regions.length) % regions.length];
      if (next.id === "shell-nav") setNavOpen(true);
      next.focus();
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  const goNewQuestion = useCallback(() => {
    setPaletteOpen(false);
    router.push("/ask");
  }, [router]);

  // Reflect the actually-applied theme (explicit cookie attribute, else the OS
  // prefers-color-scheme) so the toggle icon is right with no cookie, and track
  // OS changes live until the visitor picks an explicit theme.
  useEffect(() => {
    const read = (): Theme => {
      const attr = document.documentElement.dataset.theme;
      if (attr === "light" || attr === "dark") return attr;
      return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
    };
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const update = () => setTheme(read());
    update();
    mq?.addEventListener?.("change", update);
    return () => mq?.removeEventListener?.("change", update);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(current => {
      const next: Theme = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
      return next;
    });
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed(current => {
      const next = !current;
      document.cookie =
        `${SIDEBAR_COOKIE}=${next ? "collapsed" : "expanded"}; path=/; max-age=31536000; samesite=lax`;
      return next;
    });
  }, []);

  const cycleLocale = useCallback(() => {
    setLocale(locale === "vi" ? "en" : "vi");
  }, [locale, setLocale]);

  // Global keyboard: ⌘K palette, ⌘N new question, ⌘1/2/3 nav, Escape closes.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (event.key === "Escape") {
        setPaletteOpen(false); setNavOpen(false); setHelpOpen(false); return;
      }
      if (event.key === "?" && !isTextInput(event.target)) {
        event.preventDefault(); setHelpOpen(true); return;
      }
      if (!mod) return;
      const key = event.key.toLowerCase();
      if (key === "k") { event.preventDefault(); setPaletteOpen(open => !open); }
      else if (key === "n") { event.preventDefault(); goNewQuestion(); }
      else if (key === "1") { event.preventDefault(); router.push("/ask"); }
      else if (key === "2") { event.preventDefault(); router.push("/files"); }
      else if (key === "3") { event.preventDefault(); router.push("/documents"); }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [router, goNewQuestion]);

  const closePalette = useCallback(() => {
    setPaletteOpen(false);
    searchRef.current?.focus();
  }, []);

  const closeHelp = useCallback(() => {
    setHelpOpen(false);
    helpBtnRef.current?.focus();
  }, []);

  const commands = useMemo<Command[]>(() => {
    const nav: Command[] = visibleAreas(identity).map((item, index) => ({
      id: `nav-${item.area}`, label: t(item.labelKey), icon: item.icon,
      hint: index < 3 ? `⌘${index + 1}` : undefined,
      run: () => { setPaletteOpen(false); router.push(item.href); },
    }));
    return [
      {id: "new", label: t("shell.newQuestion"), icon: "plus", hint: "⌘N", run: goNewQuestion},
      ...nav,
      {id: "theme", label: t(theme === "dark" ? "shell.theme.toLight" : "shell.theme.toDark"),
        icon: theme === "dark" ? "sun" : "moon", run: () => { toggleTheme(); setPaletteOpen(false); }},
      {id: "locale", label: t("shell.language"), icon: "languages",
        run: () => { cycleLocale(); setPaletteOpen(false); }},
    ];
  }, [t, theme, router, goNewQuestion, toggleTheme, cycleLocale, identity]);

  const askFromPalette = useCallback((query: string) => {
    setPaletteOpen(false);
    router.push(`/ask?q=${encodeURIComponent(query)}`);
  }, [router]);

  const skipToMain = useCallback((event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    document.getElementById("main")?.focus();
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", {method: "POST"});
    setIdentity(null);
  }

  const integrity = health === null
    ? {state: "idle" as const, value: "—", width: "40%", sub: t("shell.integrity.checking")}
    : health.ok && health.answerQuality === "ready"
      ? {state: "ok" as const, value: "100%", width: "100%", sub: t("shell.integrity.ready")}
      : health.ok && health.answerQuality === "evidence_only"
        ? {state: "ok" as const, value: "SOT", width: "92%", sub: t("shell.integrity.evidenceOnly")}
      : health.ok
        ? {state: "warn" as const, value: "LLM", width: "72%", sub: t("shell.integrity.answerSetup")}
        : {state: "down" as const, value: "—", width: "28%", sub: t("shell.integrity.down")};

  const displayName = identity?.display_name || identity?.email || "";
  const role = identity?.roles?.[0] ?? "";
  const areas = visibleAreas(identity);

  return <div className="pc-shell" data-collapsed={collapsed}>
    <a className="pc-skip-link" href="#main" onClick={skipToMain}>{t("shell.skipToContent")}</a>

    <div className={`pc-sidebar ${navOpen ? "open" : ""}`} id="pc-sidebar">
      <div className="pc-sidebar-head">
        <button className="pc-workspace" type="button" aria-haspopup="dialog"
          aria-label={t("shell.workspace.aria")}
          title={collapsed ? t("shell.workspace.name") : undefined}
          onClick={() => setPaletteOpen(true)}>
          <span className="pc-mark">RtR</span>
          <span className="pc-workspace-meta">
            <span className="pc-workspace-name">{t("shell.workspace.name")}</span>
          </span>
        </button>
        <button className="pc-collapse" type="button" aria-pressed={collapsed}
          aria-label={t(collapsed ? "shell.expandNav" : "shell.collapseNav")}
          onClick={toggleCollapsed}>
          <Icon name="panelLeft" size={17}/>
        </button>
      </div>

      <Link className="pc-new" href="/ask" title={t("shell.newQuestion")}>
        <span className="pc-new-ico"><Icon name="plus" size={16}/></span>
        <span className="pc-new-label">{t("shell.newQuestion")}</span>
        <kbd className="pc-kbd" aria-hidden>⌘N</kbd>
      </Link>

      <div className="pc-sidebar-scroll">
        <nav id="shell-nav" className="pc-nav" aria-label={t("shell.navLabel")}
          tabIndex={-1} data-shell-region>
          {GROUPS.map(group => {
            const groupAreas = group.areas.filter(area =>
              areas.some(item => item.area === area));
            if (groupAreas.length === 0) return null;
            return <div className="pc-navgroup" key={group.titleKey}>
              <p className="pc-navgroup-title">{t(group.titleKey)}</p>
              <ol>
              {groupAreas.map(area => {
                const item = NAV_AREAS.find(entry => entry.area === area)!;
                return <li key={area}>
                  <Link className="pc-nav-item" href={item.href}
                    aria-current={active === area ? "page" : undefined}
                    title={collapsed ? t(item.labelKey) : undefined}
                    onClick={() => setNavOpen(false)}>
                    <span className="pc-nav-ico"><Icon name={item.icon}/></span>
                    <span className="pc-nav-label">{t(item.labelKey)}</span>
                  </Link>
                </li>;
              })}
              </ol>
            </div>;
          })}
        </nav>

        {identity && recent.length > 0 && <section className="pc-recent" aria-label={t("shell.recent.title")}>
          <p className="pc-navgroup-title">{t("shell.recent.title")}</p>
          <ul>
            {recent.map(item => <li key={item.conversationId}>
              <Link className="pc-recent-item" href={`/ask?${askQuery(item.conversationId)}`}
                onClick={() => setNavOpen(false)}>
                <span className="pc-dot-tiny" aria-hidden/>
                <span>{t("shell.recent.conversation")} · {formatDateTime(item.lastActivityAt, locale, {
                  day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
                })}</span>
              </Link>
            </li>)}
          </ul>
        </section>}

      </div>

      <div className="pc-sidebar-footer">
        <div className="pc-integrity" role="status" aria-label={t("shell.integrity.title")}>
          <div className="pc-integrity-head">
            <span className="pc-status-dot" data-state={integrity.state}/>
            <span className="pc-integrity-title">{t("shell.integrity.title")}</span>
            <span className="pc-integrity-value">{integrity.value}</span>
          </div>
          <div className="pc-progress" data-state={integrity.state}>
            <span style={{width: integrity.width}}/>
          </div>
          <p className="pc-integrity-sub">{integrity.sub}</p>
        </div>
        <div className="pc-profile">
          {identity && <>
            <span className="pc-avatar" aria-hidden>{initials(displayName)}</span>
            <span className="pc-profile-meta">
              <span className="pc-profile-name">{displayName}</span>
              {role && <span className="pc-profile-role">{role}</span>}
            </span>
            <button className="pc-profile-action" type="button"
              aria-label={t("shell.logout")} onClick={() => void logout()}>
              <Icon name="logout" size={16}/>
            </button>
          </>}
          {!identity && authReady
            // OIDC requires a full navigation through the same-origin callback.
            // eslint-disable-next-line @next/next/no-html-link-for-pages
            && <a className="pc-signin" href="/api/auth/login">
              <Icon name="arrowRight" size={16}/>
              <span className="pc-signin-label">{t("shell.login")}</span>
            </a>}
          {!identity && !authReady
            && <span className="pc-profile-role" role="status">{t("shell.sessionChecking")}</span>}
        </div>
      </div>
    </div>

    <div className="pc-main-col">
      <header className="pc-topbar">
        <button className="pc-iconbtn pc-menu-btn" type="button" aria-expanded={navOpen}
          aria-controls="pc-sidebar" aria-label={t("shell.menu")}
          onClick={() => setNavOpen(open => !open)}>
          <Icon name="panelLeft" size={18}/>
        </button>
        <button className="pc-search" type="button" ref={searchRef}
          aria-haspopup="dialog" aria-label={t("shell.search")}
          onClick={() => setPaletteOpen(true)}>
          <Icon name="search" size={16}/>
          <span className="pc-search-label">{t("shell.search")}</span>
          <kbd className="pc-kbd" aria-hidden>⌘K</kbd>
        </button>
        <div className="pc-topbar-right">
          <div className="pc-locale" role="group" aria-label={t("shell.language")}>
            {LOCALES.map((item: Locale) => <button key={item} type="button" lang={item}
              aria-pressed={locale === item} onClick={() => setLocale(item)}>
              {item.toUpperCase()}
            </button>)}
          </div>
          <button className="pc-iconbtn" type="button" onClick={toggleTheme}
            aria-label={t(theme === "dark" ? "shell.theme.toLight" : "shell.theme.toDark")}>
            <Icon name={theme === "dark" ? "sun" : "moon"} size={18}/>
          </button>
          <button className="pc-iconbtn pc-help-btn" type="button" ref={helpBtnRef}
            aria-haspopup="dialog" aria-label={t("shell.help.open")}
            onClick={() => setHelpOpen(true)}>?</button>
        </div>
      </header>
      <main id="main" className="pc-main" tabIndex={-1} data-shell-region
        data-active-area={active ?? undefined}>
        {children}
      </main>
    </div>

    {/* PRD §13: mobile bottom dock — a second, distinctly-labelled nav shown
        only <760px (CSS). Icon links carry the six area names. */}
    <nav className="pc-dock" aria-label={t("shell.dockLabel")}>
      {areas.map(item => <Link key={item.area} className="pc-dock-item"
        href={item.href} aria-label={t(item.labelKey)}
        aria-current={active === item.area ? "page" : undefined}
        onClick={() => setNavOpen(false)}>
        <Icon name={item.icon} size={20}/>
      </Link>)}
    </nav>

    {navOpen && <button className="pc-scrim" type="button"
      aria-label={t("shell.closeNav")} onClick={() => setNavOpen(false)}/>}
    {paletteOpen && <CommandPalette commands={commands} onClose={closePalette}
      onAsk={askFromPalette} askPrefix={t("shell.palette.askPrefix")}
      placeholder={t("shell.search")} emptyText={t("shell.palette.empty")}/>}
    {helpOpen && <HelpDialog t={t} onClose={closeHelp}/>}
  </div>;
}
