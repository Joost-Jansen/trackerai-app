"use client";

// The net worth chart: three stacks and one line.
//
// Investments and bank stack above the zero line, debt hangs below it. The net
// line runs straight through — that is the number that matters, and the areas
// below show where it comes from.
//
// **Why there are several areas here, and not in LineChart.** Meridian says:
// area fill only with one series, because two filled shapes fight. That is true
// for lines that run over each other — then at every overlap you no longer know
// which is in front. Stacked areas precisely never overlap: they tile. Every
// area also gets a 2px stroke in the card colour, so there is always a visible
// seam between two stacks, and debt sits on the other side of the zero line.
// Position therefore does the work here that colour would have to do in a
// normal line chart.
//
// That is not a matter of style but a necessity: the palette check shows that
// Meridian's chart colours are deliberately low in saturation and too close
// together for colour-blind people (ΔE 4–9 where 8 is the minimum). Colour may
// therefore never be the only cue here. Hence: stacking order, the zero line, a
// name at the end of each area, and a readout *above* the chart.
//
// The readout sits above and not as a floating tooltip, for the same reason as
// in Bars: a tooltip next to the last point falls off the screen on a phone.
//
// **Two views.** The stacks need the zero line and the debt, so their axis spans
// the whole balance sheet; over a month the net line then moves a hair. The
// "Change" view drops the stacks and fits the axis to the net line itself, with
// the starting value as a dashed reference, so a week of spending is visible.
// Breakdown is the default; a choice for Change is remembered.
//
// **Split by source** (behind the ⚙ of Change, as on Spending) is the change split
// over time: from the start of the period, how much saving, the market, bank & cash
// and debt each added, one line per source from zero (bridgeSeries, the same
// arithmetic as the tiles). It answers "did I save this, or was it the market?". A
// line's name sits at its end, and one source can be shown alone; the axis then
// reads as change since the start.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { fmtDayMonthYear, WEEKDAY_ABBR } from "@/lib/format";
import type { useTimeline } from "@/components/money/TimelineControls";
import { Button, Explained, Tabs } from "@/components/ds";
import { Setting } from "@/components/money/charts/base";
import { TERMS } from "@/lib/net-worth-terms";
import { dayNumber, sampleBalances, windowWithBase } from "@/lib/timeline";
import { dateTicks } from "@/lib/date-ticks";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { tr, trx } from "@/lib/i18n";
import { bridge, bridgeSeries, type Flow, type SourcePoint } from "@/lib/net-worth-bridge";

export type NetWorthPoint = {
  d: string;
  /** The market value of the holdings in this app. Is *in* `investments`. */
  portfolio: number;
  /** DeGiro cash and brokers outside the app. Is also *in* `investments`. */
  investments_external: number;
  investments: number;
  bank: number;
  debt: number;
  net: number;
  measured: boolean;
  /** Cumulative: buys minus sells, and dividend received. For the market part of a change. */
  portfolio_invested?: number;
  portfolio_dividends?: number;
  /** Money of others ("Niet meetellen"): negative when held, positive when advanced. Already in debt or bank. */
  held?: number;
};

type Stack = { key: "investments" | "bank" | "debt"; label: string; colour: string };

// Fixed order, never sorted by size: a stack that changes place because it is a
// month larger makes the chart unreadable over time.
const STACKS: Stack[] = [
  { key: "investments", label: tr("Investments"), colour: "var(--chart-3)" },
  { key: "bank", label: tr("Bank & cash"), colour: "var(--chart-5)" },
  { key: "debt", label: tr("Debt"), colour: "var(--chart-4)" },
];

const PATH = { top: 16, right: 96, bottom: 20 };

/** The tabs above the chart. */
type NetWorthTab = "change" | "breakdown";
/** What the plot draws: a tab, or Change split by source (its ⚙). */
type NetWorthView = NetWorthTab | "sources";
/** Change, split by source: off, all of them, or one on its own. */
type Split = "off" | "all" | SourceKey;

type SourceKey = "saved" | "market" | "bank" | "debt";

// The same order as the tiles above the chart. Market and bank & cash take the colours of their stacks.
const SOURCES: { key: SourceKey; label: string; colour: string }[] = [
  { key: "saved", label: tr("Saved"), colour: "var(--chart-2)" },
  { key: "market", label: tr("Market"), colour: "var(--chart-3)" },
  { key: "bank", label: tr("Bank & cash"), colour: "var(--chart-5)" },
  { key: "debt", label: tr("Debt"), colour: "var(--chart-4)" },
];

// Saving and bank & cash together, before the bank data starts: there is nothing to tell them apart with.
const UNSPLIT = { key: "unsplit" as const, label: tr("Not split"), colour: "var(--text-muted)" };
// Lines that only mean something from the start of the bank data.
const BANKED_ONLY: string[] = ["saved", "bank"];

/** The first point in the bank data, or the number of points when there is none. */
function firstBanked(sources: SourcePoint[]): number {
  const i = sources.findIndex((p) => p.banked);
  return i < 0 ? sources.length : i;
}

/** "Sat 26 Sep 2026": with the weekday, because over a month that is what you place a day by. */
function fmtLongDay(d: string): string {
  const weekday = WEEKDAY_ABBR[(new Date(`${d}T00:00:00Z`).getUTCDay() + 6) % 7];
  return `${weekday} ${fmtDayMonthYear(d)}`;
}

function netLineOf(points: NetWorthPoint[], x: (i: number) => number, y: (v: number) => number): string {
  return points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.net).toFixed(1)}`).join("");
}

function NetWorthPlot({
  points,
  format,
  height = 260,
  ariaLabel,
  view,
  stepLabel,
  onSelect,
  sources = null,
  only = null,
}: {
  points: NetWorthPoint[];
  /** Per source: the split from the first point to each point, the same length as `points`. */
  sources?: SourcePoint[] | null;
  /** Per source: show this one source alone (with the net change for reference). */
  only?: SourceKey | null;
  format: (v: number) => string;
  height?: number;
  ariaLabel: string;
  view: NetWorthView;
  /** "vs the day before" or "vs the previous point", depending on the detail. */
  stepLabel: string;
  /** Drag across the chart to make that stretch the page's period. */
  onSelect?: (window: { from: string; to: string }) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState<number | null>(null);
  // Drag to select: the index where the mouse went down, while it is held.
  const [dragFrom, setDragFrom] = useState<number | null>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setW(el.clientWidth || 720);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 720));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Per source: the first point in the bank data. Before it, saving and bank & cash are one line, "Not split".
  // points.length when there is no bank data in the period: then saving and bank & cash have no line of their own.
  const banked = sources ? firstBanked(sources) : 0;
  const shownSources = useMemo(
    () => [
      ...SOURCES.filter((s) => (only === null || s.key === only) && (banked < points.length || !BANKED_ONLY.includes(s.key))),
      ...(only === null && banked > 0 ? [UNSPLIT] : []),
    ],
    [only, banked, points.length],
  );
  const model = useMemo(() => {
    if (points.length < 2) return null;
    if (view === "sources" && sources) {
      // Around zero, the start: every line begins there.
      const values = sources.flatMap((p) => [0, p.change, ...shownSources.map((s) => p[s.key])]);
      const min = Math.min(...values);
      const max = Math.max(...values);
      const pad = Math.max((max - min) * 0.08, 10);
      return { lo: min - pad, hi: max + pad };
    }
    if (view === "change") {
      // Fitted to the net line, with some air. A floor under the span keeps a
      // change of a few euros from filling the whole chart.
      const nets = points.map((p) => p.net);
      const min = Math.min(...nets);
      const max = Math.max(...nets);
      const floor = Math.max(Math.abs(nets[0]) * 0.004, 20);
      const span = Math.max(max - min, floor);
      const mid = (max + min) / 2;
      return { lo: mid - span * 0.62, hi: mid + span * 0.62 };
    }
    // The zero line always belongs: without it a debt of 39,000 is just as low as a
    // debt of 200, and you do not see that you are below zero.
    const values = points.flatMap((p) => [0, p.net, p.investments, p.investments + p.bank, p.debt]);
    return { lo: Math.min(...values), hi: Math.max(...values) };
  }, [points, view, sources, shownSources]);

  if (!model) return null;

  const { lo, hi } = model;
  const innerW = Math.max(w - PATH.right, 10);
  const innerH = height - PATH.top - PATH.bottom;
  const span = hi - lo || 1;

  const timeStart = dayNumber(points[0].d);
  const timeSpan = dayNumber(points[points.length - 1].d) - timeStart || 1;
  const x = (i: number) => ((dayNumber(points[i].d) - timeStart) / timeSpan) * innerW;
  const y = (v: number) => PATH.top + (1 - (v - lo) / span) * innerH;

  /** A stacked area between two series, as one closed path. */
  const area = (under: (p: NetWorthPoint) => number, above: (p: NetWorthPoint) => number) => {
    const outward = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(above(p)).toFixed(1)}`);
    const back = [...points]
      .map((p, i) => ({ p, i }))
      .reverse()
      .map(({ p, i }) => `L${x(i).toFixed(1)},${y(under(p)).toFixed(1)}`);
    return `${outward.join("")}${back.join("")}Z`;
  };

  const paths: Record<Stack["key"], string> = {
    investments: area(
      () => 0,
      (p) => p.investments,
    ),
    bank: area(
      (p) => p.investments,
      (p) => p.investments + p.bank,
    ),
    // Debt hangs below the zero line; the other side of the axis is the strongest
    // separation there is and costs no colour.
    debt: area(
      () => 0,
      (p) => p.debt,
    ),
  };

  const netLine = netLineOf(points, x, y);

  /** The point closest to the mouse, as an index. */
  const nearest = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = ((e.clientX - rect.left) / rect.width) * w;
    return Math.max(
      0,
      Math.min(
        points.length - 1,
        points.reduce((best, _p, i) => (Math.abs(x(i) - rel) < Math.abs(x(best) - rel) ? i : best), 0),
      ),
    );
  };

  const active = hover !== null ? points[hover] : null;
  const last = points[points.length - 1];
  const first = points[0];
  const fitted = view === "change" || view === "sources";
  const gridValues = fitted ? [lo + span * 0.1, lo + span / 2, hi - span * 0.1] : [lo, lo + span / 2, hi];
  const ticks = dateTicks(first.d, last.d, innerW);

  // The change view's fill: between the net line and the starting value.
  const startFill =
    view === "change"
      ? `${netLineOf(points, x, y)}L${x(points.length - 1).toFixed(1)},${y(first.net).toFixed(1)}L${x(0).toFixed(1)},${y(first.net).toFixed(1)}Z`
      : "";

  // Labels on the right: "Net" above its end point, "Start" on its line. When they
  // land on each other, or on an axis value, they are pushed apart and the axis
  // value gives way.
  let netLabelY = y(last.net) - 8;
  let startLabelY = y(first.net) + 3.5;
  if (view === "change" && Math.abs(netLabelY - startLabelY) < 12) {
    const above = Math.min(netLabelY, startLabelY);
    netLabelY = above;
    startLabelY = above + 12;
  }
  // Per source: a name at the end of each line, pushed apart where they would land on each other.
  const sourceLabels: { key: string; label: string; colour: string; y: number }[] = [];
  if (view === "sources" && sources) {
    const end = sources[sources.length - 1];
    const wanted = [
      ...shownSources.map((s) => ({ key: s.key, label: s.label, colour: s.colour, y: y(end[s.key]) + 3.5 })),
      { key: "change", label: tr("Net"), colour: "var(--chart-1)", y: y(end.change) + 3.5 },
      { key: "start", label: tr("Start"), colour: "var(--text-faint)", y: y(0) + 3.5 },
    ].sort((a, b) => a.y - b.y);
    for (const l of wanted) {
      const prev = sourceLabels[sourceLabels.length - 1];
      sourceLabels.push({ ...l, y: prev && l.y - prev.y < 12 ? prev.y + 12 : l.y });
    }
  }
  const taken = view === "sources" ? sourceLabels.map((l) => l.y) : view === "change" ? [netLabelY, startLabelY] : [netLabelY];
  const freeForAxis = (v: number) => taken.every((t) => Math.abs(y(v) + 3.5 - t) >= 12);

  const signed = (v: number) => `${v > 0 ? "+" : ""}${trueMinus(format(v))}`;
  const tone = (v: number) => (v > 0 ? "var(--text-gain)" : v < 0 ? "var(--text-loss)" : "var(--text-muted)");

  return (
    <div>
      {/* Vaste hoogte, zoals in Bars: de grafiek mag niet verspringen als je
          hem aanraakt. */}
      <div className="mb-2 flex min-h-[34px] flex-col gap-y-0.5 sm:min-h-[20px] sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-2.5">
        {dragFrom !== null && hover !== null && hover !== dragFrom ? (
          (() => {
            const [a, b] = dragFrom < hover ? [dragFrom, hover] : [hover, dragFrom];
            const delta = points[b].net - points[a].net;
            return (
              <span className="text-[13px]">
                <strong>
                  {fmtDayMonthYear(points[a].d)} – {fmtDayMonthYear(points[b].d)}
                </strong>
                {" · "}
                <span className="num" style={{ color: tone(delta) }}>
                  {signed(delta)}
                </span>
                {" · "}
                <span className="text-xs text-ink-muted">{tr("let go to show this period")}</span>
              </span>
            );
          })()
        ) : view === "sources" && sources ? (
          (() => {
            const since = fmtDayMonthYear(first.d);
            const at = sources[hover ?? sources.length - 1];
            // Before the bank data, saving and bank & cash are only known together.
            const listed = [...SOURCES, ...(banked > 0 ? [UNSPLIT] : [])].filter((s) => at.banked || !BANKED_ONLY.includes(s.key));
            return (
              <span className="text-[13px]">
                <span className="font-semibold">{hover !== null ? fmtLongDay(at.d) : trx("Since {0}", since)}</span>
                {hover !== null && (
                  <span className="text-xs text-ink-muted">
                    {" · "}
                    {trx("since {0}", since)}
                  </span>
                )}
                {listed.map((s) => (
                  <span key={s.key} className="num text-xs">
                    {" · "}
                    <span className="text-ink-muted">{s.label}</span>{" "}
                    <span className="whitespace-nowrap" style={{ color: tone(at[s.key]) }}>
                      {signed(at[s.key])}
                    </span>
                  </span>
                ))}
                <span className="num text-xs">
                  {" · "}
                  <span className="text-ink-muted">{tr("Net")}</span>{" "}
                  <strong className="whitespace-nowrap" style={{ color: tone(at.change) }}>
                    {signed(at.change)}
                  </strong>
                </span>
              </span>
            );
          })()
        ) : active ? (
          <>
            <span className="text-[13px] font-semibold">{fmtLongDay(active.d)}</span>
            <span className="num text-[13px] font-semibold">{trueMinus(format(active.net))}</span>
            {hover !== null && hover > 0 && (
              <span className="num text-xs" style={{ color: tone(active.net - first.net) }}>
                {trx("{0} since {1}", signed(active.net - first.net), fmtDayMonthYear(first.d))}
              </span>
            )}
            {hover !== null && hover > 0 && (
              <span className="num text-xs" style={{ color: tone(active.net - points[hover - 1].net) }}>
                {signed(active.net - points[hover - 1].net)} {stepLabel}
              </span>
            )}
            <span className="text-xs text-ink-muted">
              {/* The portfolio by name: it is in the investments stack, and you should be able to
                  read that instead of assuming it. */}
              {(
                [
                  [tr("Portfolio"), active.portfolio],
                  [tr("DeGiro cash & other"), active.investments_external],
                  [tr("Bank & cash"), active.bank],
                  [tr("Debt"), active.debt],
                ] as const
              )
                .filter(([, value]) => value !== 0)
                .map(([label, value]) => `${label} ${trueMinus(format(value))}`)
                .join(" · ")}
            </span>
            {!active.measured && (
              // Without this every point seems equally hard measured.
              <span className="text-xs text-ink-muted">{tr("calculated or estimated balance")}</span>
            )}
          </>
        ) : (
          <span className="text-[13px] text-ink-muted">
            {trx("Net {0} on {1}", trueMinus(format(last.net)), fmtDayMonthYear(last.d))}
            {" · "}
            <span className="num" style={{ color: tone(last.net - first.net) }}>
              {trx("{0} since {1}", signed(last.net - first.net), fmtDayMonthYear(first.d))}
            </span>
          </span>
        )}
      </div>

      <div ref={box}>
        <svg
          width="100%"
          height={height}
          viewBox={`0 0 ${w} ${height}`}
          role="img"
          aria-label={ariaLabel}
          style={{ cursor: onSelect ? "crosshair" : undefined, userSelect: "none", touchAction: "pan-y" }}
          onMouseLeave={() => {
            setHover(null);
            setDragFrom(null);
          }}
          onMouseMove={(e) => setHover(nearest(e))}
          onMouseDown={(e) => {
            if (!onSelect || e.button !== 0) return;
            e.preventDefault();
            setDragFrom(nearest(e));
          }}
          onMouseUp={(e) => {
            if (dragFrom === null || !onSelect) return;
            const to = nearest(e);
            setDragFrom(null);
            const [a, b] = dragFrom < to ? [dragFrom, to] : [to, dragFrom];
            // A click is not a selection: it needs two different days.
            if (b > a) onSelect({ from: points[a].d, to: points[b].d });
          }}
        >
          {gridValues.map((v) => (
            <g key={v}>
              <line x1={0} x2={innerW} y1={y(v)} y2={y(v)} stroke="var(--border-hairline)" strokeDasharray="1 4" />
              {freeForAxis(v) && (
                <text x={innerW + 6} y={y(v) + 3.5} className="num" fontSize={10} fill="var(--text-faint)">
                  {view === "sources" ? signed(v) : trueMinus(format(v))}
                </text>
              )}
            </g>
          ))}

          {/* The zero line heavier than the grid: being below zero is a different kind of fact than
              an intermediate value. */}
          {lo < 0 && hi > 0 && <line x1={0} x2={innerW} y1={y(0)} y2={y(0)} stroke="var(--border-strong)" />}

          {view === "change" && (
            <>
              <path d={startFill} fill="var(--chart-1)" fillOpacity={0.1} />
              <line x1={0} x2={innerW} y1={y(first.net)} y2={y(first.net)} stroke="var(--text-faint)" strokeDasharray="4 4" />
              <text x={innerW + 6} y={startLabelY} fontSize={10} fill="var(--text-faint)">
                {tr("Start")}
              </text>
            </>
          )}

          {view === "breakdown" &&
            STACKS.map((s) => (
              <path
                key={s.key}
                d={paths[s.key]}
                fill={s.colour}
                fillOpacity={0.55}
                // The seam between two stacks, in the card colour. Without this stroke two areas
                // of almost the same shade run into each other.
                stroke="var(--surface)"
                strokeWidth={2}
                strokeLinejoin="round"
              />
            ))}

          {view === "sources" && sources ? (
            <>
              <line x1={0} x2={innerW} y1={y(0)} y2={y(0)} stroke="var(--text-faint)" strokeDasharray="4 4" />
              {/* Where the bank data starts, when that is after the start of the period. */}
              {banked > 0 && banked < points.length && (
                <>
                  <line x1={x(banked)} x2={x(banked)} y1={PATH.top} y2={PATH.top + innerH} stroke="var(--border-strong)" />
                  {x(banked) > 100 && (
                    <text x={x(banked) - 6} y={PATH.top + 10} fontSize={10} fill="var(--text-faint)" textAnchor="end">
                      {tr("No bank data yet")}
                    </text>
                  )}
                </>
              )}
              {shownSources.map((s) => (
                <path
                  key={s.key}
                  d={sources
                    .map((p, i) => ({ p, i }))
                    .slice(BANKED_ONLY.includes(s.key) ? banked : 0)
                    .map(({ p, i }, n) => `${n ? "L" : "M"}${x(i).toFixed(1)},${y(p[s.key]).toFixed(1)}`)
                    .join("")}
                  fill="none"
                  stroke={s.colour}
                  strokeWidth={1.75}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}
              {/* The net change on top: the sum of the lines below it. Thinner and fainter when one source is
                  shown alone, as a reference. */}
              <path
                d={sources.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.change).toFixed(1)}`).join("")}
                fill="none"
                stroke="var(--chart-1)"
                strokeWidth={only === null ? 2.25 : 1.25}
                strokeOpacity={only === null ? 1 : 0.5}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </>
          ) : (
            <>
              <path d={netLine} fill="none" stroke="var(--chart-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

              {/* A faint dot on each real measurement: the line between them is extrapolated
                  balance. Kept small, the hover readout says it outright. */}
              {points.map((p, i) =>
                p.measured ? <circle key={p.d} cx={x(i)} cy={y(p.net)} r={1.5} fill="var(--chart-1)" fillOpacity={0.45} /> : null,
              )}
            </>
          )}

          {/* The stretch being dragged over. */}
          {dragFrom !== null && hover !== null && hover !== dragFrom && (
            <rect
              x={Math.min(x(dragFrom), x(hover))}
              width={Math.abs(x(hover) - x(dragFrom))}
              y={PATH.top}
              height={innerH}
              fill="var(--chart-1)"
              fillOpacity={0.12}
              stroke="var(--chart-1)"
              strokeOpacity={0.5}
            />
          )}

          {hover !== null && (
            <>
              <line x1={x(hover)} x2={x(hover)} y1={PATH.top} y2={PATH.top + innerH} stroke="var(--border-strong)" strokeDasharray="2 3" />
              {view === "sources" && sources ? (
                [...shownSources, { key: "change" as const, colour: "var(--chart-1)" }]
                  .filter((s) => sources[hover].banked || !BANKED_ONLY.includes(s.key))
                  .map((s) => (
                    <circle
                      key={s.key}
                      cx={x(hover)}
                      cy={y(sources[hover][s.key])}
                      r={3}
                      fill={s.colour}
                      stroke="var(--surface)"
                      strokeWidth={1.5}
                    />
                  ))
              ) : (
                <circle cx={x(hover)} cy={y(points[hover].net)} r={4} fill="var(--chart-1)" stroke="var(--surface)" strokeWidth={2} />
              )}
            </>
          )}

          {/* Names at the end of each area, as LineChart does — that saves a legend block and makes
              identity independent of colour. */}
          {view === "sources" ? (
            sourceLabels.map((l) => (
              <text key={l.key} x={innerW + 6} y={l.y} fontSize={10} fill={l.colour}>
                {l.label}
              </text>
            ))
          ) : (
            <text x={innerW + 6} y={netLabelY} fontSize={10} fill="var(--chart-1)">
              {tr("Net")}
            </text>
          )}
          {view === "breakdown" &&
            STACKS.map((s) => {
              const middle =
                s.key === "investments" ? last.investments / 2 : s.key === "bank" ? last.investments + last.bank / 2 : last.debt / 2;
              if (last[s.key] === 0) return null;
              return (
                <text key={s.key} x={innerW + 6} y={y(middle) + 3.5} fontSize={10} fill="var(--text-faint)">
                  {s.label}
                </text>
              );
            })}

          {/* Dates at round moments along the bottom, each with a faint tick. */}
          {ticks.map((t) => {
            const tx = ((dayNumber(t.d) - timeStart) / timeSpan) * innerW;
            return (
              <g key={t.d}>
                <line x1={tx} x2={tx} y1={PATH.top + innerH} y2={PATH.top + innerH + 4} stroke="var(--border-strong)" />
                <text
                  x={tx}
                  y={height - 4}
                  fontSize={10}
                  fill="var(--text-faint)"
                  textAnchor={tx < 20 ? "start" : tx > innerW - 20 ? "end" : "middle"}
                >
                  {t.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export default function NetWorthChart({
  boundaries,
  timeline,
  granularity,
  flows = [],
  sharedAsSpending = false,
  ...props
}: {
  points: NetWorthPoint[];
  format: (v: number) => string;
  height?: number;
  ariaLabel: string;
  flows?: Flow[];
  sharedAsSpending?: boolean;
  boundaries?: string[] | null;
  timeline: ReturnType<typeof useTimeline>;
  granularity: string;
}) {
  // From the balance at the end of the day before the window: see windowWithBase.
  const selected = windowWithBase(props.points, timeline.window);
  const points = sampleBalances(selected, granularity, boundaries);
  const change = selected.length > 1 ? selected[selected.length - 1].net - selected[0].net : null;
  const [chosen, choose] = useState<NetWorthTab | null>(null);
  const [chosenSplit, setSplit] = useState<Split>("off");
  // Choices are remembered for this browser; without one it is Breakdown, not split. "sources" is the former
  // Per source tab: now Change, split by all sources.
  useEffect(() => {
    try {
      const saved = localStorage.getItem("net-worth-view");
      if (saved === "change" || saved === "breakdown") choose(saved);
      if (saved === "sources") {
        choose("change");
        setSplit("all");
      }
      const split = localStorage.getItem("net-worth-split");
      if (split === "off" || split === "all" || SOURCES.some((s) => s.key === split)) setSplit(split as Split);
    } catch {
      /* no storage: the defaults apply */
    }
  }, []);
  // Per source: each part where its own data is (see bridgeSeries).
  const sources = useMemo(
    () => (points.length > 1 ? bridgeSeries(points, flows, sharedAsSpending) : null),
    [points, flows, sharedAsSpending],
  );
  const hasBank = !!sources && firstBanked(sources) < sources.length;
  // Saved or Bank & cash alone means nothing without bank data in the period: then it is all of them.
  const split: Split = chosenSplit !== "off" && !hasBank && BANKED_ONLY.includes(chosenSplit) ? "all" : chosenSplit;
  const tab: NetWorthTab = chosen ?? "breakdown";
  const view: NetWorthView = tab === "change" && split !== "off" && sources ? "sources" : tab;
  const only = split === "off" || split === "all" ? null : split;
  const [settingUp, setSettingUp] = useState(false);
  const remember = (key: string, value: string) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* fine */
    }
  };
  const pick = (v: NetWorthTab) => {
    choose(v);
    remember("net-worth-view", v);
  };
  const VIEWS: { id: NetWorthTab; label: string }[] = [
    { id: "breakdown", label: tr("Breakdown") },
    { id: "change", label: tr("Change") },
  ];
  const stepLabel = granularity === "day" ? tr("vs the day before") : tr("vs the previous point");
  return (
    <div>
      {change !== null && (
        <p className="pb-3 text-sm">
          <Explained
            text={`${tr("Including deposits, withdrawals and changes in available data.")} ${tr("From {0} to {1}. The parts below add up to it; it's not a return calculation.", fmtDayMonthYear(selected[0].d), fmtDayMonthYear(selected[selected.length - 1].d))}`}
          >
            {tr("Net worth difference in view")}
          </Explained>
          {": "}
          <strong className="num">
            {change > 0 ? "+" : ""}
            {trueMinus(props.format(change))}
          </strong>
        </p>
      )}
      {selected.length > 1 &&
        (() => {
          const first = selected[0],
            end = selected[selected.length - 1];
          const split = bridge(first, end, flows, sharedAsSpending);
          // With bank transactions: what you saved, what the market did and the rest.
          // Without them, the old split by stack, which is all there is to say.
          const cards =
            split.saved !== null
              ? [
                  { label: tr("Saved"), value: split.saved, sub: tr("Income minus spending"), help: TERMS.saved() },
                  {
                    label: tr("Market"),
                    value: split.market!,
                    sub: tr("What your holdings did: price changes and dividend"),
                    help: TERMS.market(),
                  },
                  {
                    label: tr("Bank & cash"),
                    value: split.bank!,
                    sub: tr("Gifts, money for friends, transfers and corrections"),
                    help: TERMS.bank(),
                  },
                  {
                    label: tr("Debt"),
                    value: split.debt!,
                    sub: tr("Your own debts: repayments positive, interest negative"),
                    help: TERMS.debt(),
                  },
                ]
              : (
                  [
                    { key: "investments", label: tr("Change in investments"), sub: tr("Including price changes and deposits") },
                    { key: "bank", label: tr("Change in bank & cash"), sub: tr("Difference between the balances shown") },
                    { key: "debt", label: tr("Effect of debts"), sub: tr("Positive means less debt") },
                  ] as const
                ).map((c) => ({ label: c.label, value: end[c.key] - first[c.key], sub: c.sub, help: null as string | null }));
          return (
            <div className={`mb-5 grid gap-3 ${cards.length === 4 ? "sm:grid-cols-2 lg:grid-cols-4" : "sm:grid-cols-3"}`}>
              {cards.map(({ label, value, sub, help }) => (
                <div key={label} className="rounded-lg border p-3" style={{ borderColor: "var(--rule)" }}>
                  <p className="text-xs text-ink-muted">
                    <Explained text={help ?? sub}>{label}</Explained>
                  </p>
                  <p className="num py-1 text-lg">
                    {Math.round(value * 100) > 0 ? "+" : ""}
                    {trueMinus(props.format(Math.round(value * 100) / 100 || 0))}
                  </p>
                </div>
              ))}
            </div>
          );
        })()}
      {points.length > 1 && (
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Tabs items={VIEWS} value={tab} variant="segmented" ariaLabel={tr("Chart view")} onChange={(v) => pick(v as NetWorthTab)} />
          <span className="text-xs text-ink-muted">
            <Explained
              text={`${
                view === "sources"
                  ? sources && firstBanked(sources) === sources.length
                    ? tr(
                        "From the start of the period: how much the market and debt each added to your net worth. There is no bank data in this period, so saving and bank & cash are one line: Not split.",
                      )
                    : sources && firstBanked(sources) > 0
                      ? tr(
                          "From the start of the period: how much saving, the market, bank & cash and debt each added to your net worth. Together they make the net line. Before {0} there is no bank data, so saving and bank & cash are one line there: Not split.",
                          fmtDayMonthYear(sources[firstBanked(sources)].d),
                        )
                      : tr(
                          "From the start of the period: how much saving, the market, bank & cash and debt each added to your net worth. Together they make the net line; at the end they are the tiles above.",
                        )
                  : view === "change"
                    ? tr("Net worth only, with the axis fitted to it: small changes become visible.")
                    : tr("Investments, bank and debt stacked, from zero.")
              } ${tr("Drag across the chart to show that stretch.")}`}
            >
              {tr("How to read this")}
            </Explained>
          </span>
          {tab === "change" && sources && (
            // As on Spending: what you can change about the chart sits behind ⚙.
            <span className="ml-auto">
              <Button size="sm" variant="ghost" aria-expanded={settingUp} onClick={() => setSettingUp((o) => !o)}>
                <span aria-hidden>⚙</span> {settingUp ? tr("Done") : tr("Set up")}
              </Button>
            </span>
          )}
        </div>
      )}
      {settingUp && tab === "change" && sources && (
        <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2.5 rounded-md p-3" style={{ background: "var(--surface-inset)" }}>
          <Setting
            label={tr("Split by source")}
            value={split}
            options={[
              ["off", tr("Off")],
              ["all", tr("All")],
              ...SOURCES.filter((s) => hasBank || !BANKED_ONLY.includes(s.key)).map((s): [string, string] => [s.key, s.label]),
            ]}
            onChange={(v) => {
              setSplit(v as Split);
              remember("net-worth-split", v);
            }}
          />
        </div>
      )}
      {points.length > 1 ? (
        <NetWorthPlot
          key={`${timeline.window.from}:${timeline.window.to}:${granularity}:${view}`}
          {...props}
          points={points}
          view={view}
          stepLabel={stepLabel}
          onSelect={timeline.change}
          sources={view === "sources" ? sources : null}
          only={only}
        />
      ) : (
        <p className="py-6 text-sm text-ink-muted">{tr("Not enough data for a line in this period. Zoom out or choose another period.")}</p>
      )}
      {granularity !== "day" && (
        <p className="pt-2 text-xs text-ink-muted">
          {trx(
            "Latest available value per {0}; the starting point stays visible.",
            granularity === "month" ? (boundaries ? tr("salary month: the day before your next salary") : tr("month")) : tr("year"),
          )}
        </p>
      )}
    </div>
  );
}
