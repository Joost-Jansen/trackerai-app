// The label of a week or month of zones (GET /api/zones, /api/zones/history): "week 41 · 5 – 11 okt 2026" or
// "oktober 2026", in the user's language. The API's own `label` is Dutch; the site builds it from start and end.

import type { Format } from "./format";
import type { Messages } from "./nl";

function isoWeek(iso: string): number {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  const day = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - day + 3); // Thursday of this week
  const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((d.getTime() - firstThursday.getTime()) / 86_400_000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
}

export function periodLabel(period: "week" | "month", start: string, end: string, t: Messages, f: Format): string {
  if (period === "month") return f.month(start.slice(0, 7));
  const y1 = start.slice(0, 4);
  const y2 = end.slice(0, 4);
  const range =
    y1 !== y2
      ? `${f.day(start)} – ${f.day(end)}`
      : start.slice(5, 7) !== end.slice(5, 7)
        ? `${f.dayMonth(start)} – ${f.day(end)}`
        : `${Number(start.slice(8, 10))} – ${f.day(end)}`;
  return t.zones.week(isoWeek(start), range);
}
