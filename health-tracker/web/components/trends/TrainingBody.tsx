"use client";

// Training and body: sport and body values over the time bar's window as small multiples, one low panel per value,
// all on the same date axis, with one cursor through every panel and every value at the cursor in one box. So you
// see whether, say, the pace at an easy heart rate drops in the weeks your resting heart rate goes up. The same card
// sits on Trends (training) and Health (over time).
//
// Panels rather than two lines on one chart with two y axes: two axes suggest a relation that the choice of scales
// makes. Daily body values are noisy, so they show faint with their 7-day average on top; their dashed line is the
// user's normal (60-day median). Pace is drawn with faster up. A click (or the link under a tap) opens the day on
// Health. Which panels show is the viewer's choice, kept in localStorage.

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useFormat, useLocale, useT } from "@/lib/i18n";
import { dayNumber, isoDay, movingAverage, timeTicks, type DateWindow, type DayPoint } from "@/lib/timeline";
import { fmtClock, type TrendsPlus } from "@/lib/training";

export const TB_METRICS = ["fitness", "form", "volume", "z2", "vo2", "resting_hr", "sleep_h", "hrv", "sleep_resp", "stress_avg", "sleep_stress", "body_battery_high"] as const;
export type TbMetric = (typeof TB_METRICS)[number];
const DEFAULT: TbMetric[] = ["fitness", "z2", "resting_hr", "sleep_h"];
const STORE = "training-body:panels";
const MAX_PANELS = 6;
const RIGHT = 44;
const PANEL_H = 62;
const MA_DAYS = 7;

type Panel = {
  key: TbMetric;
  colour: string;
  points: DayPoint[];
  /** Daily and noisy: draw faint with the 7-day average on top. */
  smooth: boolean;
  /** Days around a point within which the cursor still reads it (1 daily, 4 weekly, 10 for VO2max). */
  near: number;
  format: (v: number) => string;
  /** Lower is better and drawn upward (pace). */
  invert?: boolean;
  reference?: number | null;
  baseline?: number;
};

function nearest(points: DayPoint[], day: number, near: number): DayPoint | null {
  let best: DayPoint | null = null;
  let gap = Infinity;
  for (const p of points) {
    const g = Math.abs(dayNumber(p.d) - day);
    if (g < gap) [best, gap] = [p, g];
  }
  return best && gap <= near ? best : null;
}

function readStored(): TbMetric[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE) ?? "null");
    if (Array.isArray(raw)) {
      const ok = raw.filter((k): k is TbMetric => (TB_METRICS as readonly string[]).includes(k));
      if (ok.length) return ok;
    }
  } catch {
    /* no storage: the default */
  }
  return DEFAULT;
}

export default function TrainingBody({ t, window: win }: { t: TrendsPlus; window: DateWindow }) {
  const tr = useT();
  const w = tr.trainingBody;
  const f = useFormat();
  const { locale } = useLocale();
  const router = useRouter();
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<number | null>(null);
  const [chosen, setChosen] = useState<TbMetric[]>(DEFAULT);

  useLayoutEffect(() => {
    setChosen(readStored());
    const el = box.current;
    if (!el) return;
    setWidth(el.clientWidth || 720);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth || 720));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const toggle = (k: TbMetric) => {
    const next = chosen.includes(k) ? chosen.filter((x) => x !== k) : chosen.length >= MAX_PANELS ? chosen : [...chosen, k];
    if (!next.length) return;
    // keep the fixed order of TB_METRICS, so sport comes above body whatever the order of clicking
    const ordered = TB_METRICS.filter((m) => next.includes(m));
    setChosen(ordered);
    try {
      localStorage.setItem(STORE, JSON.stringify(ordered));
    } catch {
      /* private window */
    }
  };

  const all = useMemo(() => {
    const daily = t.recovery_daily ?? [];
    const normals = t.recovery_normals ?? {};
    const body = (key: "resting_hr" | "sleep_h" | "hrv" | "sleep_resp" | "stress_avg" | "sleep_stress" | "body_battery_high") =>
      daily.length
        ? daily.filter((r) => r[key] != null).map((r) => ({ d: r.date, v: r[key] as number }))
        : t.recovery_weekly.filter((r) => r[key] != null).map((r) => ({ d: r.week, v: r[key] as number }));
    const int = (v: number) => String(Math.round(v));
    const out: Record<TbMetric, Panel> = {
      fitness: { key: "fitness", colour: "var(--chart-1)", points: t.form.map((r) => ({ d: r.date, v: r.ctl })), smooth: false, near: 1, format: int },
      form: { key: "form", colour: "var(--chart-4)", points: t.form.map((r) => ({ d: r.date, v: r.tsb })), smooth: false, near: 1, format: (v) => `${v > 0 ? "+" : ""}${Math.round(v)}`, baseline: 0 },
      volume: {
        key: "volume",
        colour: "var(--chart-1)",
        points: t.weekly.map((x) => ({ d: x.week, v: Object.values(x.sports).reduce((s, v) => s + v.seconds, 0) / 3600 })),
        smooth: false,
        near: 4,
        format: (v) => f.hours(v * 3600),
      },
      z2: { key: "z2", colour: "var(--zone-2)", points: t.z2_pace.map((r) => ({ d: r.week, v: r.pace_s_per_km })), smooth: false, near: 4, format: (v) => `${fmtClock(v)}/km`, invert: true },
      vo2: { key: "vo2", colour: "var(--chart-3)", points: t.vo2max.map((r) => ({ d: r.date, v: r.value })), smooth: false, near: 10, format: int },
      resting_hr: { key: "resting_hr", colour: "var(--chart-6)", points: body("resting_hr"), smooth: daily.length > 0, near: daily.length ? 1 : 4, format: (v) => `${Math.round(v)} bpm`, reference: normals.resting_hr },
      sleep_h: { key: "sleep_h", colour: "var(--chart-5)", points: body("sleep_h"), smooth: daily.length > 0, near: daily.length ? 1 : 4, format: (v) => f.hours(v * 3600), reference: normals.sleep_h },
      hrv: { key: "hrv", colour: "var(--chart-3)", points: body("hrv"), smooth: daily.length > 0, near: daily.length ? 1 : 4, format: (v) => `${Math.round(v)} ms`, reference: normals.hrv },
      sleep_resp: { key: "sleep_resp", colour: "var(--chart-5)", points: body("sleep_resp"), smooth: daily.length > 0, near: daily.length ? 1 : 4, format: (v) => `${f.num(v, 1)} /min`, reference: normals.sleep_resp },
      stress_avg: { key: "stress_avg", colour: "var(--chart-4)", points: body("stress_avg"), smooth: daily.length > 0, near: daily.length ? 1 : 4, format: int, reference: normals.stress_avg },
      sleep_stress: { key: "sleep_stress", colour: "var(--chart-4)", points: body("sleep_stress"), smooth: daily.length > 0, near: daily.length ? 1 : 4, format: int, reference: normals.sleep_stress },
      body_battery_high: { key: "body_battery_high", colour: "var(--chart-1)", points: body("body_battery_high"), smooth: daily.length > 0, near: daily.length ? 1 : 4, format: int, reference: normals.body_battery_high },
    };
    return out;
  }, [t, f]);

  // Values the watch never gave (HRV on most watches) are not offered.
  const available = TB_METRICS.filter((k) => all[k].points.length >= 2);
  const a = dayNumber(win.from);
  const b = dayNumber(win.to);
  const plotW = Math.max(width - RIGHT, 10);
  const x = (day: number) => ((day - a) / Math.max(b - a, 1)) * plotW;
  const ticks = timeTicks(a, b, plotW, locale);
  const shown = chosen
    .filter((k) => available.includes(k))
    .map((k) => {
      const p = all[k];
      const inside = p.points.filter((q) => q.d >= win.from && q.d <= win.to);
      return { ...p, inside, avg: p.smooth ? movingAverage(p.points, MA_DAYS).filter((q) => q.d >= win.from && q.d <= win.to) : [] };
    });

  const locate = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return;
    const frac = Math.min(Math.max((clientX - rect.left) / plotW, 0), 1);
    setHover(Math.round(a + frac * (b - a)));
  };
  const hoverDay = hover != null ? isoDay(hover) : null;

  return (
    <div className="flex flex-col gap-3">
      {/* One scrolling row on a phone, wrapped from sm up. */}
      <div className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0" role="group" aria-label={w.choose}>
        {available.map((k) => {
          const on = chosen.includes(k);
          return (
            <button
              key={k}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(k)}
              className={`flex flex-none items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-[12px] ${on ? "border-[var(--border-strong)] bg-[var(--surface-inset)] text-[var(--text-primary)]" : "border-border text-ink-muted hover:text-[var(--text-primary)]"}`}
            >
              <span aria-hidden className="inline-block h-[3px] w-2.5 rounded-full" style={{ background: on ? all[k].colour : "var(--border-strong)" }} />
              {w.metric[k]}
            </button>
          );
        })}
      </div>

      <div
        ref={box}
        className="relative flex select-none flex-col gap-2 outline-none"
        tabIndex={0}
        role="group"
        aria-label={w.aria}
        style={{ WebkitTouchCallout: "none", touchAction: "pan-y" }}
        onMouseMove={(e) => locate(e.clientX)}
        onMouseLeave={() => setHover(null)}
        onTouchStart={(e) => locate(e.touches[0].clientX)}
        onTouchMove={(e) => locate(e.touches[0].clientX)}
        onClick={(e) => {
          // a mouse click opens the day; a tap only shows the values (the link below opens it)
          if (hoverDay && (e.nativeEvent as PointerEvent).pointerType === "mouse") router.push(`/dashboard/body/?day=${hoverDay}`);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hoverDay) router.push(`/dashboard/body/?day=${hoverDay}`);
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
          e.preventDefault();
          const step = (e.shiftKey ? 7 : 1) * (e.key === "ArrowRight" ? 1 : -1);
          setHover((d) => Math.min(b, Math.max(a, (d ?? b) + step)));
        }}
        onBlur={() => setHover(null)}
      >
        {shown.map((p) => {
          const values = [...p.inside.map((q) => q.v), ...(p.reference != null ? [p.reference] : []), ...(p.baseline != null ? [p.baseline] : [])];
          if (!values.length) {
            return (
              <div key={p.key}>
                <div className="text-[11.5px] text-ink-muted">{w.metric[p.key]}</div>
                <p className="py-3 text-[12px] text-ink-muted">{w.noData}</p>
              </div>
            );
          }
          let lo = Math.min(...values);
          let hi = Math.max(...values);
          const pad = (hi - lo) * 0.08 || 1;
          [lo, hi] = [lo - pad, hi + pad];
          const y = (v: number) => {
            const frac = (v - lo) / (hi - lo || 1);
            return 4 + (p.invert ? frac : 1 - frac) * (PANEL_H - 8);
          };
          const path = (pts: DayPoint[]) => pts.map((q, i) => `${i ? "L" : "M"}${x(dayNumber(q.d)).toFixed(1)} ${y(q.v).toFixed(1)}`).join("");
          const hv = hover != null ? nearest(p.inside, hover, p.near) : null;
          const last = p.inside[p.inside.length - 1];
          return (
            <div key={p.key}>
              <div className="flex items-baseline justify-between text-[11.5px] text-ink-muted" style={{ width: plotW }}>
                <span className="flex items-center gap-1.5">
                  <span aria-hidden className="inline-block h-[3px] w-3 rounded-full" style={{ background: p.colour }} />
                  {w.metric[p.key]}
                  {p.invert && <span className="opacity-80">({w.fasterUp})</span>}
                </span>
                <span className="tabular-nums">{hover != null ? (hv ? p.format(hv.v) : "–") : last ? p.format(last.v) : ""}</span>
              </div>
              <svg width={width} height={PANEL_H} className="block overflow-visible" role="img" aria-label={w.metric[p.key]}>
                <g className="ds-chart__grid">
                  <line x1="0" x2={plotW} y1={y(p.invert ? lo : hi)} y2={y(p.invert ? lo : hi)} />
                  <line x1="0" x2={plotW} y1={y(p.invert ? hi : lo)} y2={y(p.invert ? hi : lo)} />
                </g>
                {(p.reference ?? p.baseline) != null && (
                  <line x1="0" x2={plotW} y1={y((p.reference ?? p.baseline)!)} y2={y((p.reference ?? p.baseline)!)} stroke="var(--chart-2)" strokeWidth="1" strokeDasharray="4 4" opacity={0.7} />
                )}
                <path className="ds-chart__line" d={path(p.inside)} stroke={p.colour} strokeWidth={p.smooth ? 1 : 1.6} opacity={p.smooth ? 0.35 : 1} />
                {p.smooth && <path className="ds-chart__line" d={path(p.avg)} stroke={p.colour} strokeWidth={1.8} />}
                {hover != null && <line className="ds-chart__cursor" x1={x(hover)} x2={x(hover)} y1={0} y2={PANEL_H} />}
                {hv && <circle className="ds-chart__dot" cx={x(dayNumber(hv.d))} cy={y(hv.v)} r="3" fill={p.colour} />}
              </svg>
            </div>
          );
        })}

        <svg width={width} height={14} className="block" aria-hidden>
          <g className="ds-chart__axis">
            {ticks.map((tk) => (
              <text key={tk.day} x={x(tk.day)} y={11} textAnchor={x(tk.day) < 16 ? "start" : x(tk.day) > plotW - 16 ? "end" : "middle"}>
                {tk.label}
              </text>
            ))}
          </g>
        </svg>

        {hover != null && hoverDay && (
          <div
            className="ds-chart__tip"
            aria-live="polite"
            style={{ left: x(hover) + (x(hover) > plotW / 2 ? -12 : 12), top: 18, transform: x(hover) > plotW / 2 ? "translateX(-100%)" : "none" }}
          >
            <div className="font-semibold">{f.weekdayDay(hoverDay)}</div>
            {shown.map((p) => {
              const hv = nearest(p.inside, hover, p.near);
              return (
                <div key={p.key} className="flex items-center gap-1.5">
                  <span aria-hidden className="inline-block h-[3px] w-2.5 rounded-full" style={{ background: p.colour }} />
                  <span className="opacity-80">{w.metric[p.key]}</span>
                  <span className="ml-auto pl-3 font-semibold">{hv ? p.format(hv.v) : "–"}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <p className="text-[11.5px] text-ink-muted">
        {hoverDay ? (
          <Link href={`/dashboard/body/?day=${hoverDay}`} className="font-semibold text-brand hover:underline">
            {tr.dashboard.dayLink(f.weekdayDay(hoverDay))} →
          </Link>
        ) : (
          w.method
        )}
      </p>
    </div>
  );
}
