// Picking periods and counting months.
//
// A month is a calendar month, or — with the salary month on — the time from
// salary to salary. In that last case a screen passes the boundaries
// (lib/month-periods.ts); without boundaries everything is as it was.

import { boundaryIndex, monthKey } from "./month-periods";
import { tr } from "./i18n/tr";

export type DateWindow = { from: string; to: string };
export const PERIODS = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "All"];
const MONTHS: Record<string, number> = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "3Y": 36 };

/** Codes from before the English rename, as an old link or a saved chart setting may still hold them. */
const OLD_CODES: Record<string, string> = {
  "1J": "1Y",
  "3J": "3Y",
  "5J": "5Y",
  Alles: "All",
  Eigen: "Custom",
  Dag: "day",
  Maand: "month",
  Jaar: "year",
};
export const currentCode = (code: string): string => OLD_CODES[code] ?? code;

/** A period or range as shown: "1Y" is "1J" in Dutch, "All" is "Alles". */
export function periodLabel(code: string): string {
  switch (code) {
    case "1Y":
      return tr("1Y");
    case "3Y":
      return tr("3Y");
    case "5Y":
      return tr("5Y");
    case "All":
      return tr("All");
    case "Custom":
      return tr("Custom");
    default:
      return code;
  }
}
export const periodTabs = (codes: readonly string[]) => codes.map((id) => ({ id, label: periodLabel(id) }));

/** The detail of a balance line: every day, the last value per month, or per year. */
export const GRANULARITIES = ["day", "month", "year"] as const;
export type Granularity = (typeof GRANULARITIES)[number];
export const granularityTabs = () => [
  { id: "day", label: tr("Day") },
  { id: "month", label: tr("Month") },
  { id: "year", label: tr("Year") },
];
const DAY = 86400000;
export const dayNumber = (d: string) => Date.parse(`${d}T00:00:00Z`) / DAY;
export const isoDay = (n: number) => new Date(n * DAY).toISOString().slice(0, 10);

/**
 * The window of a period up to and including `last`.
 *
 * With salary boundaries "1M" is the current salary month, "3M" that plus the
 * two before it, and so on; "YTD" starts at the first salary of the year.
 */
export function periodWindow(period: string, first: string, last: string, boundaries?: string[] | null): DateWindow {
  if (period === "All") return { from: first, to: last };
  if (boundaries?.length) {
    const i = boundaryIndex(last, boundaries);
    if (i >= 0) {
      let from: string;
      if (period === "YTD") {
        from = boundaries.find((g) => g >= `${last.slice(0, 4)}-01-01` && g <= last) ?? boundaries[i];
      } else {
        from = boundaries[Math.max(0, i - ((MONTHS[period] ?? 12) - 1))];
      }
      return { from: [first, from].sort().pop()!, to: last };
    }
  }
  if (period === "YTD") return { from: [first, `${last.slice(0, 4)}-01-01`].sort().pop()!, to: last };
  const months = MONTHS[period] ?? 12;
  const date = new Date(`${last}T00:00:00Z`);
  const originalDay = date.getUTCDate();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() - months);
  const monthEnd = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(originalDay, monthEnd));
  return { from: [first, isoDay(date.getTime() / DAY + 1)].sort().pop()!, to: last };
}
export function moveWindow(window: DateWindow, first: string, last: string, scale: number, direction = 0): DateWindow {
  const low = dayNumber(first),
    high = dayNumber(last);
  const oldSpan = dayNumber(window.to) - dayNumber(window.from) + 1;
  const span = Math.max(1, Math.min(high - low + 1, Math.round(oldSpan * scale)));
  const center = (dayNumber(window.to) + dayNumber(window.from)) / 2 + direction * oldSpan;
  const start = Math.max(low, Math.min(high - span + 1, Math.round(center - (span - 1) / 2)));
  return { from: isoDay(start), to: isoDay(start + span - 1) };
}
/**
 * The balances in a window, starting from the balance at the end of the day
 * before its first day: like the months on Net worth and the MCP split. Without
 * that base, what happened on the first day (often your salary) falls out of
 * every change measured over the window.
 */
export function windowWithBase<T extends { d: string }>(rows: T[], window: { from: string; to: string }): T[] {
  const inside = rows.filter((r) => r.d >= window.from && r.d <= window.to);
  const base = rows.filter((r) => r.d < window.from).at(-1);
  return base && inside.length > 0 ? [base, ...inside] : inside;
}
/**
 * Balances are observations: sample the last observation, never sum them.
 * With salary boundaries a "month" is the stand on the day before the next salary.
 */
export function sampleBalances<T extends { d: string }>(rows: T[], granularity: string, boundaries?: string[] | null): T[] {
  if (granularity === "day" || rows.length < 2) return rows;
  const groups = new Map<string, T>();
  for (const p of rows) groups.set(granularity === "year" ? p.d.slice(0, 4) : monthKey(p.d, boundaries ?? null), p);
  const sampled = [...groups.values()];
  return sampled[0].d === rows[0].d ? sampled : [rows[0], ...sampled];
}

/** Calendar months covered, weighting a partial month by its actual day count. */
export function monthsCovered(window: DateWindow): number {
  if (window.from > window.to) return 0;
  const cursor = new Date(`${window.from.slice(0, 7)}-01T00:00:00Z`);
  let total = 0;
  const start = dayNumber(window.from),
    end = dayNumber(window.to) + 1;
  while (cursor.getTime() / DAY < end) {
    const monthStart = cursor.getTime() / DAY;
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
    const nextMonth = cursor.getTime() / DAY;
    total += Math.max(0, Math.min(end, nextMonth) - Math.max(start, monthStart)) / (nextMonth - monthStart);
  }
  return total;
}

/** Salary months in the window; part of a month counts pro rata to its days. */
export function periodsCovered(window: DateWindow, boundaries: string[]): number {
  if (window.from > window.to) return 0;
  const start = dayNumber(window.from),
    end = dayNumber(window.to) + 1;
  let total = 0;
  for (let i = 0; i + 1 < boundaries.length; i++) {
    const a = dayNumber(boundaries[i]),
      b = dayNumber(boundaries[i + 1]);
    total += Math.max(0, Math.min(end, b) - Math.max(start, a)) / (b - a);
  }
  return total;
}

export function averageMonthBase(window: DateWindow, preset: string, boundaries?: string[] | null): number {
  if (boundaries?.length) return periodsCovered(window, boundaries);
  const months = MONTHS[preset];
  // A complete selected 3M window is three months, even when its end months
  // have different day counts. A shortened history/custom window is prorated.
  if (months && periodWindow(preset, "0001-01-01", window.to).from === window.from) return months;
  return monthsCovered(window);
}
