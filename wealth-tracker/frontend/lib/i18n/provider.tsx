"use client";

// Renders the app once the language is known (in the browser), keeps <html lang> right, and follows the language
// stored with the account.

import { useEffect, useState } from "react";
import { UiLocale } from "@trackerai/ui/i18n";
import { api } from "@/lib/api";
import { isLocale, locale, storeLocale, type Locale } from "./locale";

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // The server renders Dutch; the browser may want English. Rendering only after mount keeps the two from
  // disagreeing (no hydration mismatch) and costs one frame.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    document.documentElement.lang = locale;
    setMounted(true);
  }, []);
  return mounted ? <UiLocale locale={locale}>{children}</UiLocale> : null;
}

/** Switch language: remember it on this device (and with the account when `save`), then reload. */
export async function setLocale(l: Locale, opts: { save?: boolean } = {}): Promise<void> {
  storeLocale(l);
  if (opts.save) {
    try {
      await api.put("/api/auth/me/locale", { locale: l });
    } catch {
      /* the device keeps the choice; the account follows next time */
    }
  }
  if (l !== locale) window.location.reload();
}

/** Follows the language stored with the account once /api/auth/me is known. */
export function useAccountLocale(stored: string | null | undefined) {
  useEffect(() => {
    if (isLocale(stored) && stored !== locale) {
      storeLocale(stored);
      window.location.reload();
    }
  }, [stored]);
}
