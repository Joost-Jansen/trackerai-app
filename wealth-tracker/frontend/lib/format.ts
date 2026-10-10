// Number and date formatting in the reader's language: Dutch (1.234,56, "17 jun") or English (1,234.56,
// "17 Jun"). Dutch is also what runs without a browser (tests, the server).
//
// The Dutch format is a faithful port of charts.py's fmt_eu.
//
// A faithful port of charts.py's fmt_eu, which every Streamlit screen and
// every Plotly figure already formats with — the figures arrive here as JSON
// with their labels pre-formatted by it, so anything this file renders sits
// directly next to its output and has to agree with it exactly:
//
//   body = f"{value:,.{decimals}f}".translate(_EU_SWAP)
//   lead = "+" if (plus and value >= 0) else ""
//   return f"{lead}{prefix}{body}{suffix}"
//
// Intl.NumberFormat produces the body (locale-correct separators, no manual
// string surgery), but not the whole string: its `style: "currency"` inserts a
// U+00A0 between the sign and the amount ("€ 13.363,06") where fmt_eu emits
// none ("€13.363,06"), and it puts a minus before the symbol where fmt_eu
// leaves it after ("€-19,31"). Hence prefix/suffix by hand — matching the
// backend beats matching CLDR here.

type EuOptions = {
  decimals?: number;
  prefix?: string;
  suffix?: string;
  plus?: boolean;
};

import { intlLocale, locale } from "./i18n/locale";
import { tr } from "./i18n/tr";

// One formatter per decimal count actually used (1, 2, 4 across app.py);
// constructing an Intl.NumberFormat per call is measurably slower in tables.
const bodyFormatters = new Map<number, Intl.NumberFormat>();

function formatterFor(decimals: number): Intl.NumberFormat {
  let fmt = bodyFormatters.get(decimals);
  if (!fmt) {
    fmt = new Intl.NumberFormat(intlLocale, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      useGrouping: true,
      // Python's format spec rounds half to even; Intl defaults to halfExpand,
      // which alone would print 0,13 where Streamlit prints 0,12 for 0.125.
      roundingMode: "halfEven",
    });
    bodyFormatters.set(decimals, fmt);
  }
  return fmt;
}

function body(value: number, decimals: number): string {
  // Handing Intl the number would let it round the *shortest decimal
  // representation* of the double, but Python rounds the double's exact binary
  // value — so 2.675, actually 2.67499...82, prints as 2,67 in Streamlit and
  // would print as 2,68 here. toFixed emits that exact expansion, and Intl
  // accepts a string and rounds it without ever going back through a float.
  //
  // 100 (toFixed's maximum) rather than a comfortable 20: the digits that decide
  // a rounding sit at the value's own scale, not at a fixed offset. 5e-05 is
  // really 5.000...0024e-05, but its first 20 decimals read as an exact tie, so
  // half-even rounded it down to 0,0000 where Streamlit prints 0,0001.
  const exact = Object.is(value, -0)
    ? "-0" // toFixed drops the sign; Intl keeps it, and fmt_eu prints "-0,00"
    : value.toFixed(100);
  // format() takes `${number}`, a template literal type no plain string widens
  // to; toFixed on a finite double always produces one. Guarded above: NaN and
  // null already returned, and no caller passes ±Infinity.
  return formatterFor(decimals).format(exact as `${number}`);
}

export function fmtEu(value: number | null | undefined, opts: EuOptions = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const { decimals = 2, prefix = "", suffix = "", plus = false } = opts;
  // `value >= 0` is deliberate rather than a sign check: it mirrors fmt_eu, and
  // it means -0.0 (which real data does produce — a fully closed position with
  // no gain) takes the same branch in both, rendering "-0,00", not "+0,00".
  const lead = plus && value >= 0 ? "+" : "";
  return `${lead}${prefix}${body(value, decimals)}${suffix}`;
}

export function fmtEuro(value: number | null | undefined, opts: Omit<EuOptions, "prefix" | "suffix"> = {}): string {
  return fmtEu(value, { ...opts, prefix: "€" });
}

export function fmtPercent(value: number | null | undefined, opts: Omit<EuOptions, "prefix" | "suffix"> = {}): string {
  return fmtEu(value, { ...opts, suffix: "%" });
}

export function fmtNumber(value: number | null | undefined, opts: Omit<EuOptions, "prefix" | "suffix"> = {}): string {
  return fmtEu(value, opts);
}

// ---------------------------------------------------------------------------
// Dates & relative time ("2 min ago", "yesterday", "14 Aug"). Backend timestamps
// arrive as "2026-07-16 23:15:47" (sqlite, local time) or full ISO —
// parseTimestamp accepts both.
// ---------------------------------------------------------------------------

// Written out rather than from Intl: Intl's Dutch short months carry a dot ("mrt.").
const MONTHS: Record<string, string[]> = {
  nl: ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};
const SHORT_MONTHS = MONTHS[locale];

/** "jan" / "Jan" — the short name of month 1–12. */
export const monthAbbr = (month: number): string => SHORT_MONTHS[month - 1] ?? String(month);

/** "ma" … "zo" / "Mon" … "Sun": the short weekday names, Monday first. */
export const WEEKDAY_ABBR: string[] = locale === "nl"
  ? ["ma", "di", "wo", "do", "vr", "za", "zo"]
  : ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** "januari" / "January" — the full name of month 1–12. */
export const monthName = (month: number): string =>
  new Intl.DateTimeFormat(intlLocale, { month: "long" }).format(new Date(2000, month - 1, 15));

export function parseTimestamp(ts: string): Date | null {
  const d = new Date(ts.includes("T") ? ts : ts.replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "17 jun" / "17 Jun" — day + month abbreviation. */
export function fmtDayMonth(ts: string): string {
  const d = parseTimestamp(ts);
  if (!d) return ts;
  return `${d.getDate()} ${SHORT_MONTHS[d.getMonth()]}`;
}

/** "14:35" — clock time in the reader's time zone, for the intraday axis. */
export function fmtTime(ts: string): string {
  const d = parseTimestamp(ts);
  if (!d) return ts;
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * "9:00" within the day itself, "previous close" for the point of the previous session.
 *
 *  The intraday line starts at yesterday's close — that is what the day is
 *  measured against — and labelling that point "17:25" next to today's "17:25"
 *  reads as a mistake instead of as a reference.
 */
export function fmtIntradayLabel(ts: string, sessionOf: string): string {
  const a = parseTimestamp(ts);
  const b = parseTimestamp(sessionOf);
  if (!a || !b) return fmtTime(ts);
  return a.toDateString() === b.toDateString() ? fmtTime(ts) : tr("previous close");
}

/** "27 Feb 2023" — day + month + year, for spans over several years. */
export function fmtDayMonthYear(ts: string): string {
  const d = parseTimestamp(ts);
  if (!d) return ts;
  return `${d.getDate()} ${SHORT_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "just now" / "5 min ago" / "3 hours ago" / "yesterday" / "4 days ago" / "14 May". */
export function fmtRelative(ts: string, now: Date = new Date()): string {
  const d = parseTimestamp(ts);
  if (!d) return ts;
  const seconds = (now.getTime() - d.getTime()) / 1000;
  if (seconds < 60) return tr("just now");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return tr("{0} min ago", minutes);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return tr("{0} hours ago", hours);
  const days = Math.floor(hours / 24);
  if (days === 1) return tr("yesterday");
  if (days < 30) return tr("{0} days ago", days);
  return fmtDayMonth(ts);
}

/** "sep" / "Sep" — month abbreviation from an ISO date or "YYYY-MM" string. */
export function fmtMonth(iso: string): string {
  const m = parseInt(iso.slice(5, 7), 10);
  return m >= 1 && m <= 12 ? SHORT_MONTHS[m - 1] : iso;
}

/** "in 4 days" / "today" / "tomorrow" — for upcoming ex-dividend dates. */
export function fmtUntil(iso: string, now: Date = new Date()): string {
  const d = parseTimestamp(iso);
  if (!d) return iso;
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(d) - startOf(now)) / 86400000);
  if (days <= 0) return tr("today");
  if (days === 1) return tr("tomorrow");
  return tr("in {0} days", days);
}

// Share counts print via f"{v:g}" in app.py, not fmt_eu: significant-digit
// formatting that drops trailing zeros, so 10.0 -> "10" and 0.5 -> "0,5".
// Only the decimal separator is swapped there, and %g switches to exponent
// form beyond 6 significant digits — reproduced here rather than approximated
// with toLocaleString, which would group thousands and never use exponents.
export function fmtShares(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  let s: string;
  const exp = value === 0 ? 0 : Math.floor(Math.log10(Math.abs(value)));
  if (exp < -4 || exp >= 6) {
    // %g pads the exponent to two digits ("1e+06"); toExponential does not
    // ("1e+6"). Unreachable for any sane share count, but free to get right.
    s = value
      .toExponential(5)
      .replace(/\.?0+e/, "e")
      .replace(/e([+-])(\d)$/, "e$10$2");
  } else {
    s = String(parseFloat(value.toPrecision(6)));
  }
  return locale === "nl" ? s.replace(".", ",") : s;
}

/** A plain number in the reader's language, e.g. 1.234 / 1,234 or 12,5 / 12.5. */
export const fmtInt = (value: number, maximumFractionDigits = 0): string =>
  value.toLocaleString(intlLocale, { maximumFractionDigits });
