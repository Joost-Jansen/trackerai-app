// Shared helpers for the Plan page and the plan editor (T24): dates in the local time zone, weeks and days,
// the race from the plan, colours per sport and status.

import type { Format } from "@/lib/i18n";
import { sportGroup } from "@/lib/sports";
import type { PlanSession, PlanWeek, SessionStatus } from "@/lib/training";

/** The sports the editor offers (api/plans.py SPORTS reads more names); any sport code of lib/sports.ts works. */
export const PLAN_SPORTS = ["run", "ride", "swim", "strength_training", "walking", "hiking", "yoga", "rest"] as const;
export type PlanSport = (typeof PLAN_SPORTS)[number];

/** The same sport colours as on Trends. */
export const SPORT_COLOUR: Record<string, string> = {
  run: "var(--chart-1)",
  ride: "var(--chart-4)",
  swim: "var(--chart-3)",
  strength_training: "var(--chart-5)",
  rest: "var(--text-faint)",
};
/** E-bike and hand cycling in the cycling colour; every other sport in clay. */
export const sportColour = (s: string) => SPORT_COLOUR[s] ?? (sportGroup(s) === "ride" ? SPORT_COLOUR.ride : "var(--chart-6)");

/** Zones the API understands (parse_zone): one zone or a range. */
export const ZONE_OPTIONS = ["Z1", "Z2", "Z3", "Z4", "Z5", "Z1-Z2", "Z2-Z3", "Z3-Z4", "Z4-Z5"];

/** Colour per status; the names are in lib/i18n (plan.statuses), kinds of workout as suggestions in plan.kinds. */
export const STATUS_TONE: Record<SessionStatus, "gain" | "loss" | "brand" | "neutral"> = {
  done: "gain",
  missed: "loss",
  today: "brand",
  planned: "neutral",
  rest: "neutral",
};

const pad = (n: number) => String(n).padStart(2, "0");

/** YYYY-MM-DD in the browser's time zone (not UTC: at 00:30 it is already the new day). */
export function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export const todayIso = () => isoLocal(new Date());

export function parseIso(day: string): Date {
  return new Date(day.slice(0, 10) + "T12:00:00");
}

export function addDays(day: string, n: number): string {
  const d = parseIso(day);
  d.setDate(d.getDate() + n);
  return isoLocal(d);
}

/** Monday of the week of `day`. */
export function weekOf(day: string): string {
  const d = parseIso(day);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return isoLocal(d);
}

export function daysBetween(from: string, to: string): number {
  return Math.round((parseIso(to).getTime() - parseIso(from).getTime()) / 86_400_000);
}

export const isValidIso = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(parseIso(s).getTime()) && isoLocal(parseIso(s)) === s;

/** "28 sep – 4 okt" / "28 Sep – 4 Oct" */
export function fmtWeekRange(monday: string, f: Format): string {
  return `${f.dayMonth(monday)} – ${f.dayMonth(addDays(monday, 6))}`;
}

const MONTHS: Record<string, number> = { jan: 1, feb: 2, mrt: 3, mar: 3, apr: 4, mei: 5, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, okt: 10, oct: 10, nov: 11, dec: 12 };

/** Date from free text: 2026-10-18, 18-10-2026, 18/10 or 18 okt (2026). */
export function findDate(text: string, year: number): { iso: string; match: string } | null {
  let m = text.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return { iso: `${m[1]}-${pad(+m[2])}-${pad(+m[3])}`, match: m[0] };
  m = text.match(/\b(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?\b/);
  if (m) {
    const y = m[3] ? (+m[3] < 100 ? +m[3] + 2000 : +m[3]) : year;
    return { iso: `${y}-${pad(+m[2])}-${pad(+m[1])}`, match: m[0] };
  }
  m = text.toLowerCase().match(/\b(\d{1,2})\s+([a-z]{3})[a-z]*\.?(?:\s+(\d{4}))?/);
  if (m && MONTHS[m[2]]) return { iso: `${m[3] ?? year}-${pad(MONTHS[m[2]])}-${pad(+m[1])}`, match: m[0] };
  return null;
}

/** Race name and date from the free field `race` ("Marathon, 2026-10-18"). */
export function splitRace(race: string | null | undefined, year = new Date().getFullYear()): { name: string; date: string | null } {
  const text = (race ?? "").trim();
  if (!text) return { name: "", date: null };
  const found = findDate(text, year);
  if (!found || !isValidIso(found.iso)) return { name: text, date: null };
  const name = text.replace(found.match, "").replace(/\s*[,·–-]\s*$/, "").replace(/^\s*[,·–-]\s*/, "").replace(/\s{2,}/g, " ").trim();
  return { name, date: found.iso };
}

/** Back to one field, the way agents write it too. */
export function joinRace(name: string, date: string): string {
  return [name.trim(), date].filter(Boolean).join(", ");
}

/** Whole words, not a pace ("marathontempo", "race pace"); the same rule as api/dashboard.py RACE_KIND. */
export const RACE_KIND = /\b(wedstrijd|race|marathon|triathlon)\b(?!\s*-?\s*(tempo|pace))/i;

/** The plan's race: date from the race field, otherwise the last session of kind race (empty name:
 *  the page then says "the race" in the user's language). */
export function planRace(race: string | null | undefined, sessions: PlanSession[]): { name: string; date: string | null } {
  const year = sessions[0] ? parseIso(sessions[0].date).getFullYear() : new Date().getFullYear();
  const r = splitRace(race, year);
  if (r.date) return r;
  const s = [...sessions].reverse().find((x) => RACE_KIND.test(x.kind ?? ""));
  return { name: r.name, date: s?.date ?? null };
}

/** `outside`: before the first or after the last session of the plan (not a rest day, the plan is not running then). */
export type Day = { date: string; sessions: PlanSession[]; outside?: boolean };
/** `km`: per sport planned against done, done being every activity of that sport that week (from the API). */
export type Week = { monday: string; days: Day[]; sessions: PlanSession[]; km: Record<string, { planned: number; done: number }> };

/** All weeks of the plan, every week with seven days (empty ones too), sessions per day in order. */
export function buildWeeks(sessions: PlanSession[], planWeeks: PlanWeek[] = []): Week[] {
  if (!sessions.length) return [];
  const sorted = [...sessions].sort((a, b) => a.date.localeCompare(b.date));
  const first = weekOf(sorted[0].date);
  const last = weekOf(sorted[sorted.length - 1].date);
  const weeks: Week[] = [];
  for (let monday = first; monday <= last; monday = addDays(monday, 7)) {
    const days = Array.from({ length: 7 }, (_, i) => {
      const date = addDays(monday, i);
      return { date, sessions: sorted.filter((s) => s.date === date), outside: date < sorted[0].date || date > sorted[sorted.length - 1].date };
    });
    const own = days.flatMap((d) => d.sessions);
    const api = planWeeks.find((w) => w.week === monday)?.sports;
    const km = api
      ? Object.fromEntries(Object.entries(api).map(([sport, v]) => [sport, { planned: v.planned_km, done: v.done_km }]))
      : kmBySport(own);
    weeks.push({ monday, days, sessions: own, km });
  }
  return weeks;
}

/** Kilometres per sport, planned and done by the sessions alone. Sessions without a distance do not count. */
export function kmBySport(sessions: PlanSession[]): Record<string, { planned: number; done: number }> {
  const out: Record<string, { planned: number; done: number }> = {};
  for (const s of sessions) {
    if (s.sport === "rest") continue;
    const row = (out[s.sport] ??= { planned: 0, done: 0 });
    row.planned += s.distance_km ?? 0;
    if (s.status === "done") row.done += s.done?.distance_km ?? 0;
  }
  return out;
}

export const capitalise = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
