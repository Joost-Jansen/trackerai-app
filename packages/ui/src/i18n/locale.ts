// Which languages the apps speak, and how the choice is made before and after login (both apps, @trackerai/ui/i18n/locale).
//
// Order: the user's own choice stored with the account, else the last choice on this device
// (localStorage, also set on the login page), else the browser's language. Dutch browsers get Dutch, every other
// browser English. The server renders Dutch (DEFAULT_LOCALE); each app's provider switches before the first text shows.

export const LOCALES = ["nl", "en"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "nl";

/** BCP 47 tag for Intl. English is en-GB: metric, 24-hour clock, weeks from Monday and "4 Oct 2026", like the data. */
export const INTL: Record<Locale, string> = { nl: "nl-NL", en: "en-GB" };

export const STORAGE_KEY = "locale";

export const isLocale = (v: unknown): v is Locale => typeof v === "string" && (LOCALES as readonly string[]).includes(v);

export function browserLocale(languages: readonly string[] | undefined): Locale {
  for (const lang of languages ?? []) {
    const base = lang.toLowerCase().split("-")[0];
    if (isLocale(base)) return base;
  }
  return "en";
}

export function storedLocale(): Locale | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return isLocale(v) ? v : null;
  } catch {
    return null;
  }
}

export function storeLocale(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    /* no storage: the choice lasts this visit */
  }
}

/** The locale before we know who is logged in. */
export function deviceLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  return storedLocale() ?? browserLocale(navigator.languages?.length ? navigator.languages : [navigator.language]);
}

/** Inline script for <head>: sets <html lang> before the first paint (same rule as deviceLocale). */
export const LOCALE_INIT_SCRIPT = `
try {
  var l = localStorage.getItem("${STORAGE_KEY}");
  if (l !== "nl" && l !== "en") {
    l = "en";
    var langs = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language];
    for (var i = 0; i < langs.length; i++) {
      var b = String(langs[i] || "").toLowerCase().split("-")[0];
      if (b === "nl" || b === "en") { l = b; break; }
    }
  }
  document.documentElement.lang = l;
} catch (e) {}
`;
