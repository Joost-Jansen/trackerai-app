"use client";

// One activity: map coloured per zone, heart rate/pace/altitude, time per zone, kilometres and laps,
// and what the data says about it (drift, comparison with earlier runs on the same route, multisport on that day).
// Static export: the id is in the query (?id=...), not in the path.

import { Suspense, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import ZoneBar from "@/components/ZoneBar";
import StreamChart from "@/components/charts/StreamChart";
import LineChart from "@trackerai/ui/charts/LineChart";
import { api } from "@/lib/api";
import { routeName, useFormat, useT, type Format, type Messages } from "@/lib/i18n";
import { SportBadge } from "@/components/plan/SportIcon";
import ActivityGear from "@/components/history/ActivityGear";
import DistanceCorrection from "@/components/history/DistanceCorrection";
import { effortKind } from "@/lib/sports";
import { type ActivityDetail, zoneShare } from "@/lib/training";

const ActivityMap = dynamic(() => import("@/components/map/ActivityMap"), {
  ssr: false,
  loading: () => <div className="h-[360px] animate-pulse rounded bg-[var(--surface-inset)]" />,
});

const href = (id: string) => `/history/activity/?id=${encodeURIComponent(id)}`;

function Stat({ label, value, note }: { label: string; value: React.ReactNode; note?: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-[11.5px] text-ink-muted">{label}</span>
      <span className="font-display text-[21px] leading-tight tabular-nums">{value}</span>
      {note && <span className="text-[11px] text-ink-muted">{note}</span>}
    </div>
  );
}

function Insights({ a }: { a: ActivityDetail }) {
  const t = useT();
  const f = useFormat();
  const T = t.texts;
  const items: { title: string; text: string; tone?: "good" | "warn" }[] = [];
  const multi = a.same_day.filter((x) => ["swim", "ride", "run"].includes(x.sport) && x.start_local < a.start_local);
  if (a.sport === "run" && multi.some((x) => x.sport !== "run")) {
    items.push({ title: t.activity.afterMultisport, text: T.afterMultisport(multi.map((x) => x.sport)), tone: "warn" });
  }
  if (a.decoupling_pct != null) {
    const d = a.decoupling_pct;
    items.push(
      d <= 5
        ? { title: t.activity.drift(f.trim(d, 2)), text: T.driftGood, tone: "good" }
        : { title: t.activity.drift(f.trim(d, 2)), text: T.driftHigh, tone: "warn" },
    );
  }
  const hist = a.route?.history.filter((r) => r.pace_s_per_km) ?? [];
  if (a.route && hist.length >= 2) {
    const me = hist.find((r) => r.id === a.id);
    const others = hist.filter((r) => r.id !== a.id);
    const sorted = [...hist].sort((x, y) => x.pace_s_per_km! - y.pace_s_per_km!);
    const rank = me ? sorted.findIndex((r) => r.id === a.id) + 1 : null;
    const avgHr = others.filter((r) => r.avg_hr).map((r) => r.avg_hr!);
    const hrText =
      me?.avg_hr && avgHr.length ? t.activity.hrVsAvg(me.avg_hr, Math.round(avgHr.reduce((s, v) => s + v, 0) / avgHr.length)) : "";
    if (rank)
      items.push({
        title: t.activity.rank(rank, hist.length),
        text: `${t.activity.fastest(f.pace(sorted[0].pace_s_per_km), f.weekdayDay(sorted[0].date))}${hrText}`,
      });
  }
  const bounds = a.zone_bounds;
  const z = a.hr_zones_s;
  if (z && bounds) {
    const total = Object.values(z).reduce((s, v) => s + v, 0);
    const easy = total ? ((z.Z1 + z.Z2) / total) * 100 : 0;
    if (total > 1200 && easy >= 80) items.push({ title: t.activity.easy, text: T.easySession(Math.round(easy), bounds[1]), tone: "good" });
    else if (total > 1200 && (z.Z4 + z.Z5) / total >= 0.25)
      items.push({ title: t.activity.hard, text: T.hardSession(Math.round(((z.Z4 + z.Z5) / total) * 100)) });
  }
  if (!items.length) return null;
  return (
    <Card title={t.activity.insights}>
      <ul className="flex flex-col gap-3">
        {items.map((i) => (
          <li key={i.title} className="flex gap-3 text-[13px]">
            <span
              className="mt-1.5 inline-block h-2 w-2 flex-none rounded-full"
              style={{ background: i.tone === "good" ? "var(--zone-2)" : i.tone === "warn" ? "var(--zone-4)" : "var(--zone-1)" }}
            />
            <span>
              <span className="font-medium">{i.title}.</span> <span className="text-ink-muted">{i.text}</span>
            </span>
          </li>
        ))}
      </ul>
      {a.decoupling_pct != null && <p className="mt-3 text-[11.5px] text-ink-muted">{T.driftMethod}</p>}
    </Card>
  );
}

function Detail({ id }: { id: string }) {
  const t = useT();
  const f = useFormat();
  const [cursor, setCursor] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["activity", id], queryFn: () => api.get<ActivityDetail>(`/api/activities/${encodeURIComponent(id)}`) });
  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{t.activity.notFound}</p>;
  const a = q.data;
  const share = zoneShare(a.hr_zones_s);
  const s = a.series;
  const routeRuns = a.route?.history.filter((r) => r.pace_s_per_km) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px]">
        <Link href="/history/" className="text-ink-muted hover:underline">
          {t.activity.back}
        </Link>
        <span className="flex gap-4">
          {a.prev_id && (
            <Link href={href(a.prev_id)} className="text-ink-muted hover:underline">
              {t.activity.prev}
            </Link>
          )}
          {a.next_id && (
            <Link href={href(a.next_id)} className="text-ink-muted hover:underline">
              {t.activity.next}
            </Link>
          )}
        </span>
      </div>

      <Card>
        <div className="mb-4 flex items-start gap-3">
          <span className="mt-1">
            <SportBadge sport={a.sport} size={36} />
          </span>
          <div className="min-w-0">
            <div className="text-[12.5px] text-ink-muted">
              {f.weekdayDayYear(a.start_local.slice(0, 10))} · {a.start_local.slice(11, 16)} · {t.sport(a.sport)}
            </div>
            <h1 className="font-display text-[27px] font-light leading-tight">{a.name ?? t.sport(a.sport)}</h1>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {a.distance_km ? <Stat label={t.activity.distance} value={f.km(a.distance_km)} /> : null}
          <Stat
            label={t.activity.time}
            value={f.clock(a.moving_time_s)}
            note={
              a.elapsed_time_s && a.elapsed_time_s - (a.moving_time_s ?? 0) > 60 ? t.activity.total(f.clock(a.elapsed_time_s)) : undefined
            }
          />
          {a.distance_km ? (
            <Stat label={effortKind(a.sport) === "speed" ? t.activity.speed : t.activity.pace} value={f.intensity(a)} />
          ) : null}
          {a.avg_hr ? <Stat label={t.activity.hr} value={`${a.avg_hr}`} note={a.max_hr ? t.activity.max(a.max_hr) : undefined} /> : null}
          {a.elevation_gain_m ? <Stat label={t.activity.elevation} value={`${Math.round(a.elevation_gain_m)} m`} /> : null}
          {a.avg_cadence_spm ? (
            <Stat label={t.activity.cadence} value={`${a.avg_cadence_spm}`} note={t.activity.stepsPerMin} />
          ) : a.vo2max ? (
            <Stat label="VO2max" value={a.vo2max} />
          ) : null}
        </div>
        <div className="mt-3">
          <DistanceCorrection a={a} />
        </div>
        <div className="mt-3">
          <ActivityGear a={a} />
        </div>
      </Card>

      {a.same_day.length > 0 && (
        <p className="text-[12.5px] text-ink-muted">
          {t.activity.sameDay}{" "}
          {a.same_day.map((x, i) => (
            <span key={x.id}>
              {i > 0 && " · "}
              <Link className="underline underline-offset-2" href={href(x.id)}>
                {t.sport(x.sport)} {x.start_local.slice(11, 16)}
                {x.distance_km ? ` (${f.km(x.distance_km)})` : ""}
              </Link>
            </span>
          ))}
        </p>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[1.3fr_1fr]">
        {a.track && (
          <Card title={t.activity.route}>
            <ActivityMap track={a.track} cursor={cursor} />
            <p className="mt-2 text-[11.5px] text-ink-muted">{t.activity.routeNote}</p>
          </Card>
        )}
        <div className="flex flex-col gap-4">
          {share && (
            <Card title={t.activity.zones}>
              <ZoneBar sport={a.sport} share={share} bounds={a.zone_bounds ?? undefined} />
              {a.zone_estimate && <p className="mt-3 text-[11.5px] text-ink-muted">{t.texts.zoneEstimate(a.sport)}</p>}
            </Card>
          )}
          <Insights a={a} />
        </div>
      </div>

      {s && (
        <Card title={t.activity.streams}>
          <StreamChart
            time={s.time}
            heartrate={s.heartrate}
            velocity={s.velocity}
            altitude={s.altitude}
            bounds={a.zone_bounds}
            sport={a.sport}
            onCursor={setCursor}
          />
        </Card>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-2">
        {a.splits.length > 0 && (
          <Card title={t.activity.perKm}>
            <SplitTable splits={a.splits} t={t} f={f} />
          </Card>
        )}
        {a.laps.length > 1 && !(a.splits.length > 0 && a.laps.slice(0, -1).every((l) => Math.abs((l.distance_km ?? 0) - 1) < 0.02)) && (
          <Card title={t.activity.laps}>
            <table className="w-full text-[12.5px] tabular-nums">
              <thead>
                <tr className="text-left text-[11.5px] text-ink-muted">
                  <th className="pb-2 font-normal">#</th>
                  <th className="pb-2 font-normal">{t.activity.distance}</th>
                  <th className="pb-2 font-normal">{t.activity.time}</th>
                  <th className="pb-2 font-normal">{effortKind(a.sport) === "speed" ? t.activity.speed : t.activity.pace}</th>
                  <th className="pb-2 font-normal">{t.activity.hrShort}</th>
                </tr>
              </thead>
              <tbody>
                {a.laps.map((l, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-1.5 text-ink-muted">{i + 1}</td>
                    <td className="py-1.5">{f.km(l.distance_km)}</td>
                    <td className="py-1.5">{f.clock(l.time_s)}</td>
                    <td className="py-1.5">
                      {a.sport === "run"
                        ? (l.pace ?? "–")
                        : f.intensity({ sport: a.sport, moving_time_s: l.time_s, distance_km: l.distance_km })}
                    </td>
                    <td className="py-1.5">{l.avg_hr ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>

      {a.route && routeRuns.length >= 2 && (
        <Card title={t.activity.earlier(routeName(a.route.name, a.route.id, t, f))} more={t.nav.items.routes} moreHref="/routes/">
          <LineChart
            ariaLabel={t.activity.paceAria}
            height={170}
            format={(v) => f.clock(-v)}
            endLabels={false}
            xFormat={(d) => f.monthShortYear(d)}
            series={[
              {
                label: t.activity.pace,
                colour: "var(--chart-1)",
                width: 2,
                fill: true,
                points: routeRuns.map((r) => ({ d: r.date, v: -r.pace_s_per_km! })),
              },
            ]}
          />
          <ul className="mt-3 grid grid-cols-2 gap-x-4 text-[12px] tabular-nums sm:grid-cols-3">
            {[...routeRuns]
              .reverse()
              .slice(0, 9)
              .map((r) => (
                <li key={r.id} className={r.id === a.id ? "font-semibold" : "text-ink-muted"}>
                  <Link href={href(r.id)} className="hover:underline">
                    {f.day(r.date)} · {f.pace(r.pace_s_per_km)}
                    {r.avg_hr ? ` · ${r.avg_hr}` : ""}
                  </Link>
                </li>
              ))}
          </ul>
        </Card>
      )}
      <p className="text-[11px] text-ink-muted">{t.activity.footer(f.hours(a.moving_time_s), a.calories ?? null)}</p>
    </div>
  );
}

function SplitTable({ splits, t, f }: { splits: ActivityDetail["splits"]; t: Messages; f: Format }) {
  const fastest = Math.min(...splits.map((s) => s.seconds));
  const slowest = Math.max(...splits.map((s) => s.seconds));
  return (
    <table className="w-full text-[12.5px] tabular-nums">
      <thead>
        <tr className="text-left text-[11.5px] text-ink-muted">
          <th className="pb-2 font-normal">Km</th>
          <th className="pb-2 font-normal">{t.activity.pace}</th>
          <th className="w-1/3 pb-2 font-normal" />
          <th className="pb-2 font-normal">{t.activity.hrShort}</th>
          <th className="pb-2 font-normal">{t.activity.height}</th>
        </tr>
      </thead>
      <tbody>
        {splits.map((s) => (
          <tr key={s.km} className="border-t border-border">
            <td className="py-1.5 text-ink-muted">{s.km}</td>
            <td className={`py-1.5 ${s.seconds === fastest ? "font-semibold" : ""}`}>{f.clock(s.seconds)}</td>
            <td className="py-1.5 pr-3">
              <span
                className="block h-1.5 rounded-full"
                style={{
                  width: `${40 + (60 * (slowest - s.seconds)) / Math.max(1, slowest - fastest)}%`,
                  background: "var(--chart-1)",
                  opacity: 0.7,
                }}
              />
            </td>
            <td className="py-1.5">{s.avg_hr ?? "–"}</td>
            <td className="py-1.5 text-ink-muted">
              {s.elevation_m != null ? `${s.elevation_m > 0 ? "+" : ""}${Math.round(s.elevation_m)} m` : "–"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function WithId() {
  const t = useT();
  const id = useSearchParams().get("id");
  if (!id) return <p className="text-sm text-ink-muted">{t.activity.none}</p>;
  return <Detail id={id} />;
}

export default function ActivityPage() {
  const t = useT();
  return (
    <Suspense fallback={<p className="text-sm text-ink-muted">{t.common.loading}</p>}>
      <WithId />
    </Suspense>
  );
}
