"use client";

// Today, Sleep & body: one day from the watch. First the day in numbers (the night's sleep with
// its stages, heart rate, breathing, stress and blood oxygen while asleep; then the day: resting heart rate, Body
// Battery, stress per level and activity), each against the user's own normal; then one timeline of the night and the
// day with heart rate, stress, Body Battery, breathing and SpO2 as equal small panels. Last night by default; another
// day through ?day= (links from Trends and the cards on the overview: /dashboard/body/?day=…), the date field or the
// arrows.

import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import SyncButton from "@/components/SyncButton";
import { Button, Columns, IconButton } from "@/components/ds";
import { ChevronLeftIcon, ChevronRightIcon } from "@trackerai/ui/icons";
import DayTimeline, { clock, STAGE_COLOUR, type TimelinePanel } from "@/components/charts/DayTimeline";
import { api } from "@/lib/api";
import { useFormat, useT } from "@/lib/i18n";
import type { DaySeriesKey, HealthDay, SleepStage } from "@/lib/training";

const STAGES: { stage: SleepStage; key: string }[] = [
  { stage: "deep", key: "deep_sleep_h" },
  { stage: "light", key: "light_sleep_h" },
  { stage: "rem", key: "rem_sleep_h" },
  { stage: "awake", key: "awake_h" },
];
const STRESS = [
  { level: "rest", key: "stress_rest_min", colour: "var(--zone-1)" },
  { level: "low", key: "stress_low_min", colour: "var(--zone-3)" },
  { level: "medium", key: "stress_medium_min", colour: "var(--zone-4)" },
  { level: "high", key: "stress_high_min", colour: "var(--zone-5)" },
] as const;
const RISE_NOTABLE = 8; // beats: from here the last two hours of sleep get a dot
const SERIES_COLOUR: Record<DaySeriesKey, string> = {
  hr: "var(--chart-6)",
  stress: "var(--chart-4)",
  bb: "var(--chart-1)",
  resp: "var(--chart-5)",
  spo2: "var(--chart-3)",
};

function Stat({ label, value, note, dot }: { label: string; value: React.ReactNode; note?: React.ReactNode; dot?: string }) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-[11.5px] text-ink-muted">
        {dot && <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: dot }} />}
        {label}
      </dt>
      <dd>
        <span className="text-[17px] leading-tight tabular-nums">{value}</span>
        {note && <span className="block text-[11px] text-ink-muted tabular-nums">{note}</span>}
      </dd>
    </div>
  );
}

/** One bar split into parts (sleep stages in hours, stress levels in minutes) with a legend under it. */
function ShareBar({ parts, label }: { parts: { name: string; value: number; colour: string; opacity?: number; text: string }[]; label: string }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (!total) return null;
  return (
    <div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-sm" role="img" aria-label={`${label}: ${parts.map((p) => `${p.name} ${p.text}`).join(", ")}`}>
        {parts.map((p) => (
          <span key={p.name} style={{ width: `${(p.value / total) * 100}%`, background: p.colour, opacity: p.opacity ?? 1 }} />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3.5 gap-y-1 text-[11.5px] text-ink-muted tabular-nums">
        {parts.map((p) => (
          <span key={p.name} className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2 w-2.5 rounded-sm" style={{ background: p.colour, opacity: p.opacity ?? 1 }} />
            {p.name} {p.text}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function DaySection() {
  const param = useSearchParams().get("day");
  const day = param && /^\d{4}-\d{2}-\d{2}$/.test(param) ? param : null;
  const t = useT();
  const f = useFormat();
  const h = t.health;
  const router = useRouter();

  const q = useQuery({
    queryKey: ["wellness-day", day],
    queryFn: () => api.get<HealthDay>(`/api/wellness/day${day ? `?day=${day}` : ""}`),
    placeholderData: keepPreviousData,
  });
  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{h.loadFailed}</p>;
  const v = q.data;
  if (!v.latest) return <Card><p className="text-[13px] text-ink-muted">{h.none}</p></Card>;

  const go = (d: string) => router.replace(`/dashboard/body/?day=${d}`, { scroll: false });
  // Voeding: the evening before this night, "Laatste maaltijd 21:30 · 2 eenheden alcohol"
  const eveningLabel = (e: NonNullable<HealthDay["evening"]>) =>
    [t.nutrition.evening.lastMeal(e.last_meal), e.alcohol_units ? t.nutrition.evening.alcohol(f.trim(e.alcohol_units, 1)) : null, e.late_large ? t.nutrition.evening.lateLarge : null]
      .filter(Boolean).join(" · ");
  const w = v.summary;
  const n = v.normals;
  const num = (key: string) => (typeof w[key] === "number" ? (w[key] as number) : null);
  const normal = (value: number | null | undefined, digits = 0, unit = "") => (value != null ? h.normal(`${f.num(value, digits)}${unit}`) : undefined);
  const night = v.night;
  const sleepH = num("sleep_h");
  const hasDay = Object.keys(w).length > 0 || Object.keys(v.series).length > 0;
  const rhrNormal = n.resting_hr != null ? Math.round(n.resting_hr) : null;

  const panels: TimelinePanel[] = (
    [
      { key: "hr", format: (x: number) => `${x}`, reference: rhrNormal },
      { key: "stress", format: (x: number) => `${x}`, domain: [0, 100] as [number, number] },
      { key: "bb", format: (x: number) => `${x}`, domain: [0, 100] as [number, number] },
      { key: "resp", format: (x: number) => f.num(x, 1) },
      { key: "spo2", format: (x: number) => `${x}%`, domain: [90, 100] as [number, number] },
    ] as const
  ).map((p) => ({ ...p, label: `${h.series[p.key]}${h.unit[p.key] && p.key !== "spo2" ? ` (${h.unit[p.key]})` : ""}`, colour: SERIES_COLOUR[p.key], points: v.series[p.key] ?? [] }));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 aria-live="polite" className={`font-display text-[21px] font-light transition-opacity ${q.isPlaceholderData ? "opacity-60" : ""}`}>
            {f.weekdayDayYear(v.day)}
          </h2>
        </div>
        <div className="flex items-center gap-1">
          {/* Any day straight away; the arrows step through the days that have data. */}
          <input
            type="date"
            aria-label={h.pickDay}
            value={v.day}
            max={v.today ?? v.latest}
            onChange={(e) => /^\d{4}-\d{2}-\d{2}$/.test(e.target.value) && go(e.target.value)}
            className="h-8 rounded border border-border bg-surface px-2 text-[13px] tabular-nums text-[var(--text-primary)]"
          />
          <IconButton label={h.previous} size="sm" icon={<ChevronLeftIcon width={15} height={15} />} disabled={!v.prev} onClick={() => v.prev && go(v.prev)} />
          <IconButton label={h.next} size="sm" icon={<ChevronRightIcon width={15} height={15} />} disabled={!v.next} onClick={() => v.next && go(v.next)} />
          {v.day !== v.latest && (
            <Button variant="ghost" size="sm" onClick={() => go(v.latest!)}>
              {h.latest}
            </Button>
          )}
        </div>
      </div>

      {!hasDay ? (
        v.day === v.today ? (
          // Garmin has nothing of today until the watch has uploaded it through the Garmin Connect app
          <Card>
            <p className="text-[13px] text-ink-muted">{h.emptyToday}</p>
            <div className="mt-3"><SyncButton text /></div>
          </Card>
        ) : (
          <Card><p className="text-[13px] text-ink-muted">{h.empty}</p></Card>
        )
      ) : (
        <>
          <Columns template="lg:grid-cols-2" left={[
            <Card title={h.sleep}>
              {sleepH == null && !v.sleep ? (
                <p className="text-[13px] text-ink-muted">{h.noSleep}</p>
              ) : (
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    {sleepH != null && <span className="font-display text-[27px] font-light tabular-nums">{f.hours(sleepH * 3600)}</span>}
                    <span className="text-[12px] text-ink-muted tabular-nums">
                      {[
                        v.sleep ? h.sleptFrom(clock(v.sleep.start), clock(v.sleep.end)) : null,
                        num("sleep_score") != null ? h.score(num("sleep_score")!) : null,
                        normal(n.sleep_h, 1, ` ${f.hourUnit}`),
                      ].filter(Boolean).join(" · ")}
                    </span>
                  </div>
                  <ShareBar
                    label={h.stagesTitle}
                    parts={STAGES.filter((s) => num(s.key)).map((s) => ({
                      name: h.stage[s.stage],
                      value: num(s.key)!,
                      colour: STAGE_COLOUR[s.stage].fill,
                      opacity: STAGE_COLOUR[s.stage].opacity,
                      text: f.hours(num(s.key)! * 3600),
                    }))}
                  />
                  <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
                    {night && <Stat label={h.lowest} value={h.bpm(night.lowest)} note={h.at(clock(night.lowest_at))} />}
                    {(num("sleep_hr") ?? night?.avg) != null && <Stat label={h.hrAsleep} value={h.bpm((num("sleep_hr") ?? night?.avg)!)} note={normal(n.sleep_hr)} />}
                    {night?.last_avg != null && night.before_avg != null && night.rise != null && (
                      <Stat
                        label={h.lastTwo}
                        value={h.bpm(night.last_avg)}
                        note={h.vsRest(night.before_avg, `${night.rise > 0 ? "+" : ""}${night.rise}`)}
                        dot={night.rise >= RISE_NOTABLE ? "var(--zone-3)" : undefined}
                      />
                    )}
                    {num("sleep_resp") != null && (
                      <Stat label={h.respiration} value={`${f.num(num("sleep_resp")!, 1)} ${h.unit.resp}`} note={[normal(n.sleep_resp, 1), num("sleep_resp_low") != null ? h.lowestOf(f.num(num("sleep_resp_low")!, 1)) : null].filter(Boolean).join(" · ")} />
                    )}
                    {num("sleep_stress") != null && <Stat label={h.sleepStress} value={f.num(num("sleep_stress")!, 0)} note={normal(n.sleep_stress)} />}
                    {num("spo2_avg") != null && (
                      <Stat label={h.spo2} value={`${num("spo2_avg")}%`} note={[normal(n.spo2_avg, 0, "%"), num("spo2_low") != null ? h.lowestOf(`${num("spo2_low")}%`) : null].filter(Boolean).join(" · ")} />
                    )}
                    {num("bb_charged_sleep") != null && <Stat label={h.bbCharged} value={`+${num("bb_charged_sleep")}`} note={normal(n.bb_charged_sleep)} />}
                  </dl>
                  {!(night?.rise != null && night.last_avg != null && night.before_avg != null) && v.sleep && (
                    <p className="text-[12px] text-ink-muted">{h.noNight}</p>
                  )}
                  {/* the watch estimates the stages: say so once, where they are shown */}
                  {sleepH != null && <p className="text-[11.5px] text-ink-muted">{h.estimate}</p>}
                </div>
              )}
            </Card>,
          ]} right={[
            <Card title={h.day}>
              <div className="flex flex-col gap-4">
                <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
                  {num("resting_hr") != null && <Stat label={h.restingHr} value={h.bpm(num("resting_hr")!)} note={normal(n.resting_hr)} />}
                  {num("body_battery_high") != null && (
                    <Stat
                      label={h.bodyBattery}
                      value={num("body_battery_high")}
                      note={[
                        num("body_battery_low") != null ? h.lowestOf(String(num("body_battery_low"))) : null,
                        num("bb_charged") != null && num("bb_drained") != null ? h.bbFlow(num("bb_charged")!, num("bb_drained")!) : null,
                      ].filter(Boolean).join(" · ")}
                    />
                  )}
                  {num("stress_avg") != null && <Stat label={h.stress} value={num("stress_avg")} note={normal(n.stress_avg)} />}
                  {num("steps") != null && <Stat label={h.steps} value={f.num(num("steps")!)} />}
                  {num("intensity_min") != null && (
                    <Stat label={h.intensity} value={num("intensity_min")} note={h.intensityDetail(num("intensity_moderate_min") ?? 0, num("intensity_vigorous_min") ?? 0)} />
                  )}
                  {num("floors") != null && <Stat label={h.floors} value={num("floors")} />}
                  {num("active_kcal") != null && <Stat label={h.activeKcal} value={h.kcal(f.num(num("active_kcal")!))} />}
                </dl>
                {STRESS.some((s) => num(s.key)) && (
                  <div>
                    <p className="mb-1.5 text-[11.5px] text-ink-muted">{h.stressLevels}</p>
                    <ShareBar
                      label={h.stressLevels}
                      parts={STRESS.filter((s) => num(s.key)).map((s) => ({ name: h.level[s.level], value: num(s.key)!, colour: s.colour, text: f.duration(num(s.key)! * 60) }))}
                    />
                  </div>
                )}
              </div>
            </Card>,
          ]} />

          {panels.some((p) => p.points.length >= 2) && (
            <Card title={h.timeline}>
              <DayTimeline
                from={v.from}
                to={v.to}
                panels={panels}
                sleep={v.sleep}
                nextSleepStart={v.next_sleep_start}
                marks={v.evening ? [{ minute: v.evening.minute - 1440, label: eveningLabel(v.evening) }] : []}
                stageLabel={h.stage}
                stagesTitle={h.stagesTitle}
                ariaLabel={h.timelineAria(f.long(v.day))}
                rangeLabel={h.range}
              />
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-ink-muted">
                {v.sleep && (
                  <span className="flex items-center gap-1.5">
                    <span aria-hidden className="inline-block h-2.5 w-3.5 rounded-sm" style={{ background: "var(--chart-band)", outline: "1px solid var(--border)" }} />
                    {h.sleep}
                  </span>
                )}
                {v.evening && (
                  <span className="flex items-center gap-1.5">
                    <svg width="10" height="10" aria-hidden><line x1="5" x2="5" y1="0" y2="10" stroke="var(--macro-alcohol)" strokeDasharray="3 3" /></svg>
                    {t.nutrition.evening.before(eveningLabel(v.evening))}
                  </span>
                )}
                {rhrNormal != null && (
                  <span className="flex items-center gap-1.5">
                    <svg width="16" height="6" aria-hidden>
                      <line x1="0" x2="16" y1="3" y2="3" stroke="var(--chart-2)" strokeWidth="1" strokeDasharray="4 4" />
                    </svg>
                    {h.normalLine(rhrNormal)}
                  </span>
                )}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">{h.source}</p>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
