"use client";

// The admin page's charts (Admin.tsx): one small SVG chart per question, by week, hand-written like the rest of the
// codebase. Columns (stacked when there is more than one series) or a line. Hover or arrow keys show the week's values.

import { useEffect, useRef, useState } from "react";
import type { Locale } from "./brands";

export type Series = { id: string; label: string; color: string; values: number[] };

const H = 150;
const M = { top: 14, right: 14, bottom: 22, left: 34 };
const DAY = 86_400_000;

/** The Mondays (UTC, YYYY-MM-DD) of the last n ISO weeks including this one, oldest first. */
export function lastWeeks(n: number, now = new Date()): string[] {
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const monday = d.getTime() - ((d.getUTCDay() + 6) % 7) * DAY;
  return Array.from({ length: n }, (_, i) => new Date(monday - (n - 1 - i) * 7 * DAY).toISOString().slice(0, 10));
}

/** The index of the week (from lastWeeks) an ISO time falls in, or -1 outside them. */
export function weekIndex(weeks: string[], iso: string | null): number {
  if (!iso) return -1;
  const t = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
  const start = Date.parse(`${weeks[0]}T00:00:00Z`);
  const i = Math.floor((t - start) / (7 * DAY));
  return i >= 0 && i < weeks.length ? i : -1;
}

function niceStep(max: number): number {
  const raw = Math.max(max, 1) / 3;
  const pow = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 5, 10]) if (m * pow >= raw) return Math.max(1, m * pow);
  return 10 * pow;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function topRounded(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, h, w / 2);
  const b = y + h;
  return `M${x},${b}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${b}Z`;
}

export function WeekChart({ title, icon, weeks, series, kind, locale, extra, empty }: {
  title: string; icon?: React.ReactNode; weeks: string[]; series: Series[]; kind: "bars" | "line"; locale: Locale;
  /** One more line in the tooltip for week i. */
  extra?: (i: number) => string | null;
  /** Shown instead of the chart when every value is 0. */
  empty?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const fmtWeek = (w: string) =>
    new Date(`${w}T00:00:00Z`).toLocaleDateString(locale === "nl" ? "nl-NL" : "en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  const num = (n: number) => n.toLocaleString(locale === "nl" ? "nl-NL" : "en-GB");

  const n = weeks.length;
  const totals = weeks.map((_, i) => series.reduce((s, x) => s + (x.values[i] ?? 0), 0));
  const maxV = kind === "line" ? Math.max(0, ...series.flatMap((s) => s.values)) : Math.max(0, ...totals);
  const step = niceStep(maxV);
  const top = Math.max(step, Math.ceil(maxV / step) * step);
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
  // Reserve the same gutter for every chart, including the line's end labels.
  const right = M.right + 26;
  const pw = Math.max(0, width - M.left - right);
  const ph = H - M.top - M.bottom;
  const band = n ? pw / n : 0;
  const cx = (i: number) => M.left + band * (i + 0.5);
  const y = (v: number) => M.top + ph - (v / top) * ph;
  const bw = Math.min(24, band * 0.62);
  const nothing = maxV === 0 && !!empty;

  // The lines' end labels, at least 12px apart so two lines that end close together stay readable.
  const endLabels = (() => {
    const order = series.map((s, k) => ({ k, at: y(s.values[n - 1] ?? 0) })).sort((a, b) => a.at - b.at);
    for (let i = 1; i < order.length; i++) order[i].at = Math.max(order[i].at, order[i - 1].at + 12);
    const overflow = Math.max(0, (order.at(-1)?.at ?? 0) - (M.top + ph));
    for (const o of order) o.at -= overflow;
    const out: number[] = [];
    for (const o of order) out[o.k] = o.at;
    return out;
  })();

  const tipLeft = hover === null ? 0 : Math.min(Math.max(cx(hover), 70), Math.max(70, width - 70));

  return (
    <figure className="mk-ad-chart">
      <figcaption className="mk-ad-chart-title">{icon}{title}</figcaption>
      {/* Keep a legend row even for one series so neighbouring plots start at the same height. */}
      <div className="mk-ad-legend">
        {series.length > 1 && series.map((s) => <span key={s.id}><i style={{ background: s.color }} />{s.label}</span>)}
      </div>
      <div ref={ref} className="mk-ad-chart-plot">
        {nothing ? <p className="mk-ad-muted mk-ad-chart-empty">{empty}</p> : width > 0 && (
          <svg width="100%" height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label={title} tabIndex={0}
            onPointerLeave={() => setHover(null)} onBlur={() => setHover(null)} onFocus={() => setHover(n - 1)}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") { e.preventDefault(); setHover((h) => Math.max(0, (h ?? n) - 1)); }
              if (e.key === "ArrowRight") { e.preventDefault(); setHover((h) => Math.min(n - 1, (h ?? -1) + 1)); }
            }}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={width - right} y1={y(t)} y2={y(t)} className={t === 0 ? "mk-ad-axis" : "mk-ad-grid"} />
                <text x={M.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="mk-ad-tick">{num(t)}</text>
              </g>
            ))}
            {[0, Math.floor((n - 1) / 2), n - 1].filter((i, k, a) => n > 0 && a.indexOf(i) === k).map((i) => (
              <text key={i} x={cx(i)} y={H - 6} textAnchor="middle" className="mk-ad-tick">{fmtWeek(weeks[i])}</text>
            ))}
            {hover !== null && <rect x={cx(hover) - band / 2} y={M.top} width={band} height={ph} className="mk-ad-hoverband" />}

            {kind === "bars" && weeks.map((_, i) => {
              let base = 0;
              const parts = series.map((s) => ({ s, v: s.values[i] ?? 0 })).filter((p) => p.v > 0);
              return parts.map(({ s, v }, k) => {
                const y0 = y(base);
                base += v;
                const isTop = k === parts.length - 1;
                // A 2px gap in the surface colour between stacked segments.
                const y1 = y(base) + (isTop ? 0 : 2);
                const h = Math.max(0, y0 - y1);
                if (h <= 0) return null;
                return isTop
                  ? <path key={s.id} d={topRounded(cx(i) - bw / 2, y1, bw, h, 4)} fill={s.color} />
                  : <rect key={s.id} x={cx(i) - bw / 2} y={y1} width={bw} height={h} fill={s.color} />;
              });
            })}

            {kind === "line" && series.map((s, k) => {
              const pts = s.values.map((v, i) => `${cx(i)},${y(v)}`);
              const last = s.values[n - 1] ?? 0;
              const labelY = endLabels[k];
              return (
                <g key={s.id}>
                  <path d={`M${cx(0)},${y(0)}L${pts.join("L")}L${cx(n - 1)},${y(0)}Z`} fill={s.color} fillOpacity={0.1} />
                  <path d={`M${pts.join("L")}`} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                  <circle cx={cx(n - 1)} cy={y(last)} r={4} fill={s.color} className="mk-ad-dot" />
                  <text x={cx(n - 1) + 9} y={labelY} dy="0.32em" className="mk-ad-endlabel">{num(last)}</text>
                  {hover !== null && hover !== n - 1 && <circle cx={cx(hover)} cy={y(s.values[hover] ?? 0)} r={4} fill={s.color} className="mk-ad-dot" />}
                </g>
              );
            })}

            {weeks.map((_, i) => (
              <rect key={i} x={cx(i) - band / 2} y={0} width={band} height={H} fill="transparent" onPointerEnter={() => setHover(i)} />
            ))}
          </svg>
        )}
        {hover !== null && !nothing && (
          <div className="mk-ad-tip" style={{ left: tipLeft }}>
            <span className="mk-ad-muted">{fmtWeek(weeks[hover])}</span>
            {series.map((s) => (
              <span key={s.id} className="mk-ad-tip-row">
                <i style={{ background: s.color }} /><b>{num(s.values[hover] ?? 0)}</b><span className="mk-ad-muted">{s.label}</span>
              </span>
            ))}
            {extra?.(hover) && <span className="mk-ad-muted">{extra(hover)}</span>}
          </div>
        )}
      </div>
      <table className="mk-ad-sr">
        <caption>{title}</caption>
        <thead><tr><th scope="col" />{series.map((s) => <th key={s.id} scope="col">{s.label}</th>)}</tr></thead>
        <tbody>
          {weeks.map((w, i) => (
            <tr key={w}><th scope="row">{fmtWeek(w)}</th>{series.map((s) => <td key={s.id}>{s.values[i] ?? 0}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
