"use client";

import React, {createContext, useCallback, useContext, useMemo, useState} from "react";
import {DEFAULT_LOCALE, Locale, LOCALE_COOKIE, MESSAGES, MessageKey} from "./messages";

type I18n = {
  locale: Locale;
  t: (key: MessageKey) => string;
  setLocale: (locale: Locale) => void;
};

/**
 * Default context renders the Vietnamese catalog, so components (e.g. the
 * shared `Surface`) keep today's vi strings even when rendered without a
 * provider — unit tests of individual pages need no wrapper.
 */
const FALLBACK: I18n = {
  locale: DEFAULT_LOCALE,
  t: key => MESSAGES[DEFAULT_LOCALE][key],
  setLocale: () => undefined,
};

const I18nContext = createContext<I18n>(FALLBACK);

export function I18nProvider({initialLocale, children}: {
  initialLocale: Locale; children: React.ReactNode;
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    // The switch re-renders in place (no reload); the cookie is the only
    // persistence — never localStorage/sessionStorage (D-011-05).
    document.documentElement.lang = next;
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
  }, []);
  const value = useMemo<I18n>(
    () => ({locale, setLocale, t: key => MESSAGES[locale][key]}),
    [locale, setLocale],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  return useContext(I18nContext);
}
