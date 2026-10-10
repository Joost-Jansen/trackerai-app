"use client";

// One bar per week or month, always 100% high, split into the five zones
// (Z1 at the bottom). That shows the distribution shifting, regardless of how much you trained.
// Same set-up as charts/Bars: divs instead of svg and a readout line
// above the chart instead of a floating tooltip, so nothing jumps
// or falls off a phone screen. Bars itself shows one amount per bar; here
// each bar needs five shares plus hours in the line, hence a component of
// its own.

import { useLayoutEffect, useRef, useState } from "react";
import { useFormat, useT } from "@/lib/i18n";
import { EASY_TARGET, ZONE_COLOUR, ZONES, easyPct, type ZoneHistoryItem } from "@/lib/training";

export type ZoneStackBar = ZoneHistoryItem & {
  /** Short label under the bar. */
  short: string;
  /** The current period: not finished yet, drawn a bit lighter. */
  partial?: boolean;
};

export default function ZoneStackChart({
  bars,
  summary,
  labelEvery = 1,
  ariaLabel,
}: {
  bars: ZoneStackBar[];
  summary: React.ReactNode;
  labelEvery?: number;
  ariaLabel: string;
}) {
  const t = useT();
  const f = useFormat();
  const [active, setActive] = useState<number | null>(null);
  const shown = active !== null ? bars[active] : null;
  // How many labels fit at this width? A label ("25 mei") is ~45 px; on a phone with 27 weeks
  // they otherwise ran into each other ("25 mei15 jun").
  const row = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = row.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const every = width ? Math.max(labelEvery, Math.ceil(bars.length / Math.max(2, Math.floor(width / 52)))) : labelEvery;

  return (
    <div>
      {/* The summary stays put; the bar under the pointer gets a box beside it, as on the other charts. */}
      <div className="mb-2 text-[13px] text-ink-muted">{summary}</div>

      {/* Z1 and Z2 sit at the bottom, so where their top meets the dashed line the 80/20 aim is met. */}
      <div className="relative">
      <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 z-10 border-t border-dashed border-[var(--text-primary)] opacity-70" style={{ bottom: `${EASY_TARGET}%` }}>
        <span className="absolute -top-[9px] right-0 rounded bg-surface px-1 text-[10.5px] leading-[16px] text-[var(--text-primary)]">{EASY_TARGET}%</span>
      </div>
      <div role="group" aria-label={ariaLabel} className="flex h-[150px] items-stretch gap-[3px] sm:h-[180px]" onMouseLeave={() => setActive(null)}>
        {bars.map((bar, i) => (
          <button
            key={bar.start}
            type="button"
            onFocus={() => setActive(i)}
            onBlur={() => setActive(null)}
            onMouseEnter={() => setActive(i)}
            onClick={() => setActive(i)}
            aria-label={`${bar.label}: ${bar.total_s ? ZONES.map((z) => `${z} ${Math.round(bar.pct[z])}%`).join(", ") : t.zones.noHr}`}
            className="flex min-w-0 flex-1 flex-col justify-end overflow-hidden rounded-[4px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-focus)]"
          >
            {bar.total_s > 0 ? (
              // Z5 at the top, Z1 against the baseline.
              [...ZONES].reverse().map((z) =>
                bar.pct[z] > 0 ? (
                  <span
                    key={z}
                    aria-hidden="true"
                    className="block w-full"
                    style={{
                      height: `${bar.pct[z]}%`,
                      background: ZONE_COLOUR[z],
                      opacity: bar.partial ? 0.6 : 1,
                    }}
                  />
                ) : null,
              )
            ) : (
              <span aria-hidden="true" className="block h-[2px] w-full bg-border-strong" />
            )}
          </button>
        ))}
      </div>
      {shown && active != null && (
        <div
          className="ds-chart__tip"
          aria-live="polite"
          style={{
            left: `calc(${((active + 0.5) / bars.length) * 100}% ${active >= bars.length / 2 ? "- 10px" : "+ 10px"})`,
            top: 8,
            transform: active >= bars.length / 2 ? "translateX(-100%)" : "none",
            zIndex: 20,
          }}
        >
          <div className="font-semibold">{shown.label}</div>
          <div className="opacity-80">
            {shown.total_s ? f.hours(shown.total_s) : t.zones.noHr}
            {shown.partial ? ` · ${t.zones.running}` : ""}
          </div>
          {shown.total_s > 0 && (
            <>
              <div className="flex justify-between gap-3"><span className="opacity-80">{t.zones.easyShort}</span><span className="font-semibold">{Math.round(easyPct(shown.pct))}%</span></div>
              {ZONES.map((z) => (
                <div key={z} className="flex items-center gap-1.5">
                  <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: ZONE_COLOUR[z] }} />
                  <span className="opacity-80">{z}</span>
                  <span className="ml-auto pl-3 font-semibold">{Math.round(shown.pct[z])}%</span>
                  <span className="w-10 text-right opacity-80">{f.duration(shown.seconds[z])}</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
      </div>

      {/* Flex instead of text-center: a label wider than its bar then sticks out equally on both sides
          (text always overflows to the right), and the first and last label stay inside the card. */}
      <div ref={row} aria-hidden="true" className="mt-1.5 flex gap-[3px]">
        {bars.map((bar, i) => {
          const label = (bars.length - 1 - i) % every === 0;
          const edge = i === 0 ? "justify-start" : i === bars.length - 1 ? "justify-end" : "justify-center";
          return (
            <span key={bar.start} className={`flex min-w-0 flex-1 ${edge} whitespace-nowrap text-[11px] leading-tight ${i === active ? "font-semibold text-text" : "text-ink-muted"}`}>
              <span className="flex-none">{label ? bar.short : ""}</span>
            </span>
          );
        })}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3.5 gap-y-1 text-[11px] text-ink-muted">
        {ZONES.map((z) => (
          <span key={z} className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: ZONE_COLOUR[z] }} />
            {z}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block w-3 border-t border-dashed border-[var(--text-primary)]" />
          {t.zones.easyLine(EASY_TARGET)}
        </span>
        {bars.some((b) => b.partial) && <span>· {t.zones.lighter}</span>}
      </div>
    </div>
  );
}
