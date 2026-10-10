"use client";

// The shared components' own texts, in Dutch and English: the same model as wealth-tracker's tr(). The code holds the
// English text; ./nl.ts maps it to Dutch; `npm run check:i18n --workspace @trackerai/ui` checks both ways.
//
//   const tr = useTr();
//   tr("Explanation {0}", label)   -> "Uitleg Rendement" / "Explanation Returns"
//
// The language comes from the app: it wraps its tree in <UiLocale locale={…}>, from its own i18n, so these texts
// switch together with the app's own.

import { createContext, useCallback, useContext, type ReactNode } from "react";
import { nl } from "./nl";

import type { Locale } from "./locale";

export type { Locale };

const LocaleContext = createContext<Locale>("nl");

/** Tells the shared components which language the app is in. */
export function UiLocale({ locale, children }: { locale: Locale; children: ReactNode }) {
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

export const useUiLocale = (): Locale => useContext(LocaleContext);

/** The text in the given language, with {0}, {1}… filled in. */
export function translate(locale: Locale, english: string, ...args: unknown[]): string {
  const s = locale === "nl" ? nl[english] ?? english : english;
  return args.length ? s.replace(/\{(\d+)\}/g, (m, i) => (Number(i) < args.length ? String(args[Number(i)]) : m)) : s;
}

/** tr() in the current language, for a component. */
export function useTr(): (english: string, ...args: unknown[]) => string {
  const locale = useUiLocale();
  return useCallback((english: string, ...args: unknown[]) => translate(locale, english, ...args), [locale]);
}
