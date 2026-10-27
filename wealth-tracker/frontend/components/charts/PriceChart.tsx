"use client";

// The price chart of one product, on the page of a position: what the share or
// tracker itself has done, regardless of how much of it you have.
//
// Why not ValueChart with other data? That draws two series with a legend that
// turns them on and off, and its axis scales to what is on — a price is one line,
// so that whole mechanism would stand empty. What the two *do* share (the round
// axis values) has lived in lib/chartScale.ts since this chart, and reading out
// works here the same as there, because they are used side by side on one phone:
//
//  1. One finger (or the mouse) puts a crosshair on the line and reports the
//     point under it through `onProbe`; two fingers — or dragging — measure the
//     stretch between them.
//  2. What is read out does not float over the drawing but is put by the card in
//     its own header: a tooltip in a 150px chart covers exactly the line you are
//     reading.
//  3. The y-labels sit on round numbers and the grid lines lie on them.
//  4. Over days, as on Net worth: dates at round moments along the bottom, and on a
//     desktop a drag you let go of zooms the page in on that stretch (`onSelect`).
//
// preserveAspectRatio="none" stretches the svg to the card; vector-effect keeps
// the line width honest in the process. The downside is that no <text> can sit
// in the svg — it would be distorted along — so every label is HTML next to or
// over the svg.

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { tickFractions } from "@/lib/date-ticks";
import type { ZoomWindow } from "@/components/charts/ZoomChip";
import { niceTicks, tickDecimals } from "@trackerai/ui/lib/chartScale";
import { type PricePoint, type PriceProbe, priceChange } from "@/lib/holdings";
import { fmtNumber } from "@/lib/format";
import { tr } from "@/lib/i18n";

const W = 620;
const H = 188;
const PATH_Y = 12;

export default function PriceChart({
  points,
  /**
   * The previous session's close, as a dotted line. What the day is measured
   *  against: without that line an intraday chart starts at the opening price and
   *  says nothing about gain or loss.
   */
  baseline = null,
  /** What is being pointed at right now, or null as soon as the finger is lifted. */
  onProbe,
  /** Labels under the axis; the card knows whether they are clock times or dates. */
  xLabel,
  decimals = 2,
  className = "h-[170px] sm:h-[208px]",
  dateAxis = false,
  onSelect,
  onReset,
}: {
  points: PricePoint[];
  baseline?: number | null;
  onProbe?: (probe: PriceProbe | null) => void;
  xLabel: (d: string) => string;
  /**
   * Decimals of the y-labels. A price of €4.12 needs more than the portfolio value,
   *  where the step size gives them by itself.
   */
  decimals?: number;
  className?: string;
  /** Daily points: dates at round moments instead of three labels. */
  dateAxis?: boolean;
  /** Drag across the chart and let go: that stretch becomes the period. */
  onSelect?: (window: ZoomWindow) => void;
  /** Double-click: back to the period from before the dragging. */
  onReset?: () => void;
}) {
  const clipId = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  // Two pointed points: [a, b] in the order in which they were touched.
  const [span, setSpan] = useState<[number, number] | null>(null);
  const dragFrom = useRef<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pw, setPw] = useState(600);
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    setPw(el.clientWidth || 600);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setPw(el.clientWidth || 600));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // A new period is a new series; a measurement from the previous one then points
  // to points that no longer exist.
  const length = points.length;
  useEffect(() => {
    setSpan(null);
    setHover(null);
  }, [length]);

  const model = useMemo(() => {
    if (points.length < 2) return null;
    const values = points.map((p) => p.c);
    if (baseline !== null) values.push(baseline);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    // With a flat line there is no spread to scale on; a fixed margin around the
    // value then keeps it neatly in the middle.
    const half = hi - lo > 0 ? (hi - lo) * 0.06 : Math.max(Math.abs(hi) * 0.001, 0.01);
    const min = lo - half;
    const max = hi + half;
    const y = (v: number) => PATH_Y + (1 - (v - min) / (max - min)) * (H - 2 * PATH_Y);
    return { y, ticks: niceTicks(min, max) };
  }, [points, baseline]);

  // Before the early return below: a hook after it would make the number of hooks change when the series
  // grows from one point to two, which React refuses.
  // An index from the previous render can fall outside the new series —
  // react-query refreshes the history while you point.
  const clamp = (i: number) => Math.min(Math.max(i, 0), points.length - 1);
  const hovered = hover !== null ? points[clamp(hover)] : null;

  // The measured stretch, always read from left to right: the difference should
  // point forward in time, even if you dragged from right to left.
  const measured =
    span === null
      ? null
      : (() => {
          const [from, to] = (span[0] <= span[1] ? span : [span[1], span[0]]).map(clamp);
          if (from === to) return null;
          return { from, to, a: points[from], b: points[to] };
        })();

  // Report upward in an effect and not during render: calling the parent's
  // setState while this component renders is the loop React cuts off.
  const probeKey = measured ? `${measured.from}-${measured.to}` : hovered ? hovered.d : "";
  useEffect(() => {
    if (!onProbe) return;
    if (measured) onProbe({ kind: "span", a: measured.a, b: measured.b, ...priceChange(measured.a, measured.b) });
    else if (hovered) onProbe({ kind: "point", point: hovered });
    else onProbe(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [probeKey, onProbe]);

  if (!model) return null;
  const { y, ticks } = model;
  // The round step decides how many decimals carry meaning, but never fewer than
  // the card asks for: with a step of 1 euro "128" on a price chart is a different
  // number from the €127.80 below it.
  const labelDecimals = Math.max(tickDecimals(ticks), decimals);

  const x = (i: number) => (i / (points.length - 1)) * W;
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(p.c).toFixed(1)}`).join(" ");

  const last = points[points.length - 1];
  const mid = points[Math.floor((points.length - 1) / 2)];
  const colour = "var(--chart-1)";

  function indexAt(clientX: number): number | null {
    const rect = wrap.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return null;
    const f = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
    return Math.round(f * (points.length - 1));
  }

  function measure(a: number | null, b: number | null) {
    if (a === null || b === null || a === b) return;
    setHover(null);
    setSpan([a, b]);
  }

  function clear() {
    dragFrom.current = null;
    setDragging(false);
    setSpan(null);
    setHover(null);
  }
  // Letting go of a drag: that stretch becomes the period.
  function release() {
    if (onSelect && dragging && span) {
      const [a, b] = [Math.min(...span), Math.max(...span)].map((i) => Math.min(Math.max(i, 0), points.length - 1));
      if (b > a) onSelect({ from: points[a].d.slice(0, 10), to: points[b].d.slice(0, 10) });
    }
    clear();
  }

  return (
    // select-none over the whole chart: to iOS, putting two fingers down to measure
    // cannot be told apart from two fingers to select text.
    <div className="select-none" style={{ WebkitTouchCallout: "none" }}>
      {/* pr-12 is the gutter for the y labels; they are HTML, because <text> in the svg would
          distort along with preserveAspectRatio="none". */}
      <div className="pr-12">
        <div
          ref={wrap}
          // Exactly as wide as the svg: indexAt() calculates the pointing position from
          // this width, so no padding may be added here.
          className="relative"
          // pan-y: dragging sideways measures, vertically the page simply scrolls on — the
          // chart takes up the full width of the card.
          style={{ touchAction: "pan-y", cursor: onSelect ? "crosshair" : undefined }}
          onMouseDown={(e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            dragFrom.current = indexAt(e.clientX);
            setDragging(true);
          }}
          onMouseMove={(e) => {
            if (dragFrom.current !== null) measure(dragFrom.current, indexAt(e.clientX));
            else setHover(indexAt(e.clientX));
          }}
          onMouseUp={release}
          onDoubleClick={onReset}
          onMouseLeave={clear}
          onTouchStart={(e) => {
            if (e.touches.length >= 2) measure(indexAt(e.touches[0].clientX), indexAt(e.touches[1].clientX));
            else setHover(indexAt(e.touches[0].clientX));
          }}
          onTouchMove={(e) => {
            if (e.touches.length >= 2) measure(indexAt(e.touches[0].clientX), indexAt(e.touches[1].clientX));
            else if (span === null) setHover(indexAt(e.touches[0].clientX));
          }}
          onTouchEnd={(e) => {
            if (e.touches.length === 0) clear();
            else if (e.touches.length < 2) setSpan(null);
          }}
        >
          <svg
            width="100%"
            className={className}
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={tr("Price history")}
          >
            <defs>
              <clipPath id={clipId}>
                <rect x="0" y="0" width={W} height={H} />
              </clipPath>
            </defs>

            {/* Rasterlijnen op de labels, niet op vaste hoogtes: anders wijzen
                de getallen naast de grafiek nergens naar. */}
            <g className="ds-chart__grid">
              {ticks.map((t) => (
                <line key={t} x1="0" y1={y(t)} x2={W} y2={y(t)} vectorEffect="non-scaling-stroke" />
              ))}
            </g>

            {baseline !== null && (
              <line
                x1="0"
                y1={y(baseline)}
                x2={W}
                y2={y(baseline)}
                stroke="var(--border-strong)"
                strokeWidth="1"
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
            )}

            {measured && (
              <rect
                x={x(measured.from)}
                y="0"
                width={Math.max(x(measured.to) - x(measured.from), 0.5)}
                height={H}
                fill="var(--chart-band)"
              />
            )}

            <g clipPath={`url(#${clipId})`}>
              <path className="ds-chart__area" d={`${path} L${W} ${H} L0 ${H} Z`} fill="var(--chart-band)" />
              <path
                d={path}
                fill="none"
                stroke={colour}
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            </g>

            {hover !== null && !measured && (
              <line
                x1={x(clamp(hover))}
                y1="0"
                x2={x(clamp(hover))}
                y2={H}
                className="ds-chart__cursor"
                vectorEffect="non-scaling-stroke"
              />
            )}

            {measured &&
              [measured.from, measured.to].map((i) => (
                <g key={i}>
                  <line x1={x(i)} y1="0" x2={x(i)} y2={H} stroke="var(--chart-1)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                  <circle
                    cx={x(i)}
                    cy={y(points[i].c)}
                    r="4"
                    fill={colour}
                    stroke="var(--surface-page)"
                    strokeWidth="2"
                    vectorEffect="non-scaling-stroke"
                  />
                </g>
              ))}

            {!measured && <circle cx={W} cy={y(last.c)} r="3.5" fill={colour} stroke="var(--surface-page)" strokeWidth="2" />}
          </svg>

          {/* The y labels in the gutter on the right. hi and lo lie PAD_Y inside the viewBox, so
              each label is at the height of its own tick. */}
          <div className="pointer-events-none absolute inset-y-0 -right-12 w-12 text-[11px] text-ink-muted">
            {ticks.map((t) => (
              <span key={t} className="num absolute left-1.5 -translate-y-1/2 whitespace-nowrap" style={{ top: `${(y(t) / H) * 100}%` }}>
                {fmtNumber(t, { decimals: labelDecimals })}
              </span>
            ))}
          </div>
        </div>

        {onSelect && dragging && span ? (
          <div className="mt-1 h-4 text-xs text-ink-muted">{tr("let go to show this period")}</div>
        ) : dateAxis ? (
          <div className="relative mt-1 h-4 text-xs text-ink-muted">
            {tickFractions(
              points.map((p) => p.d.slice(0, 10)),
              pw,
            ).map((t, i) => (
              <span
                key={i}
                className="absolute whitespace-nowrap"
                style={{ left: `${t.f * 100}%`, transform: t.f < 0.04 ? "none" : t.f > 0.96 ? "translateX(-100%)" : "translateX(-50%)" }}
              >
                {t.label}
              </span>
            ))}
          </div>
        ) : (
          <div className="mt-1 flex justify-between text-xs text-ink-muted">
            <span>{xLabel(points[0].d)}</span>
            <span>{xLabel(mid.d)}</span>
            <span>{xLabel(last.d)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
