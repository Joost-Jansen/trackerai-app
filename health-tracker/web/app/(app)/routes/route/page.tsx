"use client";

// One route: map, pace (running) or speed (cycling) over time with a trend line, and every time you
// ran or rode it. It can be renamed here.

import { Suspense, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button } from "@/components/ds";
import TrendChart from "@/components/charts/TrendChart";
import { api } from "@/lib/api";
import { errorText, routeName, useFormat, useT } from "@/lib/i18n";
import { type RouteDetail, type RouteLengthVariant, ZONE_COLOUR, ZONES } from "@/lib/training";
import LengthVariants from "@/components/routes/LengthVariants";
import { asSport, fmtEffort, kmhFromPace, listHref } from "../sport";

const RoutesMap = dynamic(() => import("@/components/map/RoutesMap"), { ssr: false });

function Rename({ route }: { route: RouteDetail }) {
  const t = useT();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(route.name ?? "");
  const [error, setError] = useState<string | null>(null);
  if (!open)
    return (
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        {t.routes.rename}
      </Button>
    );
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api.patch(`/api/routes/${route.id}`, { name });
          setOpen(false);
          qc.invalidateQueries({ queryKey: ["route", route.id] });
          qc.invalidateQueries({ queryKey: ["routes"] });
        } catch (err) {
          setError(errorText(err, t, t.common.failed));
        }
      }}
    >
      <input
        className="ds-input h-8 w-56 text-[13px]"
        value={name}
        onChange={(e) => setName(e.target.value)}
        autoFocus
        aria-label={t.routes.name}
      />
      <Button size="sm" variant="primary" type="submit">
        {t.common.save}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        {t.common.cancel}
      </Button>
      {error && <span className="text-[12px] text-loss">{error}</span>}
    </form>
  );
}

function Detail({ id }: { id: string }) {
  const t = useT();
  const f = useFormat();
  const fmtDay = (d: string) => f.dayShortYear(d);
  const q = useQuery({
    queryKey: ["route", id],
    queryFn: () => api.get<RouteDetail & { distance_variants?: RouteLengthVariant[] }>(`/api/routes/${encodeURIComponent(id)}`),
  });
  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{t.routes.notFound}</p>;
  const r = q.data;
  const sport = asSport(r.sport);
  const ride = sport === "ride";
  const runs = r.history.filter((h) => h.pace_s_per_km);
  const hrRuns = r.history.filter((h) => h.avg_hr);
  const effRuns = r.history.filter((h) => h.m_per_beat);

  return (
    <div className="flex flex-col gap-4">
      <Link href={listHref(sport)} className="text-[12.5px] text-ink-muted hover:underline">
        {t.routes.back}
      </Link>
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-display text-[27px] font-light leading-tight">{routeName(r.name, r.id, t, f)}</h1>
            <p className="text-[12.5px] tabular-nums text-ink-muted">
              {f.km(r.distance_km)} · {r.is_loop ? t.routes.loop : t.routes.line}
              {r.elevation_gain_m ? ` · ${t.routes.elevationLong(Math.round(r.elevation_gain_m))}` : ""} ·{" "}
              {t.routes.summary(r.runs, t.routes.words[sport].done, r.first_run ? fmtDay(r.first_run) : "–")}
            </p>
            <LengthVariants variants={r.distance_variants} className="block text-[12.5px] text-ink-muted" />
          </div>
          <Rename route={r} />
        </div>
      </Card>
      <div className="grid items-start gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Card title={t.routes.map}>
          <RoutesMap
            height={400}
            lines={[
              ...(r.variants ?? []).map((v) => ({ id: v.id, label: v.date, points: v.track, variant: true })),
              { id: r.id, label: t.routes.mostTypical, points: r.track },
            ]}
          />
          <p className="mt-2 text-[11.5px] text-ink-muted">{t.routes.mapNote(r.variants?.length ?? 0)}</p>
        </Card>
        <div className="flex flex-col gap-4">
          {ride ? (
            <Card title={t.routes.speedTitle}>
              <TrendChart
                label={t.routes.speed}
                points={runs.map((h) => ({ d: h.date, v: kmhFromPace(h.pace_s_per_km)! }))}
                format={(v) => f.num(v, 1)}
                unit={` ${f.kmhUnit}`}
                height={150}
              />
            </Card>
          ) : (
            <Card title={t.routes.paceTitle}>
              <TrendChart
                label={t.routes.pace}
                points={runs.map((h) => ({ d: h.date, v: h.pace_s_per_km! }))}
                format={(v) => f.clock(v)}
                unit="/km"
                lowerIsBetter
                height={150}
              />
            </Card>
          )}
          <Card title={t.routes.efficiencyTitle}>
            <TrendChart
              label={t.routes.efficiency}
              points={effRuns.map((h) => ({ d: h.date, v: h.m_per_beat! }))}
              format={(v) => f.num(v, 2)}
              unit=" m"
              height={120}
              colour="var(--chart-6)"
            />
            <p className="mt-2 text-[11.5px] text-ink-muted">
              {t.texts.efficiency(ride ? "ride" : "run")}{" "}
              {t.routes.avgHr(hrRuns.length ? String(Math.round(hrRuns.reduce((s, h) => s + h.avg_hr!, 0) / hrRuns.length)) : "–")}
            </p>
          </Card>
        </div>
      </div>
      <Card title={t.routes.all}>
        <table className="w-full text-[12.5px] tabular-nums">
          <thead>
            <tr className="text-left text-[11.5px] text-ink-muted">
              <th className="pb-2 font-normal">{t.routes.date}</th>
              <th className="pb-2 font-normal">{t.routes.time}</th>
              <th className="pb-2 font-normal">{ride ? t.routes.speed : t.routes.pace}</th>
              <th className="pb-2 font-normal">{t.routes.hr}</th>
              <th className="pb-2 font-normal">{t.routes.perBeat}</th>
              <th className="hidden w-1/4 pb-2 font-normal sm:table-cell">{t.routes.zones}</th>
            </tr>
          </thead>
          <tbody>
            {[...r.history].reverse().map((h) => {
              const z = h.hr_zones_s;
              const total = z ? ZONES.reduce((s, k) => s + (z[k] ?? 0), 0) : 0;
              return (
                <tr key={h.id} className="border-t border-border">
                  <td className="py-1.5">
                    <Link href={`/history/activity/?id=${encodeURIComponent(h.id)}`} className="hover:underline">
                      {fmtDay(h.date)}
                    </Link>
                  </td>
                  <td className="py-1.5">{f.clock(h.moving_time_s)}</td>
                  <td className={`py-1.5 ${r.best?.activity_id === h.id ? "font-semibold" : ""}`}>
                    {fmtEffort(f, sport, h.pace_s_per_km)}
                  </td>
                  <td className="py-1.5">{h.avg_hr ?? "–"}</td>
                  <td className="py-1.5">{h.m_per_beat ? f.num(h.m_per_beat, 2) : "–"}</td>
                  <td className="hidden py-1.5 sm:table-cell">
                    {total > 0 && (
                      <span className="flex h-1.5 overflow-hidden rounded-full">
                        {ZONES.map((k) =>
                          z![k] ? <span key={k} style={{ width: `${(z![k] / total) * 100}%`, background: ZONE_COLOUR[k] }} /> : null,
                        )}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function WithId() {
  const t = useT();
  const id = useSearchParams().get("id");
  return id ? <Detail id={id} /> : <p className="text-sm text-ink-muted">{t.routes.noneChosen}</p>;
}

export default function RoutePage() {
  const t = useT();
  return (
    <Suspense fallback={<p className="text-sm text-ink-muted">{t.common.loading}</p>}>
      <WithId />
    </Suspense>
  );
}
