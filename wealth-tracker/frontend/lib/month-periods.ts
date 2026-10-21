// Where a month starts: on the 1st, or on the day your salary comes in.
//
// The backend (month_periods.py) recognises your salary days and gives the
// boundaries; here is only how a screen places a date in a month. A month is
// named after the calendar month in which it starts, so a key always stays
// "YYYY-MM" — also in the salary month.

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type MonthPeriods = {
  /** What you chose. */
  mode: "calendar" | "salary";
  /** What is used: "salary" without a recognised or set day falls back to "calendar". */
  active: "calendar" | "salary";
  category: string;
  day: number | null;
  day_configured: number | null;
  shift: "earlier" | "later";
  recognised: { day: number; count: number; last: string } | null;
  /** First day of every month, ascending; also the coming months. */
  boundaries: string[];
  current: { start: string; end: string };
};

export function useMonthPeriods() {
  return useQuery({ queryKey: ["month_periods"], queryFn: () => api.get<MonthPeriods>("/api/month-periods") });
}

/** The salary boundaries when the salary month is in use, otherwise null: the calendar month. */
export function boundariesOf(m: MonthPeriods | undefined | null): string[] | null {
  return m?.active === "salary" ? m.boundaries : null;
}

/** How many boundaries lie on or before `date`. */
function countUntil(boundaries: string[], date: string): number {
  let lo = 0,
    hi = boundaries.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (boundaries[mid] <= date) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The month in which `date` falls, as "YYYY-MM" of the month in which it starts. */
export function monthKey(date: string, boundaries: string[] | null): string {
  if (!boundaries) return date.slice(0, 7);
  const i = countUntil(boundaries, date);
  return i ? boundaries[i - 1].slice(0, 7) : date.slice(0, 7);
}

/** The first day of the month in which `date` falls. */
export function monthStart(date: string, boundaries: string[] | null): string {
  if (!boundaries) return `${date.slice(0, 7)}-01`;
  const i = countUntil(boundaries, date);
  return i ? boundaries[i - 1] : `${date.slice(0, 7)}-01`;
}

/** The index of the boundary with which the month of `date` starts, or -1. */
export function boundaryIndex(date: string, boundaries: string[]): number {
  return countUntil(boundaries, date) - 1;
}

/**
 * First and last day of the month with key "YYYY-MM". With salary months it runs
 *  from its boundary to the day before the next one; the last one runs to the end
 *  of the calendar month after it, or earlier with `end`.
 */
export function monthPeriod(key: string, boundaries: string[] | null): { start: string; end: string } {
  const endCalendar = (s: string) => {
    const [j, m] = s.split("-").map(Number);
    return new Date(Date.UTC(j, m, 0)).toISOString().slice(0, 10);
  };
  const i = boundaries ? boundaries.findIndex((g) => g.startsWith(key)) : -1;
  if (!boundaries || i < 0) return { start: `${key}-01`, end: endCalendar(key) };
  const following = boundaries[i + 1];
  if (following) {
    const d = new Date(`${following}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - 1);
    return { start: boundaries[i], end: d.toISOString().slice(0, 10) };
  }
  const [j, m] = key.split("-").map(Number);
  const after = `${m === 12 ? j + 1 : j}-${String(m === 12 ? 1 : m + 1).padStart(2, "0")}`;
  return { start: boundaries[i], end: endCalendar(after) };
}
