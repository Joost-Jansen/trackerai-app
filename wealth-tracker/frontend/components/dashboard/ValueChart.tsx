"use client";

// The portfolio-value card's chart: your own portfolio in euros over the
// selected range — Value (brand, area fill, emphasized endpoint) and Invested
// (dashed, muted).
//
// There used to be a third line, value + cumulative dividends. It was correct —
// prices drop on the ex-date, so Waarde alone understates what the portfolio
// earned — but on this card it was a slowly widening gap between two nearly
// parallel lines, and it invited a wrong reading: a reinvested dividend is an
// ordinary BUY in the DeGiro export, so it also raises Invested. Dividends stay
// in the return arithmetic (rangeBreakdown reads value_divs) and get their own
// chart later; the line is gone.
//
// Three things it does that a plain line chart does not:
//
//  1. The y-axis fits *the lines that are switched on*, not both. Invested sits
//     a whole return below Waarde, so letting it set the floor spent the entire
//     height on the gap and flattened a day's movement into a straight line. On
//     1D and 1W only Waarde is on by default; the legend below the chart toggles
//     Invested back (and toggling is remembered until the period changes).
//  2. There are y-labels, at round numbers, and the gridlines sit on them.
//  3. Two fingers on a phone — or a drag on a desktop — measure the difference
//     between two points, like the Aandelen app. On a desktop, letting go of the
//     drag zooms the page in on that stretch (`onSelect`), as on Net worth.
//  4. Dates along the bottom at round moments (lib/date-ticks.ts).
//
// What it reads out does not float over the drawing. In a card this short a
// tooltip covers the very line it describes, so the chart reports what is under
// the finger through `onProbe` and the card's header renders it in the space it
// already occupies.
//
// preserveAspectRatio="none" stretches the svg to the card; vector-effect keeps
// stroke widths honest while it does. The flip side is that no <text> can live
// in the svg: it would be stretched with it. Every label is HTML positioned
// over or beside the svg.

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { tickFractions } from "@/lib/date-ticks";
import type { ZoomWindow } from "@/components/charts/ZoomChip";
import { niceTicks, tickDecimals } from "@trackerai/ui/lib/chartScale";
import { type Probe, type Range, type ValuePoint, splitChange } from "@/lib/dashboard";
import { fmtDayMonth, fmtDayMonthYear, fmtIntradayLabel, fmtNumber } from "@/lib/format";
import { tr } from "@/lib/i18n";

const W = 620;
const H = 188;
const PATH_Y = 12;

type Key = "value" | "invested";

const SERIES: {
  key: Key;
  label: string;
  colour: string;
  dash?: string;
  width: number;
}[] = [
  // Meridian's order of importance: series 1 (terracotta) is always the user's own
  // data, series 2 (walnut black, dashed) is always what you measure it against.
  { key: "value", label: tr("Value"), colour: "var(--chart-1)", width: 1.75 },
  { key: "invested", label: tr("Deposited"), colour: "var(--chart-2)", dash: "4 4", width: 1.5 },
];

/**
 * On these periods Invested is off by default: over a day or a week the distance
 *  to Value is the only thing you would still see of it.
 */
const SHORT_RANGES: Range[] = ["1D", "1W"];

export default function ValueChart({
  points,
  range,
  intraday = false,
  baseline = null,
  onProbe,
  onSelect,
  className = "h-[150px] sm:h-[188px]",
}: {
  points: ValuePoint[];
  /** Only decides which lines are on by default (see SHORT_RANGES). */
  range: Range;
  /**
   * The points are today's 5-minute bars: then the labels are clock times and not
   *  dates.
   */
  intraday?: boolean;
  /**
   * Value at the previous close, as a dotted line. What the day is measured
   *  against — without that line an intraday chart says nothing about gain or
   *  loss, because it starts at the opening price.
   */
  baseline?: number | null;
  /**
   * What is being pointed at right now, or null as soon as the finger is lifted.
   *  The card puts this in its own header; drawing it over the line here would
   *  cover the line you are reading.
   */
  onProbe?: (probe: Probe | null) => void;
  /** Drag across the chart and let go: that stretch becomes the period. Not on intraday bars. */
  onSelect?: (window: ZoomWindow) => void;
  /** Height utilities for the svg. Shorter on a phone by default: at 188px in a
   *  ~310px-wide card the 620x188 viewBox is stretched to twice its intended
   *  vertical scale, which turns an ordinary month into a cliff. */
  className?: string;
}) {
  const clipId = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  // Two pointed points: [a, b] in the order in which they were touched.
  const [span, setSpan] = useState<[number, number] | null>(null);
  const dragFrom = useRef<number | null>(null);
  const [dragging, setDragging] = useState(false);
  // The real width, for how many dates fit along the bottom.
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

  // Turning a line on/off by hand overrules the period's default; switching
  // period resets that, otherwise a line you turned off on 1D would also stay away
  // on All without you remembering why.
  const [override, setOverride] = useState<Partial<Record<Key, boolean>>>({});
  useEffect(() => {
    setOverride({});
    setSpan(null);
  }, [range]);

  const shown = useMemo<Record<Key, boolean>>(() => {
    return { value: true, invested: !SHORT_RANGES.includes(range), ...override };
  }, [range, override]);

  const visible = SERIES.filter((s) => shown[s.key]);

  const model = useMemo(() => {
    if (points.length < 2) return null;
    const keys = SERIES.filter((s) => shown[s.key]).map((s) => s.key);
    const values = points.flatMap((p) => keys.map((k) => p[k]));
    // The previous close line should fall within view, otherwise the day measures
    // itself against something you cannot see.
    if (baseline !== null) values.push(baseline);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    // With a flat line there is no spread to scale on; a fixed margin around the
    // value then keeps it neatly in the middle.
    const half = hi - lo > 0 ? (hi - lo) * 0.06 : Math.max(Math.abs(hi) * 0.001, 0.01);
    const min = lo - half;
    const max = hi + half;
    const y = (v: number) => PATH_Y + (1 - (v - min) / (max - min)) * (H - 2 * PATH_Y);
    return { min, max, y, ticks: niceTicks(min, max) };
  }, [points, shown, baseline]);

  // Before the early return below: a hook after it would make the number of hooks change when the series
  // grows from one point to two, which React refuses.
  // An index from the previous render can fall outside the new series — react-query
  // refreshes the history while you point. Without the clamp that reads `undefined`.
  const clamp = (i: number) => Math.min(Math.max(i, 0), points.length - 1);

  const hovered = hover !== null ? points[clamp(hover)] : null;

  // The measured stretch, always read from left to right: the difference should
  // point forward in time, even if you dragged from right to left.
  //
  // The breakdown itself is in splitChange (lib/dashboard.ts), so the arithmetic
  // can be checked separately from the drawing.
  const measured =
    span === null
      ? null
      : (() => {
          const [from, to] = (span[0] <= span[1] ? span : [span[1], span[0]]).map(clamp);
          if (from === to) return null;
          const a = points[from];
          const b = points[to];
          return { from, to, a, b, ...splitChange(a, b) };
        })();

  // Report upward in an effect and not during render: calling the parent's
  // setState while this component renders is exactly the loop React cuts off. The
  // separate fields as deps, because `measured` is a new object on every render
  // and would make the effect fire endlessly.
  const probeKey = measured ? `${measured.from}-${measured.to}` : hovered ? hovered.d : "";
  useEffect(() => {
    if (!onProbe) return;
    if (measured) onProbe({ kind: "span", a: measured.a, b: measured.b, ...splitChange(measured.a, measured.b) });
    else if (hovered) onProbe({ kind: "point", point: hovered });
    else onProbe(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [probeKey, onProbe]);

  if (!model) return null;
  const { y, ticks } = model;
  const decimals = tickDecimals(ticks);

  const x = (i: number) => (i / (points.length - 1)) * W;

  // On one day "30 Jul" says the same thing three times; over a series of days a
  // clock time says nothing. The card header labels its readout itself, through
  // `intraday`, so this only stays for the axis at the bottom.
  //
  // Over more than a year the year belongs with it. Without it an axis of five
  // years reads as "5 Jan — 20 Oct — 7 Aug", where nothing gives away that there
  // are four years between the first two. Measured on the series and not on the
  // button: "All" is three months for one person and ten years for another.
  const spansYears =
    !intraday && new Date(points[points.length - 1].d).getTime() - new Date(points[0].d).getTime() > 400 * 24 * 3600 * 1000;
  const xLabel = intraday ? (d: string) => fmtIntradayLabel(d, points[points.length - 1].d) : spansYears ? fmtDayMonthYear : fmtDayMonth;

  const path = (key: Key) => points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(" ");

  const last = points[points.length - 1];
  const mid = points[Math.floor((points.length - 1) / 2)];

  // The name of each line at the end of that line, in its own colour — the same
  // rule as LineChart on the Returns tab. It used to be only in the legend below
  // the chart, so you had to look down from the line and remember two colours to
  // know which of the two you were reading.
  //
  // As HTML and not as <text>: preserveAspectRatio="none" stretches the svg to the
  // card width, and text would be distorted along. The y's therefore stay in
  // viewBox units and only become a percentage when placed.
  const LABEL_GAP = 15;
  const endLabels = visible
    .map((s) => ({ key: s.key, label: s.label, colour: s.colour, y: y(last[s.key]) - 9 }))
    .sort((a, b) => a.y - b.y)
    // Een reduce en geen map: het tweede label moet onder het *verschoven*
    // eerste komen. Waarde en Ingelegd liggen bij een jonge portefeuille vlak op
    // elkaar, en dan stapelen twee namen tot één onleesbare vlek.
    .reduce<{ key: Key; label: string; colour: string; y: number }[]>((acc, r) => {
      const floor = acc.length === 0 ? 9 : acc[acc.length - 1].y + LABEL_GAP;
      acc.push({ ...r, y: Math.min(Math.max(r.y, floor), H - 4) });
      return acc;
    }, []);

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
  const zooms = !!onSelect && !intraday;
  // Letting go of a drag: that stretch becomes the period.
  function release() {
    if (zooms && dragging && span) {
      const [a, b] = [Math.min(...span), Math.max(...span)].map((i) => Math.min(Math.max(i, 0), points.length - 1));
      if (b > a) onSelect!({ from: points[a].d.slice(0, 10), to: points[b].d.slice(0, 10) });
    }
    clear();
  }

  return (
    // select-none over the whole chart, and no wider: to iOS, putting two fingers
    // down to measure cannot be told apart from putting two fingers down to select
    // text, so the card lit up with a selection over it. The callout (the copy menu
    // after a long press) belongs to the same event and is turned off along with it.
    // Outside this chart everything stays selectable as usual.
    <div className="select-none" style={{ WebkitTouchCallout: "none" }}>
      {/* pr-12 is the gutter for the y labels; they are HTML, because <text> in the svg would
          distort along with preserveAspectRatio="none". */}
      <div className="pr-12">
        <div
          ref={wrap}
          // Exactly as wide as the svg: indexAt() calculates the pointing position from
          // this width, so no padding may be added here.
          className="relative"
          // pan-y: a sideways drag scrubs the crosshair, a vertical one still
          // scrolls the page. Without it a thumb landing on the chart — which
          // spans the full width of the card — could not scroll past it.
          style={{ touchAction: "pan-y", cursor: zooms ? "crosshair" : undefined }}
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
            aria-label={tr("Portfolio value over time")}
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
              {shown.value && visible.length === 1 && (
                <path className="ds-chart__area" d={`${path("value")} L${W} ${H} L0 ${H} Z`} fill="var(--chart-band)" />
              )}
              {/* In fixed order and not in that of `visible`, so Value always lies on top of
                  Deposited. */}
              {[...SERIES]
                .reverse()
                .filter((s) => shown[s.key])
                .map((s) => (
                  <path
                    key={s.key}
                    d={path(s.key)}
                    fill="none"
                    stroke={s.colour}
                    strokeWidth={s.width}
                    strokeDasharray={s.dash}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
            </g>

            {hover !== null && !measured && (
              <line className="ds-chart__cursor" x1={x(hover)} y1="0" x2={x(hover)} y2={H} vectorEffect="non-scaling-stroke" />
            )}

            {measured &&
              [measured.from, measured.to].map((i) => (
                <g key={i}>
                  <line x1={x(i)} y1="0" x2={x(i)} y2={H} stroke="var(--chart-1)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                  {visible.map((s) => (
                    <circle
                      key={s.key}
                      cx={x(i)}
                      cy={y(points[i][s.key])}
                      r="4"
                      fill={s.colour}
                      stroke="var(--surface-page)"
                      strokeWidth="2"
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                </g>
              ))}

            {shown.value && !measured && (
              <circle cx={W} cy={y(last.value)} r="3.5" fill="var(--chart-1)" stroke="var(--surface-page)" strokeWidth="2" />
            )}
          </svg>

          {/* The names at the end of their line. Right-aligned 6px from the right edge, so just
              before the end point and not over it. They disappear as soon as you measure or point:
              then it is about the point under your finger, and the card header already says which
              line that is. */}
          {!measured && hover === null && (
            <div className="pointer-events-none absolute inset-0">
              {endLabels.map((r) => (
                <span
                  key={r.key}
                  className="absolute -translate-y-1/2 whitespace-nowrap text-[11px] font-medium"
                  style={{ right: 6, top: `${(r.y / H) * 100}%`, color: r.colour }}
                >
                  {r.label}
                </span>
              ))}
            </div>
          )}

          {/* The y labels in the gutter on the right. hi and lo lie PAD_Y inside the viewBox, so
              the label is at the height of its own tick and not at a fixed fraction of the block. */}
          <div className="pointer-events-none absolute inset-y-0 -right-12 w-12 text-[11px] text-ink-muted">
            {ticks.map((t) => (
              <span key={t} className="num absolute left-1.5 -translate-y-1/2 whitespace-nowrap" style={{ top: `${(y(t) / H) * 100}%` }}>
                {fmtNumber(t, { decimals })}
              </span>
            ))}
          </div>
        </div>

        {zooms && dragging && measured ? (
          <div className="mt-1 h-4 text-xs text-ink-muted">{tr("let go to show this period")}</div>
        ) : intraday ? (
          <div className="mt-1 flex justify-between text-xs text-ink-muted">
            <span>{xLabel(points[0].d)}</span>
            <span>{xLabel(mid.d)}</span>
            <span>{xLabel(last.d)}</span>
          </div>
        ) : (
          // Round moments (days, Mondays, months, years) where they fall, not three
          // arbitrary points: the same axis as Net worth.
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
        )}
      </div>

      {/* The legend is also the on/off switch: the y axis scales to what is on. The last visible
          line can't be turned off — an empty chart is not a usable state. */}
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
        {SERIES.map((s) => {
          const on = shown[s.key];
          const onlyOne = on && visible.length === 1;
          return (
            <button
              key={s.key}
              type="button"
              aria-pressed={on}
              disabled={onlyOne}
              onClick={() => setOverride((o) => ({ ...o, [s.key]: !on }))}
              className={`inline-flex items-center gap-1.5 rounded-sm px-0.5 py-0.5 ${
                on ? "text-ink-muted" : "text-ink-muted/45"
              } ${onlyOne ? "cursor-default" : "hover:text-text"}`}
            >
              <span
                className="h-0 w-3.5 flex-none"
                style={{
                  borderTop: `${s.key === "value" ? 3 : 2}px ${
                    s.dash === "5 4" ? "dashed" : s.dash === "1 4" ? "dotted" : "solid"
                  } ${on ? s.colour : "var(--border-strong)"}`,
                }}
              />
              {s.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
