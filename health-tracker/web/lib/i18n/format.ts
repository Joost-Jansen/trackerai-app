// Numbers, units, dates and plurals per locale. Dutch: 5,3 km, 28,4 km/u, "4 okt 2026". English (en-GB): 5.3 km,
// 28.4 km/h, "4 Oct 2026". Times (1:05, 5:08/km) look the same in both.

import { effortKind } from "@/lib/sports";
import { INTL, type Locale } from "./locale";

export type Forms = { one: string; other: string };

/** "# activiteit" / "# activiteiten": `#` becomes the number, formatted for the locale. */
export function plural(locale: Locale, n: number, forms: Forms): string {
  const rule = new Intl.PluralRules(INTL[locale]).select(n);
  const text = rule === "one" ? forms.one : forms.other;
  return text.replace("#", new Intl.NumberFormat(INTL[locale]).format(n));
}

const pad = (n: number) => String(n).padStart(2, "0");

/** "2026-10-04" as local noon (no time zone surprises); timestamps ("2026-10-04 06:02", ISO) as they are. */
export function toDate(iso: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return new Date(`${iso}T12:00:00`);
  if (/^\d{4}-\d{2}$/.test(iso)) return new Date(`${iso}-15T12:00:00`);
  return new Date(iso.includes("T") ? iso : iso.replace(" ", "T"));
}

export type Intensity = { sport: string; moving_time_s?: number; distance_km?: number };

export function makeFormat(locale: Locale) {
  const tag = INTL[locale];
  const numbers = new Map<string, Intl.NumberFormat>();
  const nf = (min: number, max: number) => {
    const key = `${min}-${max}`;
    let f = numbers.get(key);
    if (!f) numbers.set(key, (f = new Intl.NumberFormat(tag, { minimumFractionDigits: min, maximumFractionDigits: max })));
    return f;
  };
  const dateWith = (o: Intl.DateTimeFormatOptions) => (iso: string | null | undefined) => {
    if (!iso) return "–";
    const d = toDate(iso);
    // en-GB writes "Sept"; the charts' time axis says "Sep", keep one spelling.
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(tag, o).replace(/\.(?=\s|$)/g, "").replace(/\bSept\b/, "Sep");
  };
  const clock = (seconds?: number | null) => {
    if (seconds == null) return "–";
    const s = Math.round(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
  };
  const kmhUnit = locale === "nl" ? "km/u" : "km/h";
  const hourUnit = locale === "nl" ? "u" : "h";

  const f = {
    locale,
    tag,
    /** Fixed number of decimals: 5,30 / 5.30. */
    num: (v: number | null | undefined, digits = 0) => (v == null || Number.isNaN(v) ? "–" : nf(digits, digits).format(v)),
    /** Up to `digits` decimals, no trailing zero: 5 / 5,3. */
    trim: (v: number | null | undefined, digits = 1) => (v == null || Number.isNaN(v) ? "–" : nf(0, digits).format(v)),
    /** Number typed by the user: accepts a comma or a point. */
    parse: (v: string) => (v.trim() === "" ? null : Number(v.trim().replace(",", "."))),
    /** A number as it stands in an input field. */
    input: (v: number | null | undefined) => (v == null ? "" : locale === "nl" ? String(v).replace(".", ",") : String(v)),
    km: (v?: number | null, digits = 1) => (v == null ? "–" : `${nf(digits, digits).format(v)} km`),
    kmhUnit,
    kmh: (v?: number | null) => (v ? `${nf(1, 1).format(v)} ${kmhUnit}` : "–"),
    hourUnit,
    /** "1:05" (h:mm) for a total time. */
    duration: (seconds?: number) => {
      if (!seconds) return "0:00";
      const m = Math.round(seconds / 60);
      return `${Math.floor(m / 60)}:${pad(m % 60)}`;
    },
    /** "1:05 u" / "1:05 h". */
    hours: (seconds?: number) => `${f.duration(seconds)} ${hourUnit}`,
    /** "1:02:03" or "5:08". */
    clock,
    /** "5:08/km". */
    pace: (sPerKm?: number | null) => (sPerKm ? `${clock(sPerKm)}/km` : "–"),
    /** Pace on foot, per 100 m for swimming, per 500 m for rowing, speed for the rest (lib/sports.ts effortKind). */
    intensity: (a: Intensity) => {
      if (!a.moving_time_s || !a.distance_km) return "–";
      const kind = effortKind(a.sport);
      if (kind === "speed") return f.kmh((a.distance_km / a.moving_time_s) * 3600);
      if (kind === "swim") return `${clock(Math.round(a.moving_time_s / (a.distance_km * 10)))}/100m`;
      if (kind === "row") return `${clock(Math.round(a.moving_time_s / (a.distance_km * 2)))}/500m`;
      return f.pace(Math.round(a.moving_time_s / a.distance_km));
    },
    /** "4 okt 2026" / "4 Oct 2026". */
    day: dateWith({ day: "numeric", month: "short", year: "numeric" }),
    /** "4 okt 26". */
    dayShortYear: dateWith({ day: "numeric", month: "short", year: "2-digit" }),
    /** "4 okt". */
    dayMonth: dateWith({ day: "numeric", month: "short" }),
    /** "zo 4 okt" / "Sun 4 Oct". */
    weekdayDay: dateWith({ weekday: "short", day: "numeric", month: "short" }),
    /** "zo, 4 oktober 2026" style for log entries. */
    weekdayDayYear: dateWith({ weekday: "short", day: "numeric", month: "long", year: "numeric" }),
    /** "zo" / "Sun". */
    weekday: dateWith({ weekday: "short" }),
    /** "zondag 4 oktober". */
    long: dateWith({ weekday: "long", day: "numeric", month: "long" }),
    /** "oktober 2026". */
    month: dateWith({ month: "long", year: "numeric" }),
    /** "okt 26". */
    monthShortYear: dateWith({ month: "short", year: "2-digit" }),
    /** "okt". */
    monthShort: dateWith({ month: "short" }),
    /** Any date with Intl options, e.g. { weekday: "long" }. */
    date: (iso: string | null | undefined, o: Intl.DateTimeFormatOptions) => dateWith(o)(iso),
    /** "4 okt 2026, 06:02". */
    dateTime: dateWith({ day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }),
    /** "a, b en c" / "a, b and c". */
    list: (items: string[]) => new Intl.ListFormat(tag, { type: "conjunction" }).format(items),
    plural: (n: number, forms: Forms) => plural(locale, n, forms),
  };
  return f;
}

export type Format = ReturnType<typeof makeFormat>;
