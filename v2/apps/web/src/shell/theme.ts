/**
 * Theme + sidebar-density preferences. Both persist ONLY in cookies (never
 * localStorage/sessionStorage — same rule as the locale, D-011-05) and are
 * resolved SSR so the first paint already carries the user's choice with no
 * flash and no hydration mismatch.
 */

export type Theme = "light" | "dark";

/** Shipped identity is dark; light is a first-class, fully-supported opt-in. */
export const DEFAULT_THEME: Theme = "dark";
export const THEME_COOKIE = "rtr_theme";
export const SIDEBAR_COOKIE = "rtr_sidebar";

export function resolveTheme(value: string | null | undefined): Theme {
  return value === "light" ? "light" : DEFAULT_THEME;
}

export function resolveCollapsed(value: string | null | undefined): boolean {
  return value === "collapsed";
}
