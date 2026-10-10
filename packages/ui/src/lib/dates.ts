// Calendar days as plain "YYYY-MM-DD" strings, and their short labels. Shared by the charts of both apps.

export type Locale = "nl" | "en";

const DAY = 86_400_000;

/** Days since 1970-01-01 (UTC), so day arithmetic never meets a time zone or a DST change. */
export const dayNumber = (d: string): number => Date.parse(`${d.slice(0, 10)}T00:00:00Z`) / DAY;
export const isoDay = (n: number): string => new Date(Math.round(n) * DAY).toISOString().slice(0, 10);

// Written out rather than from Intl: Intl's Dutch short months carry a dot ("mrt."), and its English September is
// "Sept".
const MONTHS: Record<Locale, string[]> = {
  nl: ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

/** "jan" / "Jan": the short name of month 1–12. */
export const monthAbbr = (locale: Locale, month: number): string => MONTHS[locale][month - 1] ?? String(month);

/** "4 okt" / "4 Oct". A day ("2026-10-04") is read as written; a timestamp in the reader's time zone. */
export function dayMonth(locale: Locale, ts: string): string {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ts);
  if (day) return `${Number(day[3])} ${monthAbbr(locale, Number(day[2]))}`;
  const d = new Date(ts.includes("T") ? ts : ts.replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? ts : `${d.getDate()} ${monthAbbr(locale, d.getMonth() + 1)}`;
}
