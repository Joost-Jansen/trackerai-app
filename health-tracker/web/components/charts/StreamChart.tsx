"use client";

// Heart rate, pace and altitude during one activity, stacked on the same time axis. The heart rate sits
// on the zone colours as background bands, so you see which zone you were in without calculating.
// Pointing gives one cursor through all three panels, every value at the cursor in one box beside it (as TimeChart
// does), and reports the position (0..1) to the map. On a phone a tap keeps the box; tapping elsewhere clears it.

import { useLayoutEffect, useRef, useState } from "react";
import { useFormat, useT } from "@/lib/i18n";
import { effortKind } from "@/lib/sports";
import { fmtClock, ZONES } from "@/lib/training";

type Panel = {
  key: string;
  label: string;
  values: (number | null)[];
  colour: string;
  format: (v: number) => string;
  invert?: boolean; // pace: faster (smaller) is higher
  bands?: number[]; // zone bounds for the heart rate
  fill?: boolean;
  height: number;
};

const RIGHT = 52;

function smooth(values: (number | null)[], radius: number): (number | null)[] {
  if (radius < 1) return values;
  return values.map((v, i) => {
    if (v == null) return null;
    let sum = 0;
    let n = 0;
    for (let j = Math.max(0, i - radius); j <= Math.min(values.length - 1, i + radius); j++) {
      const x = values[j];
      if (x != null) {
        sum += x;
        n++;
      }
    }
    return n ? sum / n : null;
  });
}

function quantile(sorted: number[], q: number) {
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))))];
}

export default function StreamChart({
  time,
  heartrate,
  velocity,
  altitude,
  bounds,
  sport,
  onCursor,
}: {
  time: number[];
  heartrate?: (number | null)[];
  velocity?: (number | null)[];
  altitude?: (number | null)[];
  bounds?: number[] | null;
  sport: string;
  onCursor?: (fraction: number | null) => void;
}) {
  const t = useT();
  const f = useFormat();
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState<number | null>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setW(el.clientWidth || 720);
    const ro = new ResizeObserver(() => setW(el.clientWidth || 720));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = time.length;
  const panels: Panel[] = [];
  if (heartrate?.some((v) => v)) {
    panels.push({ key: "hr", label: t.charts.hr, values: smooth(heartrate.map((v) => v || null), 2), colour: "var(--n-800)", format: (v) => `${Math.round(v)}`, bands: bounds ?? undefined, height: 150 });
  }
  if (velocity?.some((v) => v)) {
    const kind = effortKind(sport);
    const moving = velocity.map((v) => (v && v > (kind === "speed" ? 1.5 : 1.2) ? v : null));
    if (kind === "speed") {
      panels.push({ key: "speed", label: t.charts.speed, values: smooth(moving.map((v) => (v == null ? null : v * 3.6)), 3), colour: "var(--chart-1)", format: (v) => `${f.num(v)} ${f.kmhUnit}`, height: 110 });
    } else if (kind === "pace") {
      panels.push({ key: "pace", label: t.charts.pace, values: smooth(moving.map((v) => (v == null ? null : 1000 / v)), 3), colour: "var(--chart-1)", format: (v) => fmtClock(v), invert: true, height: 110 });
    }
  }
  if (altitude?.some((v) => v != null) && sport !== "swim") {
    panels.push({ key: "alt", label: t.charts.altitude, values: altitude, colour: "var(--chart-3)", format: (v) => `${Math.round(v)} m`, fill: true, height: 70 });
  }
  if (n < 2 || panels.length === 0) return null;

  const plotW = Math.max(w - RIGHT, 10);
  const x = (i: number) => (i / (n - 1)) * plotW;

  function locate(clientX: number) {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return;
    const frac = Math.min(Math.max((clientX - rect.left) / plotW, 0), 1);
    const i = Math.round(frac * (n - 1));
    setHover(i);
    onCursor?.(i / (n - 1));
  }
  function leave() {
    setHover(null);
    onCursor?.(null);
  }

  return (
    <div
      ref={box}
      className="relative flex select-none flex-col gap-1"
      onMouseMove={(e) => locate(e.clientX)}
      onMouseLeave={leave}
      onTouchStart={(e) => locate(e.touches[0].clientX)}
      onTouchMove={(e) => locate(e.touches[0].clientX)}
      tabIndex={0}
      onBlur={leave}
    >
      {panels.map((p) => {
        const vals = p.values.filter((v): v is number => v != null).sort((a, b) => a - b);
        // 2%-98% so one GPS outlier does not flatten the scale
        let lo = quantile(vals, 0.02);
        let hi = quantile(vals, 0.98);
        if (p.bands) {
          lo = Math.min(lo, p.bands[0] - 5);
          hi = Math.max(hi, p.bands[1] + 5);
        }
        if (p.key === "alt") hi = Math.max(hi, lo + 10);
        const span = hi - lo || 1;
        const top = 6;
        const ph = p.height - top - 4;
        const y = (v: number) => {
          const c = Math.min(Math.max(v, lo), hi);
          const f = (c - lo) / span;
          return top + (p.invert ? f : 1 - f) * ph;
        };
        let d = "";
        p.values.forEach((v, i) => {
          if (v == null) return;
          const prev = i > 0 ? p.values[i - 1] : null;
          d += `${prev == null ? "M" : "L"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
        });
        const hv = hover != null ? p.values[hover] : null;
        const avg = vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
        return (
          <div key={p.key}>
            <div className="flex items-baseline justify-between text-[11.5px] text-ink-muted">
              <span>{p.label}</span>
              <span className="tabular-nums">{hv != null ? p.format(hv) : avg != null ? t.charts.avg(p.format(p.key === "pace" ? 1000 / (vals.reduce((s, v) => s + 1000 / v, 0) / vals.length) : avg)) : ""}</span>
            </div>
            <svg width={w} height={p.height} className="block overflow-visible" role="img" aria-label={p.label}>
              {p.bands &&
                [lo, ...p.bands, hi].slice(0, 6).map((b0, i, arr) => {
                  const b1 = i + 1 < arr.length ? arr[i + 1] : hi;
                  if (i >= ZONES.length || b1 <= lo || b0 >= hi) return null;
                  const yTop = y(Math.min(b1, hi));
                  const yBot = y(Math.max(b0, lo));
                  return <rect key={i} x={0} width={plotW} y={yTop} height={Math.max(0, yBot - yTop)} fill={`var(--zone-${i + 1})`} opacity={0.28} />;
                })}
              {p.fill && d && <path d={`${d} L${plotW} ${top + ph} L0 ${top + ph} Z`} fill={p.colour} opacity={0.18} />}
              <path d={d} fill="none" stroke={p.colour} strokeWidth={1.4} strokeLinejoin="round" />
              <g className="ds-chart__axis" fontSize={10.5} fill="var(--data-axis)">
                <text x={plotW + 6} y={top + 8}>{p.format(p.invert ? lo : hi)}</text>
                <text x={plotW + 6} y={top + ph}>{p.format(p.invert ? hi : lo)}</text>
              </g>
              {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={p.height} stroke="var(--border-strong)" strokeDasharray="2 3" />}
              {hover != null && hv != null && <circle cx={x(hover)} cy={y(hv)} r={3} fill={p.colour} />}
            </svg>
          </div>
        );
      })}
      {hover != null && (
        <div
          className="ds-chart__tip"
          aria-live="polite"
          style={{ left: x(hover) + (x(hover) > plotW / 2 ? -12 : 12), top: 22, transform: x(hover) > plotW / 2 ? "translateX(-100%)" : "none" }}
        >
          <div className="font-semibold">{fmtClock(time[hover] - time[0])}</div>
          {panels.map((p) => {
            const v = p.values[hover];
            // the heart rate's zone from the bounds the bands use
            const zone = p.bands && v != null ? ZONES[p.bands.filter((b) => v >= b).length] : null;
            return (
              <div key={p.key} className="flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-[3px] w-2.5 rounded-full" style={{ background: zone ? `var(--zone-${ZONES.indexOf(zone) + 1})` : p.colour }} />
                <span className="opacity-80">{p.label}</span>
                <span className="ml-auto pl-3 font-semibold">
                  {v != null ? p.format(v) : "–"}
                  {zone ? ` · ${zone}` : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}
      <div className="flex justify-between text-[10.5px] tabular-nums text-ink-muted" style={{ width: plotW }}>
        <span>0:00</span>
        <span>{hover != null ? fmtClock(time[hover] - time[0]) : ""}</span>
        <span>{fmtClock(time[n - 1] - time[0])}</span>
      </div>
    </div>
  );
}
