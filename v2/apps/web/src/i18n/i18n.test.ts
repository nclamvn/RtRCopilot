import {expect, test} from "vitest";
import {formatDate, formatDateTime, formatNumber} from "./format";
import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE,
  LOCALES,
  MESSAGES,
  resolveLocale,
} from "./messages";

test("catalog parity: vi and en expose exactly the same keys, all non-empty", () => {
  const viKeys = Object.keys(MESSAGES.vi).sort();
  const enKeys = Object.keys(MESSAGES.en).sort();
  expect(enKeys).toEqual(viKeys);
  expect(viKeys.length).toBeGreaterThan(0);
  for (const locale of LOCALES) {
    for (const [key, value] of Object.entries(MESSAGES[locale])) {
      expect(typeof value, `${locale}:${key}`).toBe("string");
      expect(value.trim().length, `${locale}:${key} must not be empty`)
        .toBeGreaterThan(0);
    }
  }
});

test("vi is the default locale and unknown cookie values fall back to it", () => {
  expect(DEFAULT_LOCALE).toBe("vi");
  expect(resolveLocale("en")).toBe("en");
  expect(resolveLocale("vi")).toBe("vi");
  expect(resolveLocale(undefined)).toBe("vi");
  expect(resolveLocale(null)).toBe("vi");
  expect(resolveLocale("de")).toBe("vi");
  expect(resolveLocale("")).toBe("vi");
  expect(LOCALE_COOKIE).toBe("rtr_locale");
});

test("number formatting follows the locale", () => {
  expect(formatNumber(12345.67, "vi")).toBe("12.345,67");
  expect(formatNumber(12345.67, "en")).toBe("12,345.67");
});

test("date and datetime formatting follow the locale", () => {
  const value = "2026-08-01T12:34:00Z";
  const utc = {timeZone: "UTC"} as const;
  expect(formatDate(value, "vi", utc)).toBe("1/8/2026");
  expect(formatDate(value, "en", utc)).toBe("8/1/2026");
  expect(formatDateTime(value, "vi", utc)).toContain("1/8/2026");
  expect(formatDateTime(value, "en", utc)).toContain("8/1/2026");
});
