"use client";

// History: all activities, filterable by sport, period and name, grouped per month.
// Second view: the heatmap of all routes. Third: gear and its kilometres (#gear in the address, so a link can open it).

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Tabs } from "@/components/ds";
import { api } from "@/lib/api";
import { SportBadge } from "@/components/plan/SportIcon";
import FitUpload from "@/components/history/FitUpload";
import GearView from "@/components/history/GearView";
import { useFormat, useT } from "@/lib/i18n";
import { type ActivityListItem, type Heatmap, ZONE_COLOUR, ZONES } from "@/lib/training";

const HeatMap = dynamic(() => import("@/components/map/HeatMap"), { ssr: false });

const PERIODS = ["all", "30", "90", "365"] as const;

function ZoneStrip({ a }: { a: ActivityListItem }) {
  const z = a.hr_zones_s;
  const total = z ? ZONES.reduce((s, k) => s + (z[k] ?? 0), 0) : 0;
  if (!z || !total) return <span className="block h-1.5 w-full rounded-full" style={{ background: "var(--surface-inset)" }} />;
  return (
    <span
      className="flex h-1.5 w-full overflow-hidden rounded-full"
      title={ZONES.map((k) => `${k} ${Math.round((z[k] / total) * 100)}%`).join(" · ")}
    >
      {ZONES.map((k) => (z[k] ? <span key={k} style={{ width: `${(z[k] / total) * 100}%`, background: ZONE_COLOUR[k] }} /> : null))}
    </span>
  );
}

function ListView() {
  const t = useT();
  const f = useFormat();
  const [sport, setSport] = useState("all");
  const [period, setPeriod] = useState("90");
  const [search, setSearch] = useState("");
  const q = useQuery({ queryKey: ["activities"], queryFn: () => api.get<ActivityListItem[]>("/api/activities") });

  const sports = useMemo(() => {
    const count = new Map<string, number>();
    (q.data ?? []).forEach((a) => count.set(a.sport, (count.get(a.sport) ?? 0) + 1));
    return [...count.entries()].sort((a, b) => b[1] - a[1]).map(([s]) => s);
  }, [q.data]);

  const items = useMemo(() => {
    const from = period === "all" ? "" : new Date(Date.now() - Number(period) * 86400000).toISOString().slice(0, 10);
    const needle = search.trim().toLowerCase();
    return (q.data ?? []).filter(
      (a) =>
        (sport === "all" || a.sport === sport) &&
        (!from || a.start_local.slice(0, 10) >= from) &&
        (!needle || (a.name ?? "").toLowerCase().includes(needle) || a.start_local.includes(needle)),
    );
  }, [q.data, sport, period, search]);

  const groups = useMemo(() => {
    const out: { month: string; items: ActivityListItem[]; km: number; seconds: number }[] = [];
    for (const a of items) {
      const m = a.start_local.slice(0, 7);
      let g = out[out.length - 1];
      if (!g || g.month !== m) out.push((g = { month: m, items: [], km: 0, seconds: 0 }));
      g.items.push(a);
      g.km += a.distance_km ?? 0;
      g.seconds += a.moving_time_s ?? 0;
    }
    return out;
  }, [items]);

  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{t.history.loadFailed}</p>;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="ds-select h-9 w-auto text-[13px]"
          value={sport}
          onChange={(e) => setSport(e.target.value)}
          aria-label={t.history.sport}
        >
          <option value="all">{t.sport("all")}</option>
          {sports.map((s) => (
            <option key={s} value={s}>
              {t.sport(s)}
            </option>
          ))}
        </select>
        <Tabs
          variant="quiet"
          items={PERIODS.map((id) => ({ id, label: t.history.periods[id] }))}
          value={period}
          onChange={setPeriod}
          ariaLabel={t.history.period}
        />
        <input
          className="ds-input h-9 min-w-0 flex-1 text-[13px] sm:max-w-[240px]"
          placeholder={t.history.search}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="ml-auto text-[12px] text-ink-muted tabular-nums">{t.history.count(items.length)}</span>
        <FitUpload />
      </div>

      {groups.length === 0 && <p className="text-sm text-ink-muted">{t.history.nothing}</p>}
      {groups.map((g) => (
        <Card
          key={g.month}
          title={f.month(g.month)}
          action={
            <span className="text-[12px] tabular-nums text-ink-muted">
              {g.items.length}× · {f.km(g.km)} · {f.hours(g.seconds)}
            </span>
          }
        >
          <ul className="flex flex-col">
            {g.items.map((a) => (
              <li key={a.id} className="border-t border-border first:border-t-0">
                <Link
                  href={`/history/activity/?id=${encodeURIComponent(a.id)}`}
                  className="grid grid-cols-[76px_1fr] items-center gap-x-3 gap-y-1 py-2.5 text-[13px] hover:bg-[var(--surface-hover)] sm:grid-cols-[92px_1fr_auto_120px] sm:px-1"
                >
                  <span className="text-ink-muted">{f.weekdayDay(a.start_local.slice(0, 10))}</span>
                  <span className="flex min-w-0 items-center gap-2">
                    <SportBadge sport={a.sport} size={22} />
                    <span className="truncate">
                      <span className="font-medium">{t.sport(a.sport)}</span>
                      {a.name && <span className="text-ink-muted"> · {a.name}</span>}
                      {a.has_gps && (
                        <span className="ml-1.5 text-[11px] text-ink-muted" title={t.history.withMap}>
                          ◉
                        </span>
                      )}
                    </span>
                  </span>
                  <span className="col-start-2 tabular-nums text-ink-muted sm:col-start-auto">
                    {a.distance_km ? `${f.km(a.distance_km)} · ${f.intensity(a)}` : f.duration(a.moving_time_s)}
                    {a.distance_doubtful && <span title={t.history.gpsDoubtful}> · GPS?</span>}
                    {a.avg_hr ? ` · ${a.avg_hr} bpm` : ""}
                  </span>
                  <span className="col-start-2 sm:col-start-auto">
                    <ZoneStrip a={a} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

function HeatView() {
  const t = useT();
  const [sport, setSport] = useState("run");
  const q = useQuery({ queryKey: ["heatmap", sport], queryFn: () => api.get<Heatmap>(`/api/heatmap?sport=${sport}`) });
  return (
    <Card
      title={t.history.heatTitle}
      action={
        <Tabs
          variant="segmented"
          items={(["run", "ride", "swim"] as const).map((id) => ({ id, label: t.history.heatSports[id] }))}
          value={sport}
          onChange={setSport}
          ariaLabel={t.history.sport}
        />
      }
    >
      {q.isLoading ? <p className="text-sm text-ink-muted">{t.common.loading}</p> : <HeatMap tracks={q.data?.tracks ?? []} />}
      <p className="mt-3 text-[11.5px] text-ink-muted">
        {q.data ? `${t.history.heatRoutes(q.data.tracks.length)} ` : ""}
        {t.history.heatNote}
      </p>
    </Card>
  );
}

export default function HistoryPage() {
  const t = useT();
  const [view, setView] = useState("list");
  useEffect(() => {
    const fromHash = () => setView(["heat", "gear"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "list");
    fromHash();
    window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
  }, []);
  function choose(id: string) {
    setView(id);
    history.replaceState(null, "", id === "list" ? location.pathname : `#${id}`);
  }
  return (
    <div className="flex flex-col gap-4">
      <Tabs items={(["list", "heat", "gear"] as const).map((id) => ({ id, label: t.history.tabs[id] }))} value={view} onChange={choose} />
      {view === "list" ? <ListView /> : view === "heat" ? <HeatView /> : <GearView />}
    </div>
  );
}
