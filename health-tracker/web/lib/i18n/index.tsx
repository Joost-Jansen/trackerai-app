"use client";

// i18n (T25): Dutch and English, no library. Texts live in lib/i18n/nl.ts (source) and lib/i18n/en.ts (same keys);
// the health and performance explanations in lib/texts.ts (T) and lib/i18n/texts.en.ts.
//
//   const t = useT();          t.common.save, t.history.count(12), t.texts.driftGood
//   const f = useFormat();     f.km(5.3) -> "5,3 km" / "5.3 km", f.day("2026-10-04") -> "4 okt 2026" / "4 Oct 2026"
//   const { locale, setLocale } = useLocale();
//
// Adding a string: add the key to nl.ts and en.ts (TypeScript fails on a missing one), use it via useT(), run
// `npm run check:i18n`. The language: see lib/i18n/locale.ts; the account setting is saved by setLocale(l, { save: true }).

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { UiLocale } from "@trackerai/ui/i18n";
import { api, ApiError } from "@/lib/api";
import { en } from "./en";
import { makeFormat, type Format } from "./format";
import { DEFAULT_LOCALE, deviceLocale, storeLocale, type Locale } from "./locale";
import { nl, type Messages } from "./nl";

export { LOCALES, type Locale } from "./locale";
export type { Messages } from "./nl";
export type { Format } from "./format";

const CATALOGS: Record<Locale, Messages> = { nl, en };
const FORMATS: Record<Locale, Format> = { nl: makeFormat("nl"), en: makeFormat("en") };

export const messages = (locale: Locale): Messages => CATALOGS[locale];
export const formatFor = (locale: Locale): Format => FORMATS[locale];

type Ctx = { locale: Locale; setLocale: (l: Locale, opts?: { save?: boolean }) => Promise<void> };
const LocaleContext = createContext<Ctx>({ locale: DEFAULT_LOCALE, setLocale: async () => {} });

const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setState] = useState<Locale>(DEFAULT_LOCALE);
  // Before the first paint: the server renders Dutch, the device may want English.
  useIsoLayoutEffect(() => setState(deviceLocale()), []);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  const setLocale = useCallback(async (l: Locale, opts: { save?: boolean } = {}) => {
    setState(l);
    storeLocale(l);
    if (opts.save) await api.patch("/api/account", { locale: l });
  }, []);
  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);
  return (
    <LocaleContext.Provider value={value}>
      <UiLocale locale={locale}>{children}</UiLocale>
    </LocaleContext.Provider>
  );
}

export const useLocale = () => useContext(LocaleContext);
export const useT = (): Messages => CATALOGS[useContext(LocaleContext).locale];
export const useFormat = (): Format => FORMATS[useContext(LocaleContext).locale];

/** Follows the language stored with the account once /api/me is known (null: keep the device's language). */
export function useAccountLocale(stored: string | null | undefined) {
  const { locale, setLocale } = useLocale();
  useEffect(() => {
    if ((stored === "nl" || stored === "en") && stored !== locale) setLocale(stored);
    // only when the account's value changes, not when the user switches here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stored]);
}

type ErrorText = string | ((p: never) => string);

/** An error for the user: the API's code in the current language, else its message, else `fallback`. */
export function errorText(err: unknown, t: Messages, fallback: string): string {
  if (err instanceof ApiError && err.code) {
    const m = (t.errors as Record<string, ErrorText>)[err.code];
    if (typeof m === "string") return m;
    if (typeof m === "function") return (m as (p: Record<string, unknown>) => string)(err.params ?? {});
  }
  return err instanceof Error && err.message ? err.message : fallback;
}

/** Display name of a route: generated names ("5.2 km loop (r3)", "40.0 km bike route (f1)", tools/routes.py) in the
 *  current language. Names generated before schema 3 are Dutch ("5.2 km rondje (r3)") and read the same way. */
export function routeName(name: string | null | undefined, id: string, t: Messages, f: Format): string {
  const m = /^(\d+\.\d) km (bike |fiets)?(loop|rondje|route) \(([rf]\d+)\)$/.exec(name ?? "");
  if (!m) return name || id;
  return t.routes.defaultName(f.num(Number(m[1]), 1), m[3] !== "route", !!m[2], m[4]);
}
