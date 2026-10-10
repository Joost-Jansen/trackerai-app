"use client";

// Several lines over time, with a shared time axis and a pointer line that shows
// all series on the same day at once.
//
// Meridian's chart rules, and why they are what they are:
//   · no frame and no y-axis line — the data is the hero, not the box around it;
//   · three dotted lines in --data-grid instead of five solid ones;
//   · the y-labels on the right, where your eye is anyway after reading the line;
//   · every series carries its name at the end of its own line, in its own
//     colour — that saves a legend block and you do not have to look anywhere to
//     know which line is which;
//   · area fill only with one series: two filled shapes fight;
//   · pointing gives a dotted cursor, one dot per series and one quiet readout.
//     No crosshair, no boxed tooltip.
//
// The series do not need to have the same days — a benchmark that starts later
// gets a shorter line instead of an extrapolated one. The x-axis is the union of
// all dates, and per series only what has a point is drawn.
//
// The viewBox is deliberately *not* stretched (no preserveAspectRatio="none"):
// the width is measured and the viewBox follows it, so <text> may sit in the svg
// without being distorted. That is exactly what makes the name labels at the end
// of each line possible.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { niceTicks } from "../lib/chartScale";
import { dayMonth } from "../lib/dates";
import { tickFractions } from "../lib/dateTicks";
import { trueMinus } from "../lib/typography";
import { useTr, useUiLocale } from "../i18n";

export type LinePoint = { d: string; v: number };

export type LineSeries = {
  label: string;
  points: LinePoint[];
  colour: string;
  dash?: "solid" | "dashed" | "dotted";
  width?: number;
  /** Area fill under the line. Only meaningful with one series. */
  fill?: boolean;
};

/** A stretch of the x-axis, as the first and last date in it. */
export type ZoomWindow = { from: string; to: string };

/** A goal line across the chart: dashed in its own colour, with a short label on the left. */
export type Reference = { value: number; colour: string; label: string; dash?: string };
const NO_REFS: Reference[] = [];

// On the right a gutter for the y-labels, at the bottom a row for the dates.
const PAD = { top: 14, right: 52, bottom: 20 };

const DASH: Record<string, string | undefined> = {
  solid: undefined,
  dashed: "4 4",
  dotted: "1 4",
};

export default function LineChart({
  series,
  baseline,
  references = NO_REFS,
  format,
  height = 220,
  endLabels = true,
  gridLines = 3,
  ariaLabel,
  className = "",
  xFormat,
  dateAxis = false,
  onSelect,
}: {
  series: LineSeries[];
  /** Dotted line at this value, for example 100 (index) or 0 (%). */
  baseline?: number;
  /** Goal lines, dashed in their own colour, with a short label at the left (none when empty): always in view. */
  references?: Reference[];
  format: (v: number) => string;
  height?: number;
  /** Names at the end of each line instead of a legend. */
  endLabels?: boolean;
  gridLines?: number;
  ariaLabel: string;
  className?: string;
  /**
   * How a date shows on the axis and in the readout; "1 Sep" by default. Per year
   *  or across a year boundary the year belongs with it.
   */
  xFormat?: (d: string) => string;
  /** Dates at round moments along the bottom (as on Net worth) instead of three. */
  dateAxis?: boolean;
  /** Drag across the chart and let go: that stretch becomes the period. */
  onSelect?: (window: ZoomWindow) => void;
}) {
  const tr = useTr();
  const locale = useUiLocale();
  const showDate = xFormat ?? ((d: string) => dayMonth(locale, d));
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState<number | null>(null);
  // Drag to select: the index where the mouse went down, while it is held.
  const [dragFrom, setDragFrom] = useState<number | null>(null);

  // useLayoutEffect: the first measurement must happen before the first paint,
  // otherwise the chart draws one frame at the default width and then jumps.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setW(el.clientWidth || 720);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 720));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const model = useMemo(() => {
    const dates = [...new Set(series.flatMap((s) => s.points.map((p) => p.d)))].sort();
    if (dates.length < 2) return null;

    const index = new Map(dates.map((d, i) => [d, i]));
    const values = series.flatMap((s) => s.points.map((p) => p.v));
    if (baseline !== undefined) values.push(baseline);
    references.forEach((r) => values.push(r.value));
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    return { dates, index, lo, hi };
  }, [series, baseline, references]);

  // Area fill only when there is one line — Meridian's rule, enforced here instead
  // of remembered again at every caller.
  const single = series.length === 1;

  useEffect(() => {
    if (hover !== null && (!model || hover > model.dates.length - 1)) setHover(null);
  }, [hover, model]);

  if (!model) return null;
  const { dates, index, lo, hi } = model;

  const plotW = Math.max(w - PAD.right, 10);
  const plotH = Math.max(height - PAD.top - PAD.bottom, 10);
  const span = hi - lo || 1;
  const x = (i: number) => (i / (dates.length - 1)) * plotW;
  const y = (v: number) => PAD.top + (1 - (v - lo) / span) * plotH;

  // Round values (0, 25, 50 …) instead of equal parts of the range, which showed up on the axis as 21 and −9.
  const nice = niceTicks(lo, hi, gridLines);
  const ticks = nice.length ? nice : Array.from({ length: gridLines }, (_, i) => lo + (span * (i + 1)) / (gridLines + 1));

  function indexAt(clientX: number): number | null {
    const rect = box.current?.getBoundingClientRect();
    if (!rect || plotW === 0) return null;
    const frac = Math.min(Math.max((clientX - rect.left) / plotW, 0), 1);
    return Math.round(frac * (dates.length - 1));
  }
  function locate(clientX: number) {
    const i = indexAt(clientX);
    if (i !== null) setHover(i);
  }
  const dragging = dragFrom !== null && hover !== null && hover !== dragFrom;

  // The name labels at the end of each line, pushed apart where they would land on
  // top of each other. With four indexes ending at almost the same height — exactly
  // what a comparison is about — they otherwise stack into one unreadable blot.
  // Walk from top to bottom and put every label at least LABEL_GAP below the
  // previous one.
  const LABEL_GAP = 13;
  const endLabelRows = series
    .filter((s) => s.points.length >= 2)
    .map((s, si) => {
      const lastPoint = s.points[s.points.length - 1];
      return {
        label: s.label,
        colour: s.colour ?? `var(--chart-${(si % 6) + 1})`,
        x: x(index.get(lastPoint.d)!),
        y: y(lastPoint.v) - 10,
      };
    })
    .sort((a, b) => a.y - b.y)
    // Een reduce en geen map: elk label moet onder het *aangepaste* label ervoor
    // komen, niet onder waar dat oorspronkelijk stond — anders schuift bij drie
    // botsingen alleen de tweede op en liggen de derde en vierde er weer bovenop.
    .reduce<{ label: string; colour: string; x: number; y: number }[]>((acc, r) => {
      const floor = acc.length === 0 ? 10 : acc[acc.length - 1].y + LABEL_GAP;
      acc.push({ ...r, y: Math.max(r.y, floor) });
      return acc;
    }, []);

  const hoveredDate = hover !== null ? dates[hover] : null;
  // What each series stood at on the pointed day. A series without a point on that
  // day (not started yet, or a market holiday) drops out instead of being set to
  // zero.
  const readings =
    hoveredDate === null
      ? []
      : series
          .map((s) => ({ s, point: s.points.find((p) => p.d === hoveredDate) }))
          .filter((r): r is { s: LineSeries; point: LinePoint } => r.point !== undefined);

  return (
    // To iOS, pointing with a finger cannot be told apart from wanting to select
    // text. Only the chart itself, nothing around it.
    <div
      ref={box}
      className={`ds-chart select-none ${className}`}
      tabIndex={0}
      role="group"
      aria-label={tr("{0}. Use the arrow keys to read the values per date.", ariaLabel)}
      style={{ height, WebkitTouchCallout: "none", touchAction: "pan-y", cursor: onSelect ? "crosshair" : undefined }}
      onFocus={() => setHover((i) => i ?? dates.length - 1)}
      onBlur={() => setHover(null)}
      onKeyDown={(e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        setHover((i) => Math.min(dates.length - 1, Math.max(0, (i ?? dates.length - 1) + (e.key === "ArrowRight" ? 1 : -1))));
      }}
      onMouseMove={(e) => locate(e.clientX)}
      onMouseLeave={() => { setHover(null); setDragFrom(null); }}
      onMouseDown={(e) => {
        if (!onSelect || e.button !== 0) return;
        e.preventDefault();
        setDragFrom(indexAt(e.clientX));
      }}
      onMouseUp={(e) => {
        if (dragFrom === null || !onSelect) return;
        const to = indexAt(e.clientX);
        setDragFrom(null);
        if (to === null || to === dragFrom) return;
        const [a, b] = dragFrom < to ? [dragFrom, to] : [to, dragFrom];
        onSelect({ from: dates[a], to: dates[b] });
      }}
      onTouchStart={(e) => locate(e.touches[0].clientX)}
      onTouchMove={(e) => locate(e.touches[0].clientX)}
      onTouchEnd={() => setHover(null)}
    >
      <svg height={height} viewBox={`0 0 ${w} ${height}`} role="img" aria-label={ariaLabel}>
        <g className="ds-chart__grid">
          {ticks.map((t, i) => (
            <line key={i} x1="0" x2={plotW} y1={y(t)} y2={y(t)} />
          ))}
        </g>

        <g className="ds-chart__axis">
          {ticks.map((t, i) => (
            <text key={i} x={plotW + 8} y={y(t) + 3.5}>
              {trueMinus(format(t))}
            </text>
          ))}
          {dateAxis
            ? tickFractions(dates, plotW, locale).map((t, i) => (
              <text key={i} x={t.f * plotW} y={height - 3}
                textAnchor={t.f < 0.04 ? "start" : t.f > 0.96 ? "end" : "middle"}>
                {t.label}
              </text>
            ))
            : [...new Set([0, Math.floor((dates.length - 1) / 2), dates.length - 1])].map((i) => (
            <text
              key={i}
              x={x(i)}
              y={height - 3}
              textAnchor={i === 0 ? "start" : i === dates.length - 1 ? "end" : "middle"}
            >
              {showDate(dates[i])}
            </text>
          ))}
        </g>

        {baseline !== undefined && baseline >= lo && baseline <= hi && (
          <line
            x1="0"
            x2={plotW}
            y1={y(baseline)}
            y2={y(baseline)}
            stroke="var(--border-strong)"
            strokeWidth="1"
            strokeDasharray="2 3"
          />
        )}

        {references.map((r) => (
          <line key={r.label || r.value} x1="0" x2={plotW} y1={y(r.value)} y2={y(r.value)} stroke={r.colour} strokeWidth="1.5" strokeDasharray={r.dash ?? "6 4"} />
        ))}

        {series.map((s, si) => {
          if (s.points.length < 2) return null;
          const d = s.points
            .map(
              (p, i) => `${i === 0 ? "M" : "L"}${x(index.get(p.d)!).toFixed(2)} ${y(p.v).toFixed(2)}`
            )
            .join(" ");
          const first = index.get(s.points[0].d)!;
          const last = index.get(s.points[s.points.length - 1].d)!;
          return (
            <g key={s.label}>
              {s.fill && single && (
                <path
                  className="ds-chart__area"
                  d={`${d} L${x(last).toFixed(2)} ${PAD.top + plotH} L${x(first).toFixed(2)} ${PAD.top + plotH} Z`}
                  fill="var(--chart-band)"
                />
              )}
              <path
                className="ds-chart__line"
                d={d}
                stroke={s.colour ?? `var(--chart-${(si % 6) + 1})`}
                strokeWidth={s.width ?? 1.75}
                strokeDasharray={DASH[s.dash ?? "solid"]}
              />
            </g>
          );
        })}

        {endLabels && (
          <g>
            {endLabelRows.map((r) => (
              <text
                key={r.label}
                x={r.x - 4}
                y={r.y}
                textAnchor="end"
                fill={r.colour}
                style={{
                  fontFamily: "var(--font-sans)",
                  fontSize: 11.5,
                  fontWeight: 500,
                  letterSpacing: "0.01em",
                }}
              >
                {r.label}
              </text>
            ))}
          </g>
        )}

        {/* The stretch being dragged over. */}
        {dragging && (
          <rect x={Math.min(x(dragFrom!), x(hover!))} width={Math.abs(x(hover!) - x(dragFrom!))}
            y={PAD.top} height={plotH} fill="var(--chart-1)" fillOpacity={0.12} stroke="var(--chart-1)" strokeOpacity={0.5} />
        )}

        {hover !== null && (
          <g>
            <line className="ds-chart__cursor" x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} />
            {readings.map(({ s, point }, si) => (
              <circle
                key={s.label}
                className="ds-chart__dot"
                cx={x(hover)}
                cy={y(point.v)}
                r="3.5"
                fill={s.colour ?? `var(--chart-${(si % 6) + 1})`}
              />
            ))}
          </g>
        )}
        {/* goal labels last, with a halo in the card's colour, so no line runs through them */}
        {references.map((r) =>
          r.label ? (
            <text key={r.label} x="4" y={y(r.value) - 5} fontSize="11" fontWeight="600" fill={r.colour} stroke="var(--surface-card)" strokeWidth="4" paintOrder="stroke" strokeLinejoin="round">
              {r.label}
            </text>
          ) : null,
        )}
      </svg>

      {readings.length > 0 && hoveredDate && hover !== null && (
        <div
          className="ds-chart__tip"
          aria-live="polite"
          // Kept within the chart: against the edge the readout would hang half outside it.
          style={{
            left: Math.min(Math.max(x(hover), 60), plotW - 60),
            top: Math.max(y(readings[0].point.v) - 10, 22),
          }}
        >
          <div style={{ color: "var(--text-on-ink-muted)" }}>
            {dragging ? `${showDate(dates[Math.min(dragFrom!, hover)])} – ${showDate(dates[Math.max(dragFrom!, hover)])}` : showDate(hoveredDate)}
          </div>
          {dragging && <div>{tr("let go to show this period")}</div>}
          {!dragging && readings.map(({ s, point }) => (
            <div key={s.label}>
              {series.length > 1 ? `${s.label} · ` : ""}
              {trueMinus(format(point.v))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
