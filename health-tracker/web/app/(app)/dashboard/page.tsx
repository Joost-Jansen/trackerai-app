"use client";

// Vandaag (today): what the week and the month look like in zones, how much you did against your usual week,
// how fresh you are, and your latest activities and recovery.

import { useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Columns } from "@/components/ds";
import ZoneBar from "@/components/ZoneBar";
import GearNotice from "@/components/dashboard/GearNotice";
import NutritionCard from "@/components/nutrition/NutritionCard";
import OnboardingCard from "@/components/onboarding/Checklist";
import EasyShare from "@/components/zones/EasyShare";
import PeriodNav from "@/components/zones/PeriodNav";
import LoadCard from "@/components/dashboard/LoadCard";
import PlanWeekCard from "@/components/dashboard/PlanWeekCard";
import ReadinessCard from "@/components/dashboard/ReadinessCard";
import RecentActivities from "@/components/dashboard/RecentActivities";
import Upcoming from "@/components/dashboard/Upcoming";
import LineChart from "@trackerai/ui/charts/LineChart";
import { api } from "@/lib/api";
import { useOnboarding } from "@/lib/onboarding";
import { useFormat, useT } from "@/lib/i18n";
import { periodLabel } from "@/lib/i18n/period";
import type { Dashboard, ZonesForPeriod } from "@/lib/training";

const FORM_LINES = [
  { key: "fitness", colour: "var(--chart-1)", dash: false },
  { key: "fatigue", colour: "var(--chart-3)", dash: false },
  { key: "form", colour: "var(--chart-4)", dash: true },
] as const;

const SPORT_ORDER = ["run", "ride", "swim"];

const IMPORT_STALE_DAYS = 7; // an Apple Health import this old gets a reminder: nothing new comes in by itself
const dayNo = (iso: string) => Date.parse(iso.slice(0, 10) + "T00:00:00Z") / 86_400_000;
const isoOf = (n: number) => new Date(n * 86_400_000).toISOString().slice(0, 10);
const bySportOrder = (a: string, b: string) =>
  (SPORT_ORDER.indexOf(a) + 1 || 99) - (SPORT_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b);

function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { id: T; label: string }[];
}) {
  return (
    <div className="ds-segmented" role="tablist">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="tab"
          aria-selected={value === o.id}
          className={`ds-segmented__item ${value === o.id ? "ds-segmented__item--active" : ""}`}
          onClick={() => onChange(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const t = useT();
  const f = useFormat();
  const T = t.texts;
  const m = t.dashboard;
  const [period, setPeriod] = useState<"week" | "month">("week");
  const [offset, setOffset] = useState(0);
  // The form chart: drag across it to zoom in on that stretch, double-click for all of it again.
  const [formZoom, setFormZoom] = useState<{ from: string; to: string } | null>(null);
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/api/dashboard") });
  const apple = useOnboarding().data?.status.apple;
  const zq = useQuery({
    queryKey: ["zones", period, offset],
    queryFn: () => api.get<ZonesForPeriod>(`/api/zones?period=${period}&offset=${offset}`),
    placeholderData: keepPreviousData,
  });
  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{m.loadFailed}</p>;
  const d = q.data;

  // Until /api/zones is there, the current period from the dashboard; after that the previous one stays while loading.
  const zp = zq.data;
  const zones = zp ? zp.zones : d.zones[period];
  const zonesCurrent = zp ? zp.is_current : true;
  const bounds = zp?.bounds ?? d.zone_bounds;
  const zoneSports = Object.keys(zones)
    .filter((s) => s !== "all")
    .sort(bySportOrder);
  const multiSport = zoneSports.length > 1;
  const volSports = Array.from(new Set([...Object.keys(d.volume.week), ...Object.keys(d.volume.avg4w)])).sort(bySportOrder);
  const form = d.form;
  const all = form?.series ?? [];
  const zoomed = formZoom ? all.filter((r) => r.date >= formZoom.from && r.date <= formZoom.to) : all;
  const formSeries = zoomed.length >= 2 ? zoomed : all;
  const syncDay = /^\d{4}-\d{2}-\d{2}/.test(d.last_sync ?? "") ? d.last_sync.slice(0, 10) : null;
  const syncAge = syncDay ? dayNo(d.today) - dayNo(syncDay) : 0;
  const importAge = apple?.imported_at ? dayNo(d.today) - dayNo(apple.imported_at.slice(0, 10)) : 0;
  const lastSync = syncDay ? `${f.weekdayDay(syncDay)}${d.last_sync.length > 10 ? `, ${d.last_sync.slice(11, 16)}` : ""}` : t.common.notYet;
  // The current week (Monday up to today) against the average of the four whole weeks before it.
  const weekThrough = f.date(d.today, { weekday: "long" });
  // Recovery: all seven days, including those without a measurement, so a gap is visible instead of dropping out.
  const recoveryByDay = new Map(d.recovery.days.map((w) => [w.date, w]));
  const recoveryDays = Array.from({ length: 7 }, (_, i) => isoOf(dayNo(d.today) - i));

  return (
    <div className="flex flex-col gap-4">
      {!syncDay && apple?.imported_at ? (
        // An Apple Watch has no sync: when the last import was, how to bring in newer data, and from a week on a
        // reminder like a stale sync's (nothing new comes in by itself)
        importAge >= IMPORT_STALE_DAYS ? (
          <p
            role="status"
            className="flex items-start gap-2 rounded border border-border bg-surface px-3 py-2 text-[12.5px] leading-relaxed"
          >
            <span aria-hidden="true" className="mt-[6px] inline-block h-2 w-2 flex-none rounded-full bg-warn" />
            <span>
              <span className="font-medium">{m.lastImport(f.dateTime(apple.imported_at))}.</span>{" "}
              <span className="text-ink-muted">{m.importStale(importAge)}</span>{" "}
              <Link href="/settings/connections/#apple" className="font-medium underline underline-offset-4">
                {m.importNow}
              </Link>
            </span>
          </p>
        ) : (
          <p className="text-[12.5px] text-ink-muted">
            {m.lastImport(f.dateTime(apple.imported_at))}
            {importAge >= 2 && (
              <>
                {" "}
                ·{" "}
                <Link href="/settings/connections/#apple" className="underline underline-offset-4">
                  {m.importNewer}
                </Link>
              </>
            )}
          </p>
        )
      ) : syncAge >= 2 ? (
        <p role="status" className="flex items-start gap-2 rounded border border-border bg-surface px-3 py-2 text-[12.5px] leading-relaxed">
          <span aria-hidden="true" className="mt-[6px] inline-block h-2 w-2 flex-none rounded-full bg-warn" />
          <span>
            <span className="font-medium">{m.lastSync(lastSync)}.</span> <span className="text-ink-muted">{T.syncStale(syncAge)}</span>
          </span>
        </p>
      ) : (
        <p className="text-[12.5px] text-ink-muted">{m.lastSync(lastSync)}</p>
      )}

      <GearNotice />

      <OnboardingCard />

      {/* Side by side in two blocks of independent columns (Columns): every card as tall as its content, the lists
          (upcoming sessions, recent activities) show as many rows as fit so both columns end level; form across the
          full width between them. On a phone one column in reading order. Cards without anything to say drop out. */}
      <Columns
        left={[
          d.readiness && <ReadinessCard key="ready" r={d.readiness} />,
          d.nutrition && <NutritionCard key="nutrition" block={d.nutrition} />,
          d.plan_week && <PlanWeekCard key="plan" week={d.plan_week} race={d.race} />,
        ]}
        right={[
          form && <LoadCard key="load" load={form.load} />,
          d.plan_week && <Upcoming key="upcoming" sessions={d.upcoming} title={d.plan_title} fill />,
        ]}
      />

      {form && (
        <Card title={m.formTitle} more={m.allTrends} moreHref="/trends/">
          <div className="grid gap-4 md:grid-cols-[240px_1fr]">
            <div className="flex flex-col gap-3">
              <div>
                <div className="font-display text-[27px] font-light">{m.statuses[form.status] ?? form.status}</div>
                <p className="text-[12.5px] leading-relaxed text-ink-muted">{T.formStatus[form.status]}</p>
              </div>
              <dl className="flex flex-wrap gap-x-6 gap-y-2 text-[12px] tabular-nums">
                <div>
                  <dt className="text-ink-muted">{m.fitness}</dt>
                  <dd className="text-[17px]">{Math.round(form.ctl)}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">{m.fatigue}</dt>
                  <dd className="text-[17px]">{Math.round(form.atl)}</dd>
                </div>
                <div>
                  <dt className="text-ink-muted">{m.form}</dt>
                  <dd className="text-[17px]">
                    {form.tsb > 0 ? "+" : ""}
                    {Math.round(form.tsb)}
                    {form.pct != null && (
                      <span className="ml-1 text-[12px] text-ink-muted">
                        ({form.pct > 0 ? "+" : ""}
                        {form.pct}%)
                      </span>
                    )}
                  </dd>
                </div>
              </dl>
              <p className="text-[11.5px] leading-relaxed text-ink-muted">
                {form.stopped_at_sync ? "" : `${T.formTsb} `}
                {m.peak(Math.round(form.ctl_peak), f.weekdayDay(form.ctl_peak_date))}
              </p>
              {form.stopped_at_sync && (
                <p className="flex items-start gap-2 text-[11.5px] leading-relaxed text-ink-muted">
                  <span aria-hidden="true" className="mt-[5px] inline-block h-1.5 w-1.5 flex-none rounded-full bg-warn" />
                  {T.today.formStopped(f.weekdayDay(form.until))}
                </p>
              )}
            </div>
            <div>
              <div className="mb-1 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-ink-muted">
                {FORM_LINES.map((l) => (
                  <span key={l.key} className="flex items-center gap-1.5">
                    <svg width="16" height="6" aria-hidden>
                      <line x1="0" x2="16" y1="3" y2="3" stroke={l.colour} strokeWidth="2" strokeDasharray={l.dash ? "4 3" : undefined} />
                    </svg>
                    {m[l.key]}
                  </span>
                ))}
              </div>
              <LineChart
                endLabels={false}
                height={190}
                ariaLabel={m.formAria}
                onSelect={setFormZoom}
                onReset={formZoom ? () => setFormZoom(null) : undefined}
                format={(v) => String(Math.round(v))}
                baseline={0}
                series={[
                  { label: m.fitness, colour: "var(--chart-1)", width: 2, points: formSeries.map((r) => ({ d: r.date, v: r.ctl })) },
                  { label: m.fatigue, colour: "var(--chart-3)", points: formSeries.map((r) => ({ d: r.date, v: r.atl })) },
                  { label: m.form, colour: "var(--chart-4)", dash: "dashed", points: formSeries.map((r) => ({ d: r.date, v: r.tsb })) },
                ]}
              />
            </div>
          </div>
        </Card>
      )}

      <Columns
        left={[
          <Card
            title={m.zonesTitle}
            action={
              <div className="flex flex-wrap items-center gap-2">
                <Segmented
                  value={period}
                  onChange={(p) => {
                    setPeriod(p);
                    setOffset(0);
                  }}
                  options={[
                    { id: "week", label: m.week },
                    { id: "month", label: m.month },
                  ]}
                />
                <PeriodNav
                  label={zp ? periodLabel(zp.period, zp.start, zp.end, t, f) : period === "week" ? m.thisWeek : m.thisMonth}
                  offset={offset}
                  onChange={setOffset}
                  loading={zq.isPlaceholderData}
                />
              </div>
            }
          >
            {zoneSports.length === 0 ? (
              <p className="text-[13px] text-ink-muted">{zonesCurrent ? m.noHrNow(period) : m.noHrPeriod}</p>
            ) : (
              <div className="flex flex-col gap-5">
                <EasyShare pct={(multiSport ? zones.all : zones[zoneSports[0]]).pct} />
                {multiSport ? (
                  <>
                    <ZoneBar sport="all" share={zones.all} />
                    <div className="border-t border-border" />
                    {zoneSports.map((s) => (
                      <ZoneBar key={s} sport={s} share={zones[s]} bounds={bounds[s]} />
                    ))}
                  </>
                ) : (
                  <>
                    <ZoneBar sport={zoneSports[0]} share={zones[zoneSports[0]]} bounds={bounds[zoneSports[0]]} />
                    <p className="-mt-2 text-[11.5px] text-ink-muted">{m.onlySport(zoneSports[0])}</p>
                  </>
                )}
              </div>
            )}
            <p className="mt-4 text-[11.5px] text-ink-muted">{T.zonesFootnote(d.zone_estimates ?? [], d.zones_set ?? [])}</p>
          </Card>,
        ]}
        right={[
          <Card title={m.volumeTitle}>
            {volSports.length === 0 ? (
              <p className="text-[13px] text-ink-muted">{m.noVolume}</p>
            ) : (
              <table className="w-full text-[13px] tabular-nums">
                <thead>
                  <tr className="text-left text-[11.5px] text-ink-muted">
                    <th className="pb-2 font-normal">{m.sport}</th>
                    <th className="pb-2 font-normal">{m.soFar}</th>
                    <th className="pb-2 font-normal">{m.avg4w}</th>
                  </tr>
                </thead>
                <tbody>
                  {volSports.map((s) => {
                    const w = d.volume.week[s];
                    const a = d.volume.avg4w[s];
                    return (
                      <tr key={s} className="border-t border-border">
                        <td className="py-2">{t.sport(s)}</td>
                        <td className="py-2">{w ? `${f.km(w.km)} · ${f.duration(w.seconds)}` : "–"}</td>
                        <td className="py-2 text-ink-muted">{a ? `${f.km(a.km)} · ${f.duration(a.seconds)}` : "–"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {volSports.length > 0 && <p className="mt-2 text-[11.5px] text-ink-muted">{T.volumeWeek(weekThrough)}</p>}
          </Card>,
          <Card title={m.recoveryTitle} more={m.dayDetail} moreHref="/dashboard/body/">
            {d.recovery.days.length === 0 ? (
              <p className="text-[13px] text-ink-muted">{m.noRecovery}</p>
            ) : (
              <table className="w-full text-[12.5px] tabular-nums">
                <thead>
                  <tr className="text-left text-[11.5px] text-ink-muted">
                    <th className="pb-2 font-normal">{m.day}</th>
                    <th className="pb-2 font-normal">{m.sleep}</th>
                    <th className="pb-2 font-normal">{m.rhr}</th>
                    <th className="pb-2 font-normal">{m.bb}</th>
                  </tr>
                </thead>
                <tbody>
                  {recoveryDays.map((day) => {
                    const w = recoveryByDay.get(day);
                    const sleep = Number(w?.sleep_h);
                    return (
                      <tr key={day} className={`border-t border-border ${w ? "" : "text-ink-muted"}`}>
                        <td className="py-1.5">
                          {w ? (
                            <Link
                              href={`/dashboard/body/?day=${day}`}
                              aria-label={m.dayLink(f.weekdayDay(day))}
                              className="hover:text-brand hover:underline"
                            >
                              {f.weekdayDay(day)}
                            </Link>
                          ) : (
                            f.weekdayDay(day)
                          )}
                        </td>
                        <td className="py-1.5">{sleep > 0 ? `${f.num(sleep, 1)} ${f.hourUnit}` : "–"}</td>
                        <td className="py-1.5">{w?.resting_hr ?? "–"}</td>
                        <td className="py-1.5">{w?.body_battery_high ?? "–"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {d.recovery.baseline_rhr && (
              <p className="mt-3 text-[11.5px] text-ink-muted">
                {m.baselineRhr(Math.round(d.recovery.baseline_rhr), t.zonesSettings.rhrSource(d.recovery.baseline_rhr_source))}
              </p>
            )}
          </Card>,
        ]}
        filler={<RecentActivities items={d.recent} fill />}
      />
    </div>
  );
}
