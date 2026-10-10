// Time windows and a time axis for the charts on Trends.
//
// periodWindow and moveWindow, plus what a chart with a real time axis needs: day numbers
// as x, ticks that fit the width, and a moving average.
//
// A date is "YYYY-MM-DD" everywhere. Calculations happen in day numbers (days since
// 1970-01-01, UTC), so daylight saving time never produces a 23-hour day.

export type DateWindow = { from: string; to: string };
export type DayPoint = { d: string; v: number };

export const PERIODS = ["4W", "3M", "6M", "YTD", "1J", "Alles"];
export const CUSTOM = "Eigen";
export const DEFAULT_PERIOD = "6M";
/** Zooming in to less than a week makes no sense for daily and weekly series. */
export const MIN_SPAN_DAYS = 7;

const MONTHS: Record<string, number> = { "3M": 3, "6M": 6, "1J": 12 };
const DAY = 86400000;
export const NL_MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
const NL_WEEKDAYS = ["zo", "ma", "di", "wo", "do", "vr", "za"];
const EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const EN_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
/** Labels in the user's language (lib/i18n useLocale); Dutch when not given. */
export type TimeLocale = "nl" | "en";
const MONTHS_OF: Record<TimeLocale, string[]> = { nl: NL_MONTHS, en: EN_MONTHS };
const WEEKDAYS_OF: Record<TimeLocale, string[]> = { nl: NL_WEEKDAYS, en: EN_WEEKDAYS };

export const dayNumber = (d: string) => Date.parse(`${d.slice(0, 10)}T00:00:00Z`) / DAY;
export const isoDay = (n: number) => new Date(Math.round(n) * DAY).toISOString().slice(0, 10);

const later = (a: string, b: string) => (a > b ? a : b);

/** The window of a period up to and including `last`, never before `first`. */
export function periodWindow(period: string, first: string, last: string): DateWindow {
  if (period === "Alles") return { from: first, to: last };
  if (period === "4W") return { from: later(first, isoDay(dayNumber(last) - 27)), to: last };
  if (period === "YTD") return { from: later(first, `${last.slice(0, 4)}-01-01`), to: last };
  const months = MONTHS[period] ?? 6;
  const date = new Date(`${last}T00:00:00Z`);
  const originalDay = date.getUTCDate();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() - months);
  const monthEnd = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(originalDay, monthEnd));
  return { from: later(first, isoDay(date.getTime() / DAY + 1)), to: last };
}

/** A window in day numbers (may be fractional while dragging). */
export type DayRange = { a: number; b: number };

export const toRange = (w: DateWindow): DayRange => ({ a: dayNumber(w.from), b: dayNumber(w.to) });
export const toWindow = (r: DayRange): DateWindow => ({ from: isoDay(r.a), to: isoDay(r.b) });

/** Keep within [lo, hi], at least MIN_SPAN_DAYS wide (or the whole data when that is shorter). */
export function clampRange(r: DayRange, lo: number, hi: number, minSpan = MIN_SPAN_DAYS): DayRange {
  const full = hi - lo;
  const span = Math.min(full, Math.max(minSpan, r.b - r.a));
  let a = r.a;
  if (r.b - r.a < span) a = (r.a + r.b) / 2 - span / 2;
  a = Math.max(lo, Math.min(hi - span, a));
  return { a, b: a + span };
}

/** Zoom around a fixed point (the mouse, the midpoint of two fingers): that point stays put. */
export function zoomRange(r: DayRange, factor: number, anchor: number, lo: number, hi: number): DayRange {
  const a = anchor - (anchor - r.a) * factor;
  const b = anchor + (r.b - anchor) * factor;
  return clampRange({ a, b }, lo, hi);
}

export function panRange(r: DayRange, delta: number, lo: number, hi: number): DayRange {
  const span = r.b - r.a;
  const a = Math.max(lo, Math.min(hi - span, r.a + delta));
  return { a, b: a + span };
}

/** Pan and zoom with buttons, in whole days: scale 0.5 is zooming in, direction ±1 one window further. */
export function moveWindow(w: DateWindow, first: string, last: string, scale: number, direction = 0): DateWindow {
  const lo = dayNumber(first);
  const hi = dayNumber(last);
  const r = toRange(w);
  const span = r.b - r.a;
  const centre = (r.a + r.b) / 2 + direction * span;
  const next = clampRange({ a: centre - (span * scale) / 2, b: centre + (span * scale) / 2 }, lo, hi);
  return { from: isoDay(Math.round(next.a)), to: isoDay(Math.round(next.b)) };
}

// ── Labels ────────────────────────────────────────────────────────────────────

const parts = (d: string) => ({ y: Number(d.slice(0, 4)), m: Number(d.slice(5, 7)) - 1, day: Number(d.slice(8, 10)) });

/** "7 sep 2026", or "7 sep" without a year. */
export function fmtDate(d: string, year = true, locale: TimeLocale = "nl"): string {
  const p = parts(d);
  return `${p.day} ${MONTHS_OF[locale][p.m]}${year ? ` ${p.y}` : ""}`;
}

/** "ma 7 sep 2026". */
export function fmtWeekday(d: string, locale: TimeLocale = "nl"): string {
  return `${WEEKDAYS_OF[locale][new Date(`${d}T00:00:00Z`).getUTCDay()]} ${fmtDate(d, true, locale)}`;
}

/** "3 mrt – 1 jun 2026", or with two years across a year boundary. */
export function fmtWindow(w: DateWindow, locale: TimeLocale = "nl"): string {
  const same = w.from.slice(0, 4) === w.to.slice(0, 4);
  return `${fmtDate(w.from, !same, locale)} – ${fmtDate(w.to, true, locale)}`;
}

/** Number of days in the window, both bounds included. */
export const windowDays = (w: DateWindow) => dayNumber(w.to) - dayNumber(w.from) + 1;

// ── Time axis ─────────────────────────────────────────────────────────────────

export type TimeTick = { day: number; label: string; major: boolean };

type Unit = { kind: "day" | "week" | "month" | "year"; step: number };
const UNITS: Unit[] = [
  { kind: "day", step: 1 },
  { kind: "day", step: 2 },
  { kind: "week", step: 1 },
  { kind: "week", step: 2 },
  { kind: "month", step: 1 },
  { kind: "month", step: 2 },
  { kind: "month", step: 3 },
  { kind: "month", step: 6 },
  { kind: "year", step: 1 },
  { kind: "year", step: 2 },
  { kind: "year", step: 5 },
];

// 11px tabular digits and lower case: a little over 6px per character.
const CHAR_PX = 6.4;
const TICK_GAP_PX = 14;

function ticksFor(unit: Unit, a: number, b: number, locale: TimeLocale = "nl"): TimeTick[] {
  const out: TimeTick[] = [];
  const first = Math.ceil(a);
  const last = Math.floor(b);
  if (unit.kind === "day" || unit.kind === "week") {
    // 1970-01-05 (day 4) was a Monday.
    const period = unit.kind === "day" ? unit.step : 7 * unit.step;
    const offset = unit.kind === "day" ? 0 : 4;
    let n = first + ((((offset - first) % period) + period) % period);
    for (; n <= last; n += period) {
      const d = isoDay(n);
      const p = parts(d);
      // The first of the month or a Monday after a month change already carries the month; the year is
      // on 1 January so a window across the year boundary can be read.
      out.push({ day: n, label: p.m === 0 && p.day <= period ? `${p.day} ${MONTHS_OF[locale][0]} ${p.y}` : fmtDate(d, false, locale), major: p.day <= period });
    }
    return out;
  }
  const start = parts(isoDay(first));
  let y = start.y;
  let m = start.m;
  if (unit.kind === "year") m = 0;
  for (;;) {
    const n = Date.UTC(y, m, 1) / DAY;
    if (n > last) break;
    const monthIndex = y * 12 + m;
    const take = unit.kind === "year" ? m === 0 && y % unit.step === 0 : monthIndex % unit.step === 0;
    if (n >= first && take) {
      out.push(
        unit.kind === "year" || m === 0
          ? { day: n, label: String(y), major: true }
          : { day: n, label: MONTHS_OF[locale][m], major: false },
      );
    }
    if (unit.kind === "year") y += 1;
    else if (++m === 12) {
      m = 0;
      y += 1;
    }
  }
  return out;
}

/**
 * Ticks for the window [a, b] (day numbers) at `width` pixels: the finest
 * unit (day, week, month, quarter, year) at which no two labels touch.
 * Months are called "sep", January carries the year.
 */
export function timeTicks(a: number, b: number, width: number, locale: TimeLocale = "nl"): TimeTick[] {
  const span = Math.max(b - a, 1);
  const pxPerDay = width / span;
  for (const unit of UNITS) {
    const ticks = ticksFor(unit, a, b, locale);
    if (ticks.length < 2 && unit.kind !== "year") continue;
    const widest = Math.max(...ticks.map((t) => t.label.length), 3) * CHAR_PX;
    const approxGap = { day: 1, week: 7, month: 30.4, year: 365.25 }[unit.kind] * unit.step * pxPerDay;
    // A month step is not equally long everywhere (February): calculating with 28 days keeps that one clear too.
    const minGap = unit.kind === "month" ? approxGap * (28 / 30.4) : approxGap;
    if (minGap >= widest + TICK_GAP_PX) return ticks;
  }
  return ticksFor({ kind: "year", step: 10 }, a, b, locale);
}

// ── Series ────────────────────────────────────────────────────────────────────

/** The median distance between two points, in days: 1 for a daily series, 7 for a weekly series. */
export function typicalStep(points: DayPoint[]): number {
  if (points.length < 2) return 1;
  const gaps: number[] = [];
  for (let i = 1; i < points.length; i++) gaps.push(dayNumber(points[i].d) - dayNumber(points[i - 1].d));
  gaps.sort((x, y) => x - y);
  return Math.max(1, gaps[Math.floor(gaps.length / 2)]);
}

/**
 * Moving average over the last `days` days (by time, not by number of points:
 * a missing day does not count as zero). Starts only once the window can be
 * completely filled for the first time, so the start does not lean on a
 * handful of points.
 */
export function movingAverage(points: DayPoint[], days: number): DayPoint[] {
  if (points.length === 0 || days <= 1) return points;
  const step = typicalStep(points);
  const t = points.map((p) => dayNumber(p.d));
  const out: DayPoint[] = [];
  let lo = 0;
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    sum += points[i].v;
    while (t[lo] <= t[i] - days) sum -= points[lo++].v;
    if (t[i] - t[0] >= days - step) out.push({ d: points[i].d, v: sum / (i - lo + 1) });
  }
  return out;
}

/** Least squares over the points, as two end points. */
export function linearTrend(points: DayPoint[]): DayPoint[] {
  if (points.length < 3) return [];
  const t = points.map((p) => dayNumber(p.d));
  const n = points.length;
  const mx = t.reduce((s, v) => s + v, 0) / n;
  const my = points.reduce((s, p) => s + p.v, 0) / n;
  let num = 0;
  let den = 0;
  t.forEach((x, i) => {
    num += (x - mx) * (points[i].v - my);
    den += (x - mx) ** 2;
  });
  const slope = den ? num / den : 0;
  return [
    { d: points[0].d, v: my + slope * (t[0] - mx) },
    { d: points[n - 1].d, v: my + slope * (t[n - 1] - mx) },
  ];
}

/** Index of the first point with day number >= day (binary search over ascending days). */
export function lowerBound(days: number[], day: number): number {
  let lo = 0;
  let hi = days.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (days[mid] < day) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Index of the point closest to `day`, or -1 for an empty series. */
export function nearestIndex(days: number[], day: number): number {
  if (days.length === 0) return -1;
  const i = lowerBound(days, day);
  if (i === 0) return 0;
  if (i === days.length) return days.length - 1;
  return day - days[i - 1] <= days[i] - day ? i - 1 : i;
}
