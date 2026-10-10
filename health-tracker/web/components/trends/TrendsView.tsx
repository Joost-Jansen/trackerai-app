"use client";

// Trends, in three tabs, each its own address (the tabs sit in the top bar, lib/nav.ts):
//   /trends/              training: what you do and what it does to your fitness: insights (on your own goal from the plan), form,
//                         VO2max, volume per week per sport, time per zone over time and Z2 pace;
//   /trends/performance/  what you can do and did in a race: predicted race times, longest run per week, records
//                         and races;
//   /trends/recovery/     the body: recovery per day or week against your own normal (with HRV when available).
// Training ends with "Training and body" (TrainingBody): sport and body values on one date axis. A day clicked in a
// chart opens it under Today, Sleep & body (/dashboard/body/?day=…).
//
// One time window for the whole page (TimeFilterBar, sticks under the top bar; lives in the address bar), and one
// sport filter (also in the address bar). Every chart shares that time axis; panning or zooming in one chart moves the
// window for all. Running cards (pace, records, predictions) only show with "Alle sporten" (all sports) or
// "Hardlopen" (running). All text comes from lib/texts.ts (T.trends).

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Tabs } from "@/components/ds";
import TimeChart, { DAILY_MA, WEEKLY_MA, type ChartSeries } from "@/components/charts/TimeChart";
import TrendChart from "@/components/charts/TrendChart";
import TimeFilterBar from "@/components/timefilter/TimeFilterBar";
import { useTimeRange } from "@/components/timefilter/useTimeRange";
import RecordTable from "@/components/trends/RecordTable";
import SleepStages from "@/components/trends/SleepStages";
import TrainingBody from "@/components/trends/TrainingBody";
import { ALL_SPORTS, useSportFilter } from "@/components/trends/useSportFilter";
import ZonesOverTime from "@/components/zones/ZonesOverTime";
import { api } from "@/lib/api";
import { useFormat, useLocale, useT } from "@/lib/i18n";
import { fmtDate as fmtDateIn } from "@/lib/timeline";
import { type RecordKey, type TrendsPlus, fmtClock } from "@/lib/training";

type RecoveryKey = "resting_hr" | "sleep_h" | "body_battery_high" | "stress_avg" | "hrv" | "sleep_resp" | "sleep_stress" | "bb_charged_sleep" | "spo2_avg";
type RecoveryChart = {
  key: RecoveryKey;
  storage: string;
  title: string;
  label?: string;
  points: { d: string; v: number }[];
  format: (v: number) => string;
  unit?: string;
  lowerIsBetter?: boolean;
  colour: string;
  note?: string;
};
/** Recovery charts shown even without data (they say so); the others only when the watch gives the value. */
const ALWAYS: RecoveryKey[] = ["resting_hr", "sleep_h", "body_battery_high", "stress_avg"];

const MAIN = ["run", "ride", "swim"];
const SPORT_COLOUR: Record<string, string> = { run: "var(--chart-1)", ride: "var(--chart-4)", swim: "var(--chart-3)" };
const RECORD_COLOUR: Record<RecordKey, string> = { "1k": "var(--chart-4)", "5k": "var(--chart-1)", "10k": "var(--chart-3)", "21k": "var(--chart-5)" };
const href = (id: string) => `/history/activity/?id=${encodeURIComponent(id)}`;
const levelColour = (level: string) => (level === "good" ? "var(--zone-2)" : level === "watch" ? "var(--zone-4)" : "var(--zone-1)");

export type TrendsTab = "training" | "performance" | "recovery";

export default function TrendsView({ tab }: { tab: TrendsTab }) {
  const tr = useT();
  const T = tr.texts;
  const TT = T.trends;
  const f = useFormat();
  const { locale } = useLocale();
  const fmtDay = (d: string) => f.day(d);
  const fmtDate = (d: string) => fmtDateIn(d, true, locale);
  const fmtKm = (v: number) => f.km(v);
  const dec = (v: number, digits = 1) => f.num(v, digits);
  const [metric, setMetric] = useState<"hours" | "km">("hours");
  const [picked, setPicked] = useState<string | null>(null); // a day clicked in a recovery chart, to open under Health
  const q = useQuery({ queryKey: ["trends"], queryFn: () => api.get<TrendsPlus>("/api/trends") });
  const { sport, choose: chooseSport, all } = useSportFilter();

  const t = q.data;
  // The window runs from the first measurement (of whatever series) to today.
  const first = useMemo(() => {
    if (!t) return "";
    const starts = [t.form[0]?.date, t.weekly[0]?.week, t.z2_pace[0]?.week, t.vo2max[0]?.date, t.recovery_daily?.[0]?.date, t.recovery_weekly[0]?.week, t.longest_runs?.[0]?.week].filter(Boolean) as string[];
    return starts.length ? starts.sort()[0] : t.today;
  }, [t]);
  const last = t?.today ?? "";
  const range = useTimeRange(first, last);
  const win = range.window;
  const from = win.from;
  const shared = { window: win, domain: { from: first, to: last }, onWindow: range.change, onReset: range.reset };

  // Sports with data, the three main sports first.
  const sports = useMemo(() => {
    const seen = new Set<string>();
    for (const w of t?.weekly ?? []) for (const s of Object.keys(w.sports)) seen.add(s);
    return [...MAIN.filter((s) => seen.has(s)), ...[...seen].filter((s) => !MAIN.includes(s)).sort()];
  }, [t]);
  const running = all || sport === "run";

  const volume = useMemo(() => {
    if (!t) return { series: [] as ChartSeries[], avg: 0, weeks: 0 };
    const val = (v: { km: number; seconds: number }) => (metric === "hours" ? v.seconds / 3600 : v.km);
    const one = (s: string): ChartSeries => ({
      key: s,
      label: tr.sport(s),
      colour: SPORT_COLOUR[s] ?? "var(--chart-5)",
      kind: "bar",
      ma: true,
      points: t.weekly.map((w) => ({ d: w.week, v: w.sports[s] ? val(w.sports[s]) : 0 })),
    });
    const series: ChartSeries[] = all ? MAIN.map(one) : [one(sport)];
    if (all && metric === "hours") {
      series.push({
        key: "other",
        label: TT.volume.other,
        colour: "var(--chart-5)",
        kind: "bar",
        ma: true,
        points: t.weekly.map((w) => ({ d: w.week, v: Object.entries(w.sports).filter(([s]) => !MAIN.includes(s)).reduce((sum, [, v]) => sum + val(v), 0) })),
      });
    }
    // Average per week over the whole weeks in the window: the current week does not count (it is not finished yet
    // and would pull the average down), and the number of weeks is what is really there, not the window width / 7.
    const monday = (() => {
      const d = new Date(t.today + "T12:00:00");
      d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    })();
    const counts = (s: string) => (all ? metric === "hours" || MAIN.includes(s) : s === sport);
    const weeks = t.weekly.filter((w) => w.week >= from && w.week <= win.to && w.week < monday);
    const total = weeks.reduce((sum, w) => sum + Object.entries(w.sports).filter(([s]) => counts(s)).reduce((x, [, v]) => x + val(v), 0), 0);
    return { series, avg: weeks.length ? total / weeks.length : 0, weeks: weeks.length };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t, from, win.to, metric, all, sport, tr]);

  if (q.isLoading) return <p className="text-sm text-ink-muted">{TT.loading}</p>;
  if (!t) return <p className="text-sm text-ink-muted">{TT.loadError}</p>;

  const inRange = <R extends { date?: string; week?: string }>(rows: R[]) => rows.filter((r) => (r.date ?? r.week ?? "") >= win.from && (r.date ?? r.week ?? "") <= win.to);
  const form = inRange(t.form);
  const peakCtl = form.length ? form.reduce((b, r) => (r.ctl > b.ctl ? r : b), form[0]) : null;
  const now = t.form[t.form.length - 1];
  // Hours as h:mm (below an hour fmtClock gave m:ss, so 30 minutes read as "30 h").
  const fmtVol = (v: number) => {
    if (metric !== "hours") return fmtKm(v);
    const min = Math.round(v * 60);
    return `${Math.floor(min / 60)}:${String(min % 60).padStart(2, "0")} ${f.hourUnit}`;
  };

  const z2 = t.z2_pace.map((r) => ({ d: r.week, v: r.pace_s_per_km }));
  const vo2 = t.vo2max.map((r) => ({ d: r.date, v: r.value }));
  const longest = (t.longest_runs ?? []).map((r) => ({ d: r.week, v: r.km }));
  const flags = t.hr_flags ?? [];
  const flagsInView = inRange(flags);
  const reasonText = (reasons: string[]) => reasons.map((r) => TT.hrReason[r as keyof typeof TT.hrReason] ?? r).join("; ");
  const flagMarkers = flags.map((f) => ({ d: f.date, label: TT.z2.marker(reasonText(f.reasons)) }));

  const recovery = t.recovery_daily ?? [];
  const daily = recovery.length > 0;
  const series = (key: RecoveryKey) =>
    daily
      ? recovery.filter((r) => r[key] != null).map((r) => ({ d: r.date, v: r[key] as number }))
      : t.recovery_weekly.filter((r) => r[key] != null).map((r) => ({ d: r.week, v: r[key] as number }));
  const recoveryMa = daily ? DAILY_MA : WEEKLY_MA;
  const hrv = series("hrv");
  const normals = t.recovery_normals ?? {};
  // Every recovery value against the user's own normal; HRV and SpO2 only when the watch gives them.
  const recoveryCharts = ([
    { key: "resting_hr", storage: "rhr", title: TT.recovery.rhr, points: series("resting_hr"), format: (v) => v.toFixed(0), unit: " bpm", lowerIsBetter: true, colour: "var(--chart-6)" },
    { key: "sleep_h", storage: "sleep", title: TT.recovery.sleep, points: series("sleep_h"), format: (v) => dec(v), unit: ` ${f.hourUnit}`, colour: "var(--chart-5)" },
    { key: "body_battery_high", storage: "bb", title: TT.recovery.bb, label: TT.recovery.bbShort, points: series("body_battery_high"), format: (v) => v.toFixed(0), colour: "var(--chart-1)" },
    { key: "stress_avg", storage: "stress", title: TT.recovery.stress, points: series("stress_avg"), format: (v) => v.toFixed(0), lowerIsBetter: true, colour: "var(--chart-4)" },
    { key: "sleep_resp", storage: "resp", title: TT.recovery.resp, points: series("sleep_resp"), format: (v) => dec(v), unit: " /min", lowerIsBetter: true, colour: "var(--chart-5)", note: TT.recovery.respNote },
    { key: "sleep_stress", storage: "sleep-stress", title: TT.recovery.sleepStress, points: series("sleep_stress"), format: (v) => v.toFixed(0), lowerIsBetter: true, colour: "var(--chart-4)" },
    { key: "bb_charged_sleep", storage: "bb-charged", title: TT.recovery.bbCharged, points: series("bb_charged_sleep"), format: (v) => v.toFixed(0), colour: "var(--chart-1)" },
    { key: "spo2_avg", storage: "spo2", title: TT.recovery.spo2, points: series("spo2_avg"), format: (v) => v.toFixed(0), unit: "%", colour: "var(--chart-3)" },
    { key: "hrv", storage: "hrv", title: TT.recovery.hrv, points: hrv, format: (v) => v.toFixed(0), unit: " ms", colour: "var(--chart-3)", note: TT.recovery.hrvNote },
  ] as RecoveryChart[]).filter((c) => ALWAYS.includes(c.key) || c.points.length > 0);

  const raceName = (r: TrendsPlus["races"][number]) => (r.sport === "triathlon" ? TT.races.triathlon : r.detected === "heart_rate" ? TT.races.byHeartRate(r.name) : r.name);
  // a triathlon is a race in swimming and cycling too
  const races = t.races.filter((r) => all || r.sport === sport || (r.sport === "triathlon" && ["swim", "ride", "run"].includes(sport)));
  const perf = t.sport_performance ?? {};
  const SP = TT.sportPerf;
  const perfValue = (s: string, b: { key: string; value: number }) =>
    b.key === "longest" ? fmtKm(b.value) : s === "swim" ? `${fmtClock(b.value)}/100m` : `${dec(b.value)} ${f.kmhUnit}`;
  const bestsTable = (s: string) => (
    <table className="w-full text-[13px] tabular-nums">
      <tbody>
        {perf[s].bests.map((b) => (
          <tr key={b.key} className="border-t border-border first:border-t-0">
            <td className="py-2 text-ink-muted">{SP.key(b.key, s)}</td>
            <td className="py-2 font-medium">{perfValue(s, b)}</td>
            <td className="hidden py-2 text-ink-muted sm:table-cell">{fmtKm(b.km)} · {fmtClock(b.seconds)}</td>
            <td className="py-2 text-right">
              <Link className="text-ink-muted underline-offset-2 hover:underline" href={href(b.activity_id)}>{fmtDay(b.date)}</Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  const raceMarkers = races.map((r) => ({ d: r.date, label: raceName(r) }));
  const hasRecords = Object.values(t.records).some((rows) => rows.length > 0);
  const raceRecord = Object.values(t.records).some((rows) => rows.some((r) => r.source === "race"));
  const predictDays = t.rules?.predict_days ?? 180;
  const p42 = t.predictions["42k"];

  return (
    <div className="flex flex-col gap-4">
      <TimeFilterBar
        range={range}
        first={first}
        last={last}
        overview={t.form.map((r) => ({ d: r.date, v: r.ctl }))}
        extra={
          // The sport, in the bar like "Adjust": it narrows volume, zones and Training and body to one sport, and the
          // running-only charts (Z2 pace, VO2max, predictions, records) show only for all sports or running. Recovery
          // is not per sport: there it is left out.
          sports.length > 1 && tab !== "recovery" ? (
            <label className="relative flex shrink-0 items-center rounded-md text-xs font-medium text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink">
              <select
                aria-label={TT.sport.label}
                value={sport}
                onChange={(e) => chooseSport(e.target.value)}
                className="cursor-pointer appearance-none bg-transparent py-2 pl-3 pr-6 text-xs font-medium text-inherit outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <option value={ALL_SPORTS}>{TT.sport.all}</option>
                {(sports.includes(sport) || all ? sports : [...sports, sport]).map((s) => (
                  <option key={s} value={s}>{tr.sport(s)}</option>
                ))}
              </select>
              <span aria-hidden className="pointer-events-none absolute right-2.5">▾</span>
            </label>
          ) : null
        }
      />


      {tab === "training" && (
        <>
          <Card title={TT.insights.title}>
            {t.insights.length === 0 ? (
              <p className="text-[13px] text-ink-muted">{t.form.length ? TT.insights.none : TT.insights.empty}</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {t.insights.map((i, n) => {
                  const { title, text } = TT.insight(i);
                  return (
                    <li key={i.code + n} className="flex gap-3 text-[13px]">
                      <span className="mt-1.5 inline-block h-2 w-2 flex-none rounded-full" style={{ background: levelColour(i.level) }} />
                      <span><span className="font-medium">{title}.</span> <span className="text-ink-muted">{text}</span></span>
                    </li>
                  );
                })}
              </ul>
            )}
            {t.form.length > 0 && <p className="mt-3 text-[11.5px] text-ink-muted">{t.goal ? TT.insights.goal(t.goal.text) : TT.insights.noGoal}</p>}
          </Card>
          <Card title={TT.form.title}>
            {now && (
              <div className="mb-2 flex flex-wrap gap-x-6 gap-y-1 text-[12.5px] tabular-nums text-ink-muted">
                <span>{TT.form.fitnessNow} <b className="text-ink">{Math.round(now.ctl)}</b></span>
                <span>{TT.form.fatigue} <b className="text-ink">{Math.round(now.atl)}</b></span>
                <span>{TT.form.form} <b className="text-ink">{now.tsb > 0 ? "+" : ""}{Math.round(now.tsb)}</b>{now.form_pct != null && ` (${now.form_pct > 0 ? "+" : ""}${now.form_pct}%)`}</span>
                {peakCtl && <span>{TT.form.peak(Math.round(peakCtl.ctl), fmtDate(peakCtl.date))}</span>}
              </div>
            )}
            <TimeChart
              {...shared}
              ariaLabel={TT.form.title}
              height={260}
              baseline={0}
              format={(v) => String(Math.round(v))}
              maOptions={DAILY_MA}
              storageKey="trends-form"
              markers={raceMarkers}
              series={[
                { key: "ctl", label: TT.form.fitness, colour: "var(--chart-1)", width: 2.25, peak: "max", points: t.form.map((r) => ({ d: r.date, v: r.ctl })) },
                { key: "atl", label: TT.form.fatigue, colour: "var(--chart-3)", points: t.form.map((r) => ({ d: r.date, v: r.atl })) },
                { key: "tsb", label: TT.form.form, colour: "var(--chart-4)", dash: "dashed", ma: true, points: t.form.map((r) => ({ d: r.date, v: r.tsb })) },
              ]}
            />
            {t.stopped_at_sync && t.form_until && <p className="mt-2 text-[12px] text-ink-muted">{TT.form.stopped(fmtDate(t.form_until))}</p>}
            <p className="mt-2 text-[11.5px] text-ink-muted">{T.formMethod} {T.formChartNote}</p>
          </Card>
          <Card title={TT.volume.title} action={<Tabs variant="segmented" items={[{ id: "hours", label: TT.volume.hours }, { id: "km", label: TT.volume.km }]} value={metric} onChange={(v) => setMetric(v as "hours" | "km")} ariaLabel={TT.volume.unit} />}>
            {t.weekly.length > 0 && (
              <p className="mb-2 text-[12.5px] tabular-nums text-ink-muted">{volume.weeks > 0 ? TT.volume.avg(fmtVol(volume.avg), volume.weeks) : TT.volume.noWholeWeek}</p>
            )}
            <TimeChart {...shared} ariaLabel={TT.volume.aria} height={220} format={fmtVol} maOptions={WEEKLY_MA} storageKey="trends-volume" totalLabel={TT.volume.total} series={volume.series} />
          </Card>
          <ZonesOverTime window={win} sport={sport} />
          {/* Every chart across the full width: the time axis is what you read, it needs the room. */}
          {running && (
            <>
              <Card title={TT.z2.title}>
                <TrendChart {...shared} label={TT.z2.label} points={z2} format={(v) => fmtClock(v)} unit="/km" lowerIsBetter clock maOptions={WEEKLY_MA} storageKey="trends-z2" markers={flagMarkers} />
                <p className="mt-2 text-[11.5px] text-ink-muted">{T.z2Pace}</p>
                {flagsInView.length > 0 && (
                  <details className="mt-2 text-[11.5px] text-ink-muted">
                    <summary className="cursor-pointer">{TT.z2.excluded(flagsInView.length)}</summary>
                    <ul className="mt-1.5 flex flex-col gap-1">
                      {flagsInView.map((f) => (
                        <li key={f.id}>
                          <Link className="underline underline-offset-2" href={href(f.id)}>{fmtDay(f.date)}{f.name ? ` · ${f.name}` : ""}</Link>: {reasonText(f.reasons)}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1.5">{TT.hrMethod}</p>
                  </details>
                )}
              </Card>
              <Card title={TT.vo2.title}>
                <TrendChart {...shared} label={TT.vo2.label} points={vo2} format={(v) => v.toFixed(0)} maOptions={DAILY_MA} storageKey="trends-vo2" />
                <p className="mt-2 text-[11.5px] text-ink-muted">{T.vo2max}</p>
              </Card>
            </>
          )}

          <Card title={tr.trainingBody.title}>
            <TrainingBody t={t} window={win} />
          </Card>
        </>
      )}

      {tab === "performance" && (
        <>
          {running ? (
            <>
              <Card title={TT.predictions.title}>
                {Object.keys(t.predictions).length === 0 ? (
                  <p className="text-[13px] text-ink-muted">{TT.predictions.none(predictDays)}</p>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
                      {(["5k", "10k", "21k", "42k"] as const).map((k) => {
                        const p = t.predictions[k];
                        return (
                          <div key={k} className="flex flex-col">
                            <span className="text-[11.5px] text-ink-muted">{TT.predictions.label[k]}</span>
                            <span className="whitespace-nowrap font-display text-[19px] leading-tight tabular-nums xl:text-[21px]">{p ? fmtClock(p.seconds) : "–"}</span>
                            {p && <span className="text-[11px] tabular-nums text-ink-muted">{fmtClock(p.pace_s_per_km)}/km</span>}
                            {p && (
                              <Link className="text-[11px] tabular-nums text-ink-muted underline-offset-2 hover:underline" href={href(p.from.activity_id)} title={TT.predictions.fromTitle(fmtKm(p.from.km), fmtClock(p.from.seconds), fmtDay(p.from.date))}>
                                {TT.predictions.from(fmtKm(p.from.km))}
                              </Link>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    {p42 && (
                      <p className="mt-3 text-[11.5px] text-ink-muted">
                        {TT.predictions.basedOn}{" "}
                        <Link className="underline underline-offset-2" href={href(p42.from.activity_id)}>
                          {TT.predictions.fromTitle(fmtKm(p42.from.km), fmtClock(p42.from.seconds), fmtDay(p42.from.date))}
                        </Link>
                        . {T.prediction(predictDays)}
                      </p>
                    )}
                  </>
                )}
              </Card>
              <Card title={TT.longest.title}>
                <TrendChart {...shared} label={TT.longest.label} points={longest} format={(v) => dec(v)} unit=" km" maOptions={WEEKLY_MA} storageKey="trends-longest" colour="var(--chart-3)" />
                <p className="mt-2 text-[11.5px] text-ink-muted">{TT.longest.note}</p>
              </Card>
              {/* Records across the full width: the progression per distance needs room. */}
              <Card title={TT.records.title}>
                {!hasRecords ? (
                  <p className="text-[13px] text-ink-muted">{TT.records.empty}</p>
                ) : (
                  <RecordTable records={t.records} recent={t.recent_records ?? []} window={win} recentDays={t.rules?.recent_record_days ?? 14} href={href} colours={RECORD_COLOUR} />
                )}
                <p className="mt-2 text-[11.5px] text-ink-muted">
                  {TT.records.method}
                  {raceRecord ? ` ${TT.records.raceRule(t.rules?.race_short_pct ?? 2)}` : ""}
                  {hasRecords ? ` ${TT.records.progressNote}` : ""}
                </p>
              </Card>
            </>
          ) : perf[sport] ? (
            // swimming and cycling: their own bests, longest per week and pace or speed per week
            <>
              <Card title={SP.bests(tr.sport(sport))}>
                {bestsTable(sport)}
                <p className="mt-2 text-[11.5px] text-ink-muted">{SP.method(sport)}</p>
              </Card>
              <Card title={SP.longest(tr.sport(sport))}>
                <TrendChart {...shared} label={SP.longestLabel} points={perf[sport].longest.map((w) => ({ d: w.week, v: w.km }))} format={(v) => dec(v)} unit=" km" maOptions={WEEKLY_MA} storageKey={`trends-longest-${sport}`} colour="var(--chart-3)" />
              </Card>
              <Card title={SP.speed(sport)}>
                <TrendChart
                  {...shared}
                  label={SP.speedLabel(sport)}
                  points={perf[sport].speed.map((w) => ({ d: w.week, v: w.value }))}
                  format={(v) => (sport === "swim" ? fmtClock(v) : dec(v))}
                  unit={sport === "swim" ? "/100m" : ` ${f.kmhUnit}`}
                  lowerIsBetter={sport === "swim"}
                  clock={sport === "swim"}
                  maOptions={WEEKLY_MA}
                  storageKey={`trends-speed-${sport}`}
                />
              </Card>
            </>
          ) : (
            <p className="text-[12.5px] text-ink-muted">{SP.noPerf}</p>
          )}
          {/* all sports: next to the running cards the bests of swimming and cycling */}
          {all && Object.keys(perf).length > 0 && (
            <Card title={SP.bestsAll}>
              <div className="flex flex-col gap-4">
                {Object.keys(perf).map((s) => (
                  <div key={s}>
                    <h3 className="mb-1 text-[12.5px] font-medium">{tr.sport(s)}</h3>
                    {bestsTable(s)}
                  </div>
                ))}
              </div>
            </Card>
          )}
          <Card title={TT.races.title}>
            {races.length === 0 ? (
              <p className="text-[13px] text-ink-muted">{TT.races.none}</p>
            ) : (
              <ul className="flex flex-col">
                {[...races].reverse().map((r) => (
                  <li key={r.date + r.name + r.activity_ids[0]} className="grid grid-cols-[1fr_auto] gap-2 border-t border-border py-2 text-[13px] first:border-t-0">
                    <Link href={href(r.activity_ids[r.activity_ids.length - 1])} className="hover:underline">
                      <span className="font-medium">{raceName(r)}</span> <span className="text-ink-muted">· {fmtDay(r.date)}</span>
                    </Link>
                    <span className="tabular-nums text-ink-muted">{fmtKm(r.distance_km)} · {fmtClock(r.seconds)}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-[11.5px] text-ink-muted">{T.races(t.rules ?? { race_min_km: 5, race_hard_pct: 85 })}</p>
          </Card>
        </>
      )}

      {tab === "recovery" && (
        <>
          <SleepStages nights={t.sleep_stages ?? []} window={win} />
          <Card title={daily ? TT.recovery.titleDay : TT.recovery.titleWeek}>
            <div className="grid gap-6 md:grid-cols-2">
              {recoveryCharts.map((c) => (
                <div key={c.key}>
                  <h3 className="mb-1 text-[12.5px] font-medium">{c.title}</h3>
                  <TrendChart
                    label={c.label ?? c.title}
                    {...shared}
                    maOptions={recoveryMa}
                    maDefault={daily ? 7 : 0}
                    storageKey={`trends-${c.storage}`}
                    points={c.points}
                    format={c.format}
                    unit={c.unit}
                    lowerIsBetter={c.lowerIsBetter}
                    height={140}
                    colour={c.colour}
                    onPick={daily ? setPicked : undefined}
                  />
                  {(normals[c.key] != null || c.note) && (
                    <p className="mt-2 text-[11.5px] text-ink-muted">
                      {normals[c.key] != null ? TT.recovery.normal(`${c.format(normals[c.key]!)}${c.unit ?? ""}`) : ""} {c.note ?? ""}
                    </p>
                  )}
                </div>
              ))}
            </div>
            {daily && (
              <p className="mt-4 text-[11.5px] text-ink-muted">
                {picked ? (
                  <Link href={`/dashboard/body/?day=${picked}`} className="font-semibold text-brand hover:underline">
                    {tr.dashboard.dayLink(f.weekdayDay(picked))} →
                  </Link>
                ) : (
                  TT.recovery.openDay
                )}
              </p>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
