"use client";

// One day and the night before it on a clock axis (minutes after midnight; the evening before is negative), as small
// multiples: one low panel per series (heart rate, stress, Body Battery, breathing, SpO2), all the same size and on
// the same x axis, the sleep shaded behind each and the sleep stages as one strip on top. No series is the hero.
//
// Why not LineChart, TimeChart or StreamChart: the first two put one point per day on the x axis; StreamChart is per
// activity (seconds since the start). Here x is the time of day, a line breaks where there is no reading (watch off,
// or a workout for stress and breathing), and the sleep is a band, not a series. The rules follow StreamChart and
// LineChart: no frame, y labels on the right, the measured width as viewBox, one dotted cursor through every panel,
// each panel's label row reading the value under the cursor; the arrow keys step through the night.

import { useLayoutEffect, useRef, useState } from "react";
import type { SleepStage } from "@/lib/training";

export type TimelinePanel = {
  key: string;
  label: string;
  colour: string;
  points: [number, number][];
  format: (v: number) => string;
  /** Fixed y range (stress and Body Battery are 0-100); otherwise the data's range with a little room. */
  domain?: [number, number];
  /** A dashed reference line, e.g. the normal resting heart rate. */
  reference?: number | null;
};

type Sleep = { start: number; end: number; stages: { start: number; end: number; stage: SleepStage }[] };

/** Stage colours: deep and light the same hue (light is fainter), REM and awake their own. */
export const STAGE_COLOUR: Record<SleepStage, { fill: string; opacity: number }> = {
  deep: { fill: "var(--chart-3)", opacity: 1 },
  light: { fill: "var(--chart-3)", opacity: 0.4 },
  rem: { fill: "var(--chart-5)", opacity: 1 },
  awake: { fill: "var(--chart-4)", opacity: 1 },
};

const RIGHT = 44; // gutter for the y labels
const PANEL_H = 64;
const STRIP = 8;
const GAP_MIN = 10; // more than this between two readings: no reading in between, the line breaks
const NEAR_MIN = 6; // the cursor reads a series only within this many minutes of a reading

/** 23:40 from a minute after midnight (negative: the evening before). */
export const clock = (minute: number) => {
  const m = ((Math.round(minute) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

function nearest(points: [number, number][], m: number): number | null {
  let lo = 0;
  let hi = points.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] < m) lo = mid + 1;
    else hi = mid;
  }
  const best = [lo - 1, lo].filter((i) => i >= 0 && i < points.length).sort((a, b) => Math.abs(points[a][0] - m) - Math.abs(points[b][0] - m))[0];
  return best != null && Math.abs(points[best][0] - m) <= NEAR_MIN ? points[best][1] : null;
}

export default function DayTimeline({
  from,
  to,
  panels,
  sleep,
  nextSleepStart,
  stageLabel,
  stagesTitle,
  ariaLabel,
  rangeLabel,
}: {
  from: number;
  to: number;
  panels: TimelinePanel[];
  sleep: Sleep | null;
  nextSleepStart: number | null;
  stageLabel: Record<SleepStage, string>;
  stagesTitle: string;
  ariaLabel: string;
  /** Label row without a cursor: the panel's range, "41–73". */
  rangeLabel: (lo: string, hi: string) => string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState<number | null>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setW(el.clientWidth || 720);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 720));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const shown = panels.filter((p) => p.points.length >= 2);
  if (shown.length === 0) return null;

  const plotW = Math.max(w - RIGHT, 10);
  const x = (m: number) => ((m - from) / (to - from)) * plotW;
  const every = plotW < 420 && to - from > 720 ? 360 : 180; // on the whole hour, every 3 h (6 on a phone)
  const hours: number[] = [];
  for (let m = Math.ceil(from / every) * every; m <= to; m += every) hours.push(m);
  const bands = [
    sleep && { start: Math.max(from, sleep.start), end: Math.min(to, sleep.end) },
    nextSleepStart != null && nextSleepStart < to && { start: nextSleepStart, end: to },
  ].filter((b): b is { start: number; end: number } => !!b && b.end > b.start);
  const stageAt = (m: number) => sleep?.stages.find((s) => s.start <= m && m < s.end)?.stage;

  function locate(clientX: number) {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return;
    setHover(Math.round(from + (Math.min(Math.max(clientX - rect.left, 0), plotW) / plotW) * (to - from)));
  }
  const hStage = hover != null ? stageAt(hover) : undefined;

  return (
    <div
      ref={box}
      className="relative flex select-none flex-col gap-2 outline-none"
      tabIndex={0}
      role="group"
      aria-label={ariaLabel}
      style={{ WebkitTouchCallout: "none", touchAction: "pan-y" }}
      onFocus={() => setHover((m) => m ?? (sleep ? sleep.end : to))}
      onBlur={() => setHover(null)}
      onKeyDown={(e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const step = (e.shiftKey ? 30 : 2) * (e.key === "ArrowRight" ? 1 : -1);
        setHover((m) => Math.min(to, Math.max(from, (m ?? to) + step)));
      }}
      onMouseMove={(e) => locate(e.clientX)}
      onMouseLeave={() => setHover(null)}
      onTouchStart={(e) => locate(e.touches[0].clientX)}
      onTouchMove={(e) => locate(e.touches[0].clientX)}
      // no onTouchEnd: after a tap the values stay readable; tapping elsewhere (blur) clears them
    >
      {sleep && (
        <div>
          <div className="flex items-baseline justify-between text-[11.5px] text-ink-muted">
            <span>{stagesTitle}</span>
            <span className="tabular-nums">{hStage ? stageLabel[hStage] : ""}</span>
          </div>
          <svg width={w} height={STRIP} className="block" aria-hidden>
            {sleep.stages
              .filter((s) => s.end > from && s.start < to)
              .map((s, i) => (
                <rect
                  key={i}
                  x={x(Math.max(from, s.start))}
                  width={Math.max(0.5, x(Math.min(to, s.end)) - x(Math.max(from, s.start)))}
                  y={0}
                  height={STRIP}
                  fill={STAGE_COLOUR[s.stage].fill}
                  opacity={STAGE_COLOUR[s.stage].opacity}
                />
              ))}
            {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={STRIP} stroke="var(--n-400)" strokeDasharray="2 2" />}
          </svg>
        </div>
      )}

      {shown.map((p) => {
        const values = p.points.map((q) => q[1]);
        if (p.reference != null) values.push(p.reference);
        let lo = Math.min(...values);
        let hi = Math.max(...values);
        if (p.domain) [lo, hi] = [Math.min(p.domain[0], lo), Math.max(p.domain[1], hi)];
        else [lo, hi] = [Math.floor(lo - (hi - lo) * 0.08 - 1), Math.ceil(hi + (hi - lo) * 0.08 + 1)];
        const top = 4;
        const ph = PANEL_H - top - 4;
        const y = (v: number) => top + (1 - (v - lo) / (hi - lo || 1)) * ph;
        let d = "";
        p.points.forEach(([m, v], i) => {
          const jump = i === 0 || m - p.points[i - 1][0] > GAP_MIN;
          d += `${jump ? "M" : "L"}${x(m).toFixed(1)} ${y(v).toFixed(1)}`;
        });
        const hv = hover != null ? nearest(p.points, hover) : null;
        const dataLo = Math.min(...p.points.map((q) => q[1]));
        const dataHi = Math.max(...p.points.map((q) => q[1]));
        return (
          <div key={p.key}>
            <div className="flex items-baseline justify-between text-[11.5px] text-ink-muted" style={{ width: plotW }}>
              <span className="flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-[3px] w-3 rounded-full" style={{ background: p.colour }} />
                {p.label}
              </span>
              <span className="tabular-nums">{hover != null ? (hv != null ? p.format(hv) : "–") : rangeLabel(p.format(dataLo), p.format(dataHi))}</span>
            </div>
            <svg width={w} height={PANEL_H} className="block overflow-visible" role="img" aria-label={p.label}>
              {bands.map((b, i) => (
                <rect key={i} x={x(b.start)} width={x(b.end) - x(b.start)} y={0} height={PANEL_H} fill="var(--chart-band)" />
              ))}
              <g className="ds-chart__grid">
                <line x1="0" x2={plotW} y1={y(hi)} y2={y(hi)} />
                <line x1="0" x2={plotW} y1={y(lo)} y2={y(lo)} />
              </g>
              <g className="ds-chart__axis">
                <text x={plotW + 6} y={y(hi) + 4}>{hi}</text>
                <text x={plotW + 6} y={y(lo)}>{lo}</text>
              </g>
              {p.reference != null && (
                <line x1="0" x2={plotW} y1={y(p.reference)} y2={y(p.reference)} stroke="var(--chart-2)" strokeWidth="1" strokeDasharray="4 4" opacity={0.7} />
              )}
              <path className="ds-chart__line" d={d} stroke={p.colour} strokeWidth={1.4} />
              {hover != null && <line className="ds-chart__cursor" x1={x(hover)} x2={x(hover)} y1={0} y2={PANEL_H} />}
              {hover != null && hv != null && <circle className="ds-chart__dot" cx={x(hover)} cy={y(hv)} r="3" fill={p.colour} />}
            </svg>
          </div>
        );
      })}

      <svg width={w} height={14} className="block" aria-hidden>
        <g className="ds-chart__axis">
          {hours.map((m) => (
            <text key={m} x={x(m)} y={11} textAnchor={x(m) < 16 ? "start" : x(m) > plotW - 16 ? "end" : "middle"}>
              {clock(m)}
            </text>
          ))}
        </g>
      </svg>
      {/* Every value at the cursor in one box beside it (left of the cursor in the right half), so you need not
          look at each panel's label row. */}
      {hover != null && (
        <div
          className="ds-chart__tip"
          aria-live="polite"
          style={{ left: x(hover) + (x(hover) > plotW / 2 ? -12 : 12), top: sleep ? STRIP + 26 : 22, transform: x(hover) > plotW / 2 ? "translateX(-100%)" : "none" }}
        >
          <div className="font-semibold">
            {clock(hover)}
            {hStage ? ` · ${stageLabel[hStage]}` : ""}
          </div>
          {shown.map((p) => {
            const hv = nearest(p.points, hover);
            return (
              <div key={p.key} className="flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-[3px] w-2.5 rounded-full" style={{ background: p.colour }} />
                <span className="opacity-80">{p.label}</span>
                <span className="ml-auto pl-3 font-semibold">{hv != null ? p.format(hv) : "–"}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
