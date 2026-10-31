"use client";

// The allocation over time: sector or region as stacked areas, one point per month-end plus today.
//
// Two views of the same stack. "Share" (the default) is 100%-stacked: every date fills the height, so what you
// read is the mix moving, which is the question this card answers. "Amount" stacks the euros, so the mix is seen
// together with the money growing; there the thin bands of the early months are the honest answer.
//
// Stacked areas tile and never overlap, so they may share one chart (as in NetWorthChart): each band gets a seam
// in the card colour, a name at its right end, and the readout above the chart lists every band by name — colour
// is never the only cue. The order is fixed (today's largest at the bottom, "Other" on top, grey), the same order
// and colours as the bars on the card above it.
//
// The look-through per fund is today's: the issuers publish their current holdings only. Holdings and prices are
// per date. The card says so in a sentence under the chart.

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDayMonthYear, fmtEu, fmtEuro } from "@/lib/format";
import { localName, OTHER, SEGMENT_COLOURS } from "@/lib/slices";
import { bandColours, stackBands, type AllocationHistory as History } from "@/lib/allocation-history";
import { dateTicks } from "@/lib/date-ticks";
import { dayNumber } from "@/lib/timeline";
import { Section, Tabs } from "@/components/ds";
import { tr, trx } from "@/lib/i18n";

type Mode = "sector" | "region";
type Scale = "pct" | "value";

const PATH = { top: 8, right: 104, bottom: 20 };
const HEIGHT = 240;
// Palette without the grey: grey is reserved for "Other" (lib/slices.ts).
const PALETTE = SEGMENT_COLOURS.slice(0, 5);

function Plot({
  dates,
  rows,
  keys,
  colours,
  scale,
  hover,
  onHover,
  ariaLabel,
}: {
  dates: string[];
  rows: number[][];
  keys: string[];
  colours: string[];
  scale: Scale;
  hover: number | null;
  onHover: (i: number | null) => void;
  ariaLabel: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(720);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setW(el.clientWidth || 720);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 720));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const bands = useMemo(() => stackBands(rows), [rows]);
  // On a phone the names at the right end take too much room; the readout above names every band anyway.
  const right = w < 420 ? 44 : PATH.right;
  const innerW = Math.max(w - right, 10);
  const innerH = HEIGHT - PATH.top - PATH.bottom;
  const hi = scale === "pct" ? 100 : Math.max(...bands.map((b) => (b.length ? b[b.length - 1].hi : 0)), 1);

  const start = dayNumber(dates[0]);
  const span = dayNumber(dates[dates.length - 1]) - start || 1;
  const x = (i: number) => ((dayNumber(dates[i]) - start) / span) * innerW;
  const y = (v: number) => PATH.top + (1 - v / hi) * innerH;

  const area = (k: number) => {
    const top = bands.map((b, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(b[k].hi).toFixed(1)}`).join("");
    const bottom = bands
      .map((b, i) => ({ b, i }))
      .reverse()
      .map(({ b, i }) => `L${x(i).toFixed(1)},${y(b[k].lo).toFixed(1)}`)
      .join("");
    return `${top}${bottom}Z`;
  };

  const nearest = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = ((e.clientX - rect.left) / rect.width) * w;
    let best = 0;
    for (let i = 1; i < dates.length; i++) if (Math.abs(x(i) - rel) < Math.abs(x(best) - rel)) best = i;
    return best;
  };

  const fmtAxis = (v: number) => (scale === "pct" ? fmtEu(v, { decimals: 0, suffix: "%" }) : fmtEuro(v, { decimals: 0 }));
  const grid = [0, hi / 2, hi];
  const ticks = dateTicks(dates[0], dates[dates.length - 1], innerW);

  // Names at the right end, in the middle of each band, pushed apart where they would land on each other.
  const end = bands[bands.length - 1];
  const labels: { k: number; y: number }[] = [];
  if (right === PATH.right) {
    const wanted = keys
      .map((_, k) => ({ k, y: y((end[k].lo + end[k].hi) / 2) + 3.5, size: end[k].hi - end[k].lo }))
      .filter((l) => l.size > 0)
      .sort((a, b) => b.y - a.y);
    for (const l of wanted) {
      const prev = labels[labels.length - 1];
      labels.push({ k: l.k, y: prev && prev.y - l.y < 12 ? prev.y - 12 : l.y });
    }
  }

  return (
    <div ref={box}>
      <svg
        width="100%"
        height={HEIGHT}
        viewBox={`0 0 ${w} ${HEIGHT}`}
        role="img"
        aria-label={ariaLabel}
        style={{ userSelect: "none", touchAction: "pan-y" }}
        onPointerMove={(e) => onHover(nearest(e))}
        onPointerDown={(e) => onHover(nearest(e))}
        onPointerLeave={() => onHover(null)}
      >
        {keys.map((key, k) => (
          <path
            key={key}
            d={area(k)}
            fill={colours[k]}
            fillOpacity={hover === null ? 0.7 : 0.6}
            stroke="var(--surface)"
            strokeWidth={1.5}
            strokeLinejoin="round"
          />
        ))}

        {grid.map((v) => (
          <g key={v}>
            <line x1={0} x2={innerW} y1={y(v)} y2={y(v)} stroke="var(--border-hairline)" strokeDasharray="1 4" />
            <text x={innerW + 6} y={y(v) + (v === hi ? 8 : v === 0 ? -2 : 3.5)} className="num" fontSize={10} fill="var(--text-faint)">
              {fmtAxis(v)}
            </text>
          </g>
        ))}

        {labels.map((l) => (
          <text key={keys[l.k]} x={innerW + 6} y={l.y} fontSize={10} fill="var(--text-muted)">
            {localName(keys[l.k])}
          </text>
        ))}

        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={PATH.top} y2={PATH.top + innerH} stroke="var(--border-strong)" strokeDasharray="2 3" />
        )}

        {ticks.map((t) => {
          const tx = ((dayNumber(t.d) - start) / span) * innerW;
          return (
            <g key={t.d}>
              <line x1={tx} x2={tx} y1={PATH.top + innerH} y2={PATH.top + innerH + 4} stroke="var(--border-strong)" />
              <text
                x={tx}
                y={HEIGHT - 4}
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
  );
}

export default function AllocationHistory() {
  const [mode, setMode] = useState<Mode>("sector");
  const [scale, setScale] = useState<Scale>("pct");
  const [hover, setHover] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["etf-history"],
    queryFn: () => api.get<History>("/api/etf-analysis/history"),
  });

  if (q.isLoading) return <div className="h-64 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  const data = q.data;
  if (!data) return null;
  if (data.unavailable) {
    return (
      <Section label={tr("Over time")}>
        <p className="text-sm text-ink-muted">
          {tr(
            "The price history could not be fetched from Yahoo Finance. Your positions and amounts are fine; only this chart is missing. Try again in a few minutes.",
          )}
        </p>
      </Section>
    );
  }
  // One point is not a line: a portfolio younger than a month has nothing to show over time yet.
  if (data.dates.length < 2) return null;

  const series = mode === "sector" ? data.sector : data.region;
  const rows = scale === "pct" ? series.pct : series.value;
  const colours = bandColours(series.keys, PALETTE, OTHER, "var(--n-400)");
  const at = hover ?? data.dates.length - 1;
  // The readout lists the bands top-down, the order you see them in the chart.
  const order = series.keys.map((_, k) => k).reverse();

  return (
    <Section
      label={tr("Over time")}
      info={
        <>
          {trx(
            "Your allocation at the end of every month, and today. What you held and what it was worth come from your transactions and that day's prices.{0}{1}How each fund is spread over sectors and regions is today's: the providers only publish their current holdings, so a past month is looked through with those.",
            <br />,
            <br />,
          )}
        </>
      }
      action={
        <span className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1">
          <Tabs
            variant="quiet"
            items={[
              { id: "sector", label: "Sector" },
              { id: "region", label: tr("Region") },
            ]}
            value={mode}
            onChange={(m) => setMode(m as Mode)}
            ariaLabel={tr("Breakdown by")}
          />
          <Tabs
            variant="quiet"
            items={[
              { id: "pct", label: tr("Share") },
              { id: "value", label: tr("Amount") },
            ]}
            value={scale}
            onChange={(s) => setScale(s as Scale)}
            ariaLabel={tr("Show as")}
          />
        </span>
      }
    >
      {/* Fixed height, as in NetWorthChart: the chart must not jump when you touch it. */}
      <div className="min-h-[40px] text-[13px]">
        <span className="font-semibold">{fmtDayMonthYear(data.dates[at])}</span>
        <span className="num text-xs text-ink-muted">
          {" · "}
          {fmtEuro(data.total[at], { decimals: 0 })}
        </span>
        {order.map((k) => (
          <span key={series.keys[k]} className="num whitespace-nowrap text-xs">
            {" · "}
            <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-sm align-middle" style={{ background: colours[k] }} />
            <span className="text-ink-muted">{localName(series.keys[k])}</span>{" "}
            {scale === "pct" ? fmtEu(series.pct[at][k], { decimals: 1, suffix: "%" }) : fmtEuro(series.value[at][k], { decimals: 0 })}
          </span>
        ))}
      </div>
      <Plot
        dates={data.dates}
        rows={rows}
        keys={series.keys}
        colours={colours}
        scale={scale}
        hover={hover}
        onHover={setHover}
        ariaLabel={mode === "sector" ? tr("Sector allocation over time") : tr("Region allocation over time")}
      />
      <p className="max-w-measure text-xs leading-relaxed text-ink-muted">
        {tr(
          "Each fund is looked through with its current holdings, also for past months: providers don't publish their history. What changes is what you held and what it was worth.",
        )}
        {data.estimated.length > 0 && (
          <> {tr("Without price history, estimated at {0}: {1}", data.estimated[0].base, data.estimated.map((e) => e.name).join(", "))}.</>
        )}
      </p>
    </Section>
  );
}
