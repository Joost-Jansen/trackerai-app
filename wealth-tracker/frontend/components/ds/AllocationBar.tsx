"use client";

// The distribution bar — Meridian's deliberate replacement of the donut.
//
// Why no donut: ratios are much easier to compare along one axis than along a
// circumference, and this costs a fraction of the height. The donut in
// components/dashboard/Donut.tsx and the two on the Allocation tab merge into
// this.
//
// At most six segments, the tail rolled up into "Other" — lib/slices.ts already
// does that, and the colours it passes along (--c1..c6) are Meridian's chart
// palette in a fixed order.

import { useState } from "react";
import { fmtEu } from "@/lib/format";

export type AllocationSegment = {
  label: string;
  /** Does not have to add up to 100 — the bar normalises itself. */
  value: number;
  colour?: string;
  /** On the right in the legend, instead of the percentage. */
  display?: string;
};

export default function AllocationBar({
  segments,
  showLegend = true,
  height = 8,
  ariaLabel,
  className = "",
}: {
  segments: AllocationSegment[];
  showLegend?: boolean;
  height?: number;
  ariaLabel?: string;
  className?: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const colourOf = (s: AllocationSegment, i: number) => s.colour ?? `var(--chart-${(i % 6) + 1})`;
  const pct = (s: AllocationSegment) => (s.value / total) * 100;

  if (segments.length === 0) return null;

  return (
    <div className={`ds-alloc ${className}`}>
      <div className="ds-alloc__bar" style={{ height }} role="img" aria-label={ariaLabel}>
        {segments.map((s, i) => (
          <div
            key={s.label}
            className="ds-alloc__seg"
            onMouseEnter={() => setActive(i)}
            onMouseLeave={() => setActive(null)}
            title={`${s.label} · ${fmtEu(pct(s), { decimals: 1, suffix: "%" })}`}
            style={{
              width: `${pct(s).toFixed(3)}%`,
              background: colourOf(s, i),
              opacity: active === null || active === i ? 1 : 0.35,
            }}
          />
        ))}
      </div>
      {showLegend && (
        <div className="ds-alloc__legend">
          {segments.map((s, i) => (
            <div key={s.label} className="ds-alloc__item" onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}>
              <span className="ds-alloc__swatch" style={{ background: colourOf(s, i) }} />
              {/* min-w-0 + truncate: a sector name such as "Consumer (cycl.)" must not push the
                  percentage off the line. */}
              <span className="min-w-0 flex-1 truncate">{s.label}</span>
              <span className="ds-alloc__pct">{s.display ?? fmtEu(pct(s), { decimals: 1, suffix: "%" })}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
