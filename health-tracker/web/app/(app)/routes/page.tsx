"use client";

// Routes: running or cycling. "A route of X km" (recurring routes and combinations from the same start, the one
// longest not run/ridden first) and all recognised routes with their shape, best time and whether you are getting faster.
// The sport is in the url (?sport=ride), so going back from a route lands on the same sport.

import { Suspense, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button, EmptyState, Tabs } from "@/components/ds";
import { api } from "@/lib/api";
import { routeName, useFormat, useT, type Format, type Messages } from "@/lib/i18n";
import type { RouteCandidates as Candidates, RouteOption, RouteSport, RouteSummary, RouteWithVariants } from "@/lib/training";
import LengthVariants from "@/components/routes/LengthVariants";
import RouteCandidates from "@/components/routes/RouteCandidates";
import { PRESETS, ROUTE_SPORTS, asSport, fmtEffort, fmtTypical, kmhFromPace, listHref, routeHref as href } from "./sport";

const RoutesMap = dynamic(() => import("@/components/map/RoutesMap"), { ssr: false });

function describe(o: RouteOption, t: Messages, f: Format) {
  const counts = new Map<string, number>();
  o.names.forEach((n, i) => {
    const name = routeName(n, o.parts[i], t, f);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  });
  return [...counts.entries()].map(([n, c]) => (c > 1 ? `${c}× ${n}` : n)).join(" + ");
}

function Suggest({ sport, routes }: { sport: RouteSport; routes: RouteSummary[] }) {
  const t = useT();
  const f = useFormat();
  const [km, setKm] = useState("");
  const [asked, setAsked] = useState<number | null>(null);
  const [pick, setPick] = useState(0);
  const words = t.routes.words[sport];
  const q = useQuery({
    queryKey: ["route-suggest", sport, asked],
    queryFn: () => api.get<{ km: number; options: RouteOption[] }>(`/api/routes/suggest?km=${asked}&sport=${sport}`),
    enabled: asked != null,
  });
  const go = (v: number) => {
    setKm(f.input(v));
    setAsked(v);
    setPick(0);
  };
  const opts = q.data?.options ?? [];
  const chosen = opts[pick];

  return (
    <>
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const v = Number(km.replace(",", "."));
          if (v > 0) go(v);
        }}
      >
        <input className="ds-input w-24" inputMode="decimal" placeholder="km" value={km} onChange={(e) => setKm(e.target.value)} aria-label={t.routes.distanceAria} />
        <Button type="submit" variant="primary" size="sm">{t.routes.find}</Button>
        <span className="flex flex-wrap gap-1.5">
          {PRESETS[sport].presets.map((p) => (
            <button key={p} type="button" className="rounded-full border border-border px-2.5 py-0.5 text-[12px] tabular-nums text-ink-muted hover:bg-[var(--surface-hover)]" onClick={() => go(p)}>
              {f.trim(p)}
            </button>
          ))}
        </span>
      </form>

      {q.isLoading && <p className="mt-3 text-sm text-ink-muted">{t.routes.searching}</p>}
      {asked != null && q.data && opts.length === 0 && <p className="mt-3 text-sm text-ink-muted">{t.routes.none}</p>}
      {opts.length > 0 && (
        <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1fr_1.3fr]">
          <ul className="flex flex-col gap-2">
            {!opts[0].within_tolerance && <li className="text-[12.5px] text-ink-muted">{t.routes.notWithin(f.trim(asked))}</li>}
            {opts.map((o, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => setPick(i)}
                  className={`w-full rounded border px-3 py-2 text-left text-[13px] ${i === pick ? "border-[var(--border-focus)] bg-[var(--surface-sunken)]" : "border-border hover:bg-[var(--surface-hover)]"}`}
                >
                  <span className="font-medium">{describe(o, t, f)}</span>
                  <span className="block text-[12px] tabular-nums text-ink-muted">
                    {t.routes.option(f.km(o.total_km), `${o.deviation_km >= 0 ? "+" : "−"}${f.num(Math.abs(o.deviation_km), 1)}`, o.days_since, words.notDone)}
                  </span>
                </button>
              </li>
            ))}
            {chosen && (
              <li className="text-[12px] text-ink-muted">
                {[...new Set(chosen.parts)].map((p) => {
                  const r = routes.find((x) => x.id === p);
                  return r ? (
                    <span key={p} className="mr-3">
                      <Link href={href(p)} className="underline underline-offset-2">{routeName(r.name, p, t, f)}</Link>{t.routes.typicalAt(fmtTypical(f, r), String(r.median_hr ?? "–"))}
                    </span>
                  ) : null;
                })}
              </li>
            )}
          </ul>
          {chosen && <RoutesMap lines={[...new Set(chosen.parts)].map((p) => ({ id: p, label: routeName(chosen.names[chosen.parts.indexOf(p)], p, t, f), points: chosen.tracks[p] ?? [] }))} height={300} />}
        </div>
      )}
    </>
  );
}

function Trend({ r }: { r: RouteSummary }) {
  const t = useT();
  const f = useFormat();
  // Efficiency (metres per heartbeat) corrects for how hard you ran; pace alone says little when you
  // sometimes run the route easy and sometimes fast.
  if (r.recent_efficiency && r.earlier_efficiency) {
    const pct = ((r.recent_efficiency - r.earlier_efficiency) / r.earlier_efficiency) * 100;
    if (Math.abs(pct) < 1.5) return <span className="text-ink-muted">{t.routes.efficiencySame}</span>;
    return <span className={pct > 0 ? "text-gain" : "text-loss"}>{pct > 0 ? t.routes.moreEfficient : t.routes.lessEfficient} ({pct > 0 ? "+" : "−"}{f.num(Math.abs(pct))}% {t.routes.perBeat})</span>;
  }
  if (!r.recent_pace_s_per_km || !r.earlier_pace_s_per_km) return null;
  if (asSport(r.sport) === "ride") {
    const d = kmhFromPace(r.recent_pace_s_per_km)! - kmhFromPace(r.earlier_pace_s_per_km)!;
    if (Math.abs(d) < 0.3) return <span className="text-ink-muted">{t.routes.same}</span>;
    return <span className={d > 0 ? "text-gain" : "text-loss"}>{d > 0 ? t.routes.faster : t.routes.slower} ({d > 0 ? "+" : "−"}{f.num(Math.abs(d), 1)} {f.kmhUnit})</span>;
  }
  const diff = r.recent_pace_s_per_km - r.earlier_pace_s_per_km;
  if (Math.abs(diff) < 3) return <span className="text-ink-muted">{t.routes.same}</span>;
  return <span className={diff < 0 ? "text-gain" : "text-loss"}>{diff < 0 ? t.routes.faster : t.routes.slower} ({diff < 0 ? "−" : "+"}{Math.abs(diff)} s/km)</span>;
}

function Routes({ sport, onSport }: { sport: RouteSport; onSport: (s: RouteSport) => void }) {
  const t = useT();
  const f = useFormat();
  const q = useQuery({ queryKey: ["routes", sport], queryFn: () => api.get<RouteWithVariants[]>(`/api/routes?sport=${sport}`) });
  const cands = useQuery({ queryKey: ["route-candidates", sport], queryFn: () => api.get<Candidates>(`/api/routes/candidates?sport=${sport}`) });
  const words = t.routes.words[sport];
  const routes = q.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <Card title={words.suggestTitle} action={<Tabs variant="segmented" items={ROUTE_SPORTS.map((id) => ({ id, label: t.routes.tabs[id] }))} value={sport} onChange={(v) => onSport(asSport(v))} ariaLabel={t.history.sport} />}>
        {q.isLoading ? (
          <p className="text-sm text-ink-muted">{t.common.loading}</p>
        ) : !q.data ? (
          <p className="text-sm text-ink-muted">{t.routes.loadFailed}</p>
        ) : routes.length === 0 ? (
          <EmptyState
            title={sport === "ride" ? t.routes.emptyRide : t.routes.emptyRun}
            body={sport === "ride" ? t.routes.emptyRideBody : t.routes.emptyRunBody}
          />
        ) : (
          <Suggest key={sport} sport={sport} routes={routes} />
        )}
      </Card>
      <RouteCandidates key={sport} sport={sport} candidates={cands.data?.candidates ?? []} done={words.done} />
      {routes.length > 0 && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {routes.map((r) => (
              <Link key={r.id} href={href(r.id)} className="group">
                <Card className="h-full transition-colors group-hover:border-[var(--border-strong)]">
                  <div className="flex flex-col gap-3">
                    <div className="-mx-1 -mt-1">
                      <RoutesMap
                        interactive={false}
                        height={170}
                        lines={[
                          ...(r.variants ?? []).map((v) => ({ id: v.id, points: v.track, variant: true })),
                          { id: r.id, points: r.track },
                        ]}
                      />
                    </div>
                    <div className="min-w-0 text-[12.5px]">
                      <div className="truncate text-[14px] font-semibold">{routeName(r.name, r.id, t, f)}</div>
                      <div className="tabular-nums text-ink-muted">{f.km(r.distance_km)} · {r.is_loop ? t.routes.loop : t.routes.line}{r.elevation_gain_m ? ` · ${t.routes.elevationShort(Math.round(r.elevation_gain_m))}` : ""}</div>
                      <LengthVariants variants={r.distance_variants} className="block text-ink-muted" />
                      <div className="mt-1.5 tabular-nums">{t.routes.timesDone(r.runs, words.done, f.day(r.last_run))}</div>
                      <div className="tabular-nums text-ink-muted">{t.routes.typical(fmtTypical(f, r), String(r.median_hr ?? "–"))}</div>
                      {r.best && <div className="tabular-nums">{t.routes.best(fmtEffort(f, sport, r.best.pace_s_per_km), f.day(r.best.date))}</div>}
                      <div className="text-[12px]"><Trend r={r} /></div>
                    </div>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
          <p className="text-[11.5px] text-ink-muted">
            {t.texts.routeRule(sport, PRESETS[sport].minCount)} {t.texts.routeTrend}
          </p>
        </>
      )}
      <p className="text-[11.5px] text-ink-muted">{t.texts.routes.auto(cands.data?.last_sync ? f.dateTime(cands.data.last_sync.split(";")[0]) : null)}</p>
    </div>
  );
}

function WithSport() {
  const router = useRouter();
  const sport = asSport(useSearchParams().get("sport"));
  return <Routes sport={sport} onSport={(s) => router.replace(listHref(s), { scroll: false })} />;
}

export default function RoutesPage() {
  const t = useT();
  return (
    <Suspense fallback={<p className="text-sm text-ink-muted">{t.common.loading}</p>}>
      <WithSport />
    </Suspense>
  );
}
