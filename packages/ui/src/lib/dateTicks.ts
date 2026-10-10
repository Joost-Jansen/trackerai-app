// Dates along the bottom of a time chart, at round moments. Shared by every line chart of both apps, so they all read
// the same way.

import { dayNumber, isoDay, monthAbbr as abbr, type Locale } from "@trackerai/ui/lib/dates";

/**
 * Dates along the bottom at round moments: days, Mondays, the 1st of a month or
 * New Year, whichever gives a readable number of labels for the width.
 */
export function dateTicks(first: string, last: string, width: number, locale: Locale): { d: string; label: string }[] {
  const monthAbbr = (m: number) => abbr(locale, m);
  const start = dayNumber(first);
  const end = dayNumber(last);
  const span = end - start;
  const room = Math.max(2, Math.floor(width / 84));
  const out: { d: string; label: string }[] = [];
  const dayLabel = (d: string) => `${Number(d.slice(8, 10))} ${monthAbbr(Number(d.slice(5, 7)))}`;
  if (span <= 120) {
    // Days, every n days, or Mondays every n weeks.
    const weekly = span > room * 2;
    const step = weekly ? 7 * Math.max(1, Math.ceil(span / 7 / room)) : Math.max(1, Math.ceil(span / room));
    let n = start;
    if (weekly) while (new Date(n * 86400000).getUTCDay() !== 1) n++;
    for (; n <= end; n += step) out.push({ d: isoDay(n), label: dayLabel(isoDay(n)) });
    return out;
  }
  const months = span <= 800;
  const every = months ? Math.max(1, Math.ceil(span / 30.4 / room)) : Math.max(1, Math.ceil(span / 365.25 / room));
  const firstDate = new Date(start * 86400000);
  let year = firstDate.getUTCFullYear();
  let month = months ? firstDate.getUTCMonth() + 1 : 0;
  for (let i = 0; i < 400; i++) {
    if (months) { month += 1; if (month > 12) { month = 1; year += 1; } }
    else year += 1;
    const d = `${year}-${String(months ? month : 1).padStart(2, "0")}-01`;
    if (dayNumber(d) > end) break;
    const index = months ? year * 12 + month : year;
    if (index % every) continue;
    out.push({ d, label: months ? (month === 1 || out.length === 0 ? `${monthAbbr(month)} '${String(year).slice(2)}` : monthAbbr(month)) : String(year) });
  }
  return out;
}


/**
 * Where each tick lands on a chart whose x follows the index of its points (not
 * time): the first point on or after the tick's day, as a fraction 0..1.
 */
export function tickFractions(days: string[], width: number, locale: Locale): { label: string; f: number }[] {
  if (days.length < 2) return [];
  const out: { label: string; f: number }[] = [];
  let i = 0;
  for (const t of dateTicks(days[0], days[days.length - 1], width, locale)) {
    while (i < days.length - 1 && days[i] < t.d) i++;
    out.push({ label: t.label, f: i / (days.length - 1) });
  }
  return out;
}
