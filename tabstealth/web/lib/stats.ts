// Practice statistics for the Practice page, from GET /api/practice (lib/api.ts PracticeSummary).

import { localDay } from "./library.ts";

/** The last `n` days up to `today`, oldest first, with the minutes played on each (0 when none). */
export function lastDays(days: { day: string; seconds: number }[], n: number, today: Date = new Date()): { day: string; minutes: number }[] {
  const byDay = new Map(days.map((d) => [d.day, d.seconds]));
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (n - 1 - i));
    const day = localDay(d);
    return { day, minutes: Math.round(((byDay.get(day) ?? 0) / 60) * 10) / 10 };
  });
}

/** Minutes in the last 7 days, and in the 7 before that (to compare). */
export function weekMinutes(days: { day: string; seconds: number }[], today: Date = new Date()) {
  const last14 = lastDays(days, 14, today);
  const sum = (xs: { minutes: number }[]) => Math.round(xs.reduce((a, b) => a + b.minutes, 0));
  return { thisWeek: sum(last14.slice(7)), lastWeek: sum(last14.slice(0, 7)) };
}

/** "1 h 05 min" / "12 min". */
export function duration(seconds: number): string {
  const m = Math.round(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min` : `${m} min`;
}
