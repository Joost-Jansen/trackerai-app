"use client";

// i18n: Dutch and English, no library, the same model as health-tracker. Texts live in lib/i18n/nl.ts (source) and
// lib/i18n/en.ts (same keys). The language: the choice on this device, else the browser's (@trackerai/ui/i18n/locale).
//
//   const t = useT();   t.library.title, t.library.measures(12)

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useState } from "react";
import { UiLocale } from "@trackerai/ui/i18n";
import { DEFAULT_LOCALE, deviceLocale, storeLocale, type Locale } from "@trackerai/ui/i18n/locale";
import { en } from "./en";
import { nl, type Messages } from "./nl";

export type { Messages };
export type { Locale };

const CATALOGS: Record<Locale, Messages> = { nl, en };

type Ctx = { locale: Locale; setLocale: (l: Locale) => void };
const LocaleContext = createContext<Ctx>({ locale: DEFAULT_LOCALE, setLocale: () => {} });

const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setState] = useState<Locale>(DEFAULT_LOCALE);
  // Before the first paint: the server renders Dutch, the device may want English.
  useIsoLayoutEffect(() => setState(deviceLocale()), []);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  const setLocale = useCallback((l: Locale) => {
    storeLocale(l);
    setState(l);
  }, []);
  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <UiLocale locale={locale}>{children}</UiLocale>
    </LocaleContext.Provider>
  );
}

export const useLocale = () => useContext(LocaleContext);
export const useT = (): Messages => CATALOGS[useContext(LocaleContext).locale];
