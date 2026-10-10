// The trackers as brands: name, colours and where they live. Colours are the
// ones each app uses itself (health: sage on dark green, wealth: terracotta on
// walnut), so a visitor recognises the app they are about to open.

export type BrandId = "health" | "wealth";
export type Locale = "en" | "nl";

export type Brand = {
  id: BrandId;
  name: string;
  /** CSS class that sets the brand's palette (marketing.css). */
  className: string;
};

export const BRANDS: Record<BrandId, Brand> = {
  health: { id: "health", name: "health-tracker", className: "mk-health" },
  wealth: { id: "wealth", name: "wealth-tracker", className: "mk-wealth" },
};

/** The cookie that keeps the language a visitor chose at the bottom of the front door ("en" or "nl"). */
export const LOCALE_COOKIE = "trackerai_locale";

/** The front door's language: English, unless the visitor chose Dutch (LOCALE_COOKIE). The browser's own preference
 *  is not used: the page is English until someone switches. */
export function localeFromCookie(value: string | null | undefined): Locale {
  return value === "nl" ? "nl" : "en";
}

/** "nl" when the visitor's browser prefers Dutch, otherwise "en". */
export function localeFrom(acceptLanguage: string | null | undefined): Locale {
  const first = (acceptLanguage ?? "").split(",")[0]?.trim().toLowerCase() ?? "";
  return first.startsWith("nl") ? "nl" : "en";
}
