/**
 * Locale-aware date/number formatting for later Builders (D-011-05).
 * Existing `when()`-style helpers migrate mechanically:
 *   `new Date(value).toLocaleString("vi-VN")` → `formatDateTime(value, locale)`.
 */

import {Locale} from "./messages";

const INTL_LOCALE: Record<Locale, string> = {vi: "vi-VN", en: "en-US"};

export function intlLocale(locale: Locale): string {
  return INTL_LOCALE[locale];
}

export function formatNumber(
  value: number, locale: Locale, options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(INTL_LOCALE[locale], options).format(value);
}

export function formatDate(
  value: Date | string | number, locale: Locale,
  options?: Intl.DateTimeFormatOptions,
): string {
  return new Date(value).toLocaleDateString(INTL_LOCALE[locale], options);
}

export function formatDateTime(
  value: Date | string | number, locale: Locale,
  options?: Intl.DateTimeFormatOptions,
): string {
  return new Date(value).toLocaleString(INTL_LOCALE[locale], options);
}
