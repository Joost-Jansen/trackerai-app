"use client";

// Kilometres per week of the plan: the planned week as a light bar, what was done as a solid bar inside it.
// That shows the build-up or taper at a glance, and how well you follow it. Per sport, because 50 km cycling and
// 10 km running do not add up to anything meaningful.

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useFormat, useT } from "@/lib/i18n";
import type { PlanSession } from "@/lib/training";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import { type Week, kmBySport, sportColour } from "./plan";

const RACE = /\b(wedstrijd|race)\b(?!\s*-?\s*(tempo|pace))/i; // not "race pace"

export default function VolumeChart({ weeks, today, raceDate }: { weeks: Week[]; today: string; raceDate: string | null }) {
  const t = useT();
  const f = useFormat();
  const v = t.plan.volume;
  const fmtNum = (n: number) => f.trim(n);
  const sports = useMemo(() => {
    const all = kmBySport(weeks.flatMap((w) => w.sessions) as PlanSession[]);
    return Object.entries(all)
      .filter(([, v]) => v.planned > 0)
      .sort((a, b) => (a[0] === "run" ? -1 : b[0] === "run" ? 1 : b[1].planned - a[1].planned))
      .map(([s]) => s);
  }, [weeks]);
  const [pick, setPick] = useState<string | null>(null);
  const [active, setActive] = useState<number | null>(null); // the week under the pointer (or tapped): its box
  // A long plan in a narrow card leaves a few pixels per week: then labels are thinned out instead of overlapping
  // (the tooltip on each bar still has the numbers).
  const barsRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = barsRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const sport = pick && sports.includes(pick) ? pick : sports[0];
  if (!sport) return null;

  const rows = weeks.map((w) => {
    const v = w.km[sport] ?? { planned: 0, done: 0 };
    // The race itself separately: otherwise race week looks like the heaviest of the plan and the taper is invisible.
    const raceKm = w.sessions.filter((s) => s.sport === sport && RACE.test(s.kind ?? "")).reduce((t, s) => t + (s.distance_km ?? 0), 0);
    const started = w.monday <= today;
    return {
      ...w,
      ...v,
      raceKm,
      started,
      current: today >= w.monday && today <= w.days[6].date,
      race: !!raceDate && raceDate >= w.monday && raceDate <= w.days[6].date,
    };
  });
  const peak = Math.max(...rows.map((r) => Math.max(r.planned, r.done)), 1);
  const colour = sportColour(sport);
  const total = rows.reduce((s, r) => s + r.planned, 0);
  const done = rows.reduce((s, r) => s + r.done, 0);
  const tight = rows.length > 10;
  const colW = width ? width / rows.length : 60;
  const values: "full" | "short" | "current" = colW >= 60 ? "full" : colW >= 30 ? "short" : "current";
  const step = Math.max(1, Math.ceil(44 / colW)); // a date label is about 40px wide
  const nearMarker = (i: number) => [i - 1, i + 1].some((j) => rows[j] && (rows[j].current || rows[j].race));

  return (
    <section className="flex flex-col rounded border border-border bg-surface p-4 sm:p-[18px]">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-[13.5px] font-semibold">
          {v.title}
          <InfoPopover label={t.common.explain(v.title.toLowerCase())}>{t.texts.plan.volume}</InfoPopover>
        </h2>
        {sports.length > 1 && (
          <div className="flex gap-1" role="group" aria-label={v.sport}>
            {sports.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={s === sport}
                onClick={() => setPick(s)}
                className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12px] ${s === sport ? "bg-[var(--surface-active)] font-semibold" : "text-ink-muted hover:bg-[var(--surface-hover)]"}`}
              >
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: sportColour(s) }} aria-hidden />
                {t.sport(s)}
              </button>
            ))}
          </div>
        )}
      </div>
      <p className="mb-3 text-[12px] tabular-nums text-ink-muted">{v.doneOf(fmtNum(done), fmtNum(total), sport)}</p>
      <div
        ref={barsRef}
        className={`relative flex h-[132px] items-end lg:h-auto lg:min-h-[132px] lg:flex-1 ${tight ? "gap-1" : "gap-2 sm:gap-3"}`}
        role="list"
        aria-label={v.aria(sport)}
        onMouseLeave={() => setActive(null)}
      >
        {rows.map((r, i) => (
          <div
            key={r.monday}
            role="listitem"
            tabIndex={0}
            aria-label={v.bar(f.dayMonth(r.monday), fmtNum(r.done), fmtNum(r.planned))}
            className="flex h-full min-w-0 flex-1 cursor-default flex-col items-center justify-end outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-focus)]"
            onMouseEnter={() => setActive(i)}
            onFocus={() => setActive(i)}
            onBlur={() => setActive(null)}
            onClick={() => setActive(i)}
          >
            <span className="mb-1 whitespace-nowrap text-[11.5px] tabular-nums text-ink-muted">
              {values === "full" ? (
                <>
                  {r.started && r.done > 0 ? (
                    <>
                      <span className="font-semibold text-[var(--text-primary)]">{fmtNum(r.done)}</span>/
                    </>
                  ) : null}
                  {r.raceKm > 0 && r.planned > r.raceKm ? (
                    <>
                      {fmtNum(r.planned - r.raceKm)}
                      <span className="text-brand"> + {fmtNum(r.raceKm)}</span>
                    </>
                  ) : (
                    fmtNum(r.planned)
                  )}
                </>
              ) : values === "short" || r.current ? (
                r.started && r.done > 0 ? (
                  <span className="font-semibold text-[var(--text-primary)]">{fmtNum(r.done)}</span>
                ) : (
                  fmtNum(r.planned)
                )
              ) : (
                "\u00a0"
              )}
            </span>
            <div
              className="relative w-full max-w-[56px] overflow-hidden rounded-t-[4px]"
              style={{
                height: `${Math.max((Math.max(r.planned, r.done) / peak) * 100, 3)}%`,
                background: `repeating-linear-gradient(135deg, color-mix(in srgb, ${colour} 30%, transparent) 0 4px, color-mix(in srgb, ${colour} 14%, transparent) 4px 8px)`,
                boxShadow: r.current ? `inset 0 0 0 1.5px ${colour}` : undefined,
              }}
            >
              {r.raceKm > 0 && (
                <div
                  className="absolute inset-x-0 top-0"
                  style={{
                    height: `${(r.raceKm / Math.max(r.planned, r.done, 0.001)) * 100}%`,
                    background: "color-mix(in srgb, var(--surface-brand) 22%, var(--surface-card))",
                    boxShadow: "inset 0 0 0 1.5px var(--surface-brand)",
                    borderRadius: "4px 4px 0 0",
                  }}
                />
              )}
              <div
                className="absolute inset-x-0 bottom-0"
                style={{ height: `${(r.done / Math.max(r.planned, r.done, 0.001)) * 100}%`, background: colour }}
              />
            </div>
          </div>
        ))}
        {/* the week under the pointer in one box beside its bar, as on the other charts */}
        {active != null && rows[active] && (
          <div
            className="ds-chart__tip"
            aria-live="polite"
            style={{
              left: ((active + 0.5) / rows.length) * (width || 1) + (active >= rows.length / 2 ? -10 : 10),
              top: 0,
              transform: active >= rows.length / 2 ? "translateX(-100%)" : "none",
            }}
          >
            <div className="font-semibold">
              {f.dayMonth(rows[active].monday)} – {f.dayMonth(rows[active].days[6].date)}
            </div>
            <div className="flex justify-between gap-3">
              <span className="opacity-80">{v.done}</span>
              <span className="font-semibold">{rows[active].started ? `${fmtNum(rows[active].done)} km` : "–"}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="opacity-80">{v.planned}</span>
              <span className="font-semibold">{fmtNum(rows[active].planned)} km</span>
            </div>
            {rows[active].raceKm > 0 && (
              <div className="flex justify-between gap-3">
                <span className="opacity-80">{v.raceLegend}</span>
                <span className="font-semibold">{fmtNum(rows[active].raceKm)} km</span>
              </div>
            )}
          </div>
        )}
      </div>
      <div className={`mt-1.5 flex border-t border-border pt-1.5 ${tight ? "gap-1" : "gap-2 sm:gap-3"}`}>
        {rows.map((r, i) => (
          <span
            key={r.monday}
            className={`flex min-w-0 flex-1 justify-center whitespace-nowrap text-[11px] ${r.current ? "font-semibold text-[var(--text-primary)]" : "text-ink-muted"}`}
          >
            {r.race ? v.race : r.current ? v.now : step === 1 || (i % step === 0 && !nearMarker(i)) ? f.dayMonth(r.monday) : ""}
          </span>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: colour }} aria-hidden /> {v.done}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-[3px]"
            style={{
              background: `repeating-linear-gradient(135deg, color-mix(in srgb, ${colour} 40%, transparent) 0 2px, transparent 2px 4px)`,
            }}
            aria-hidden
          />{" "}
          {v.planned}
        </span>
        {rows.some((r) => r.raceKm > 0) && (
          <span className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-[3px]"
              style={{
                background: "color-mix(in srgb, var(--surface-brand) 22%, var(--surface-card))",
                boxShadow: "inset 0 0 0 1.5px var(--surface-brand)",
              }}
              aria-hidden
            />{" "}
            {v.raceLegend}
          </span>
        )}
      </div>
    </section>
  );
}
