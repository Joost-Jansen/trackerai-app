// The shared language rules (@trackerai/ui/i18n/locale), plus this app's page-load language: switching language
// stores the choice and reloads the page, so texts in module-level constants follow along too.
import { deviceLocale, INTL, type Locale } from "@trackerai/ui/i18n/locale";

export * from "@trackerai/ui/i18n/locale";

/** The language of this page load. */
export const locale: Locale = deviceLocale();

/** The Intl tag of this page load: "nl-NL" or "en-GB". */
export const intlLocale: string = INTL[locale];
