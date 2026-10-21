"use client";

// The direction line next to the total return: where the value went in the last
// month, without axes, labels or pointing. If it needs those, it is not a
// sparkline but a chart.
//
// Green if it ends above where it started, red if below — for a sparkline
// direction-as-colour *is* allowed, because the line itself also shows the
// direction. No area fill any more: the fill below it was a gradient, and this
// design does not have those.

import type { SparklinePoint } from "@/lib/dashboard";
import { tr } from "@/lib/i18n";

export default function Sparkline({ points, className = "" }: { points: SparklinePoint[]; className?: string }) {
  if (points.length < 2) return null;

  const W = 188;
  const H = 40;
  const PATH = 3;
  const values = points.map((p) => p.v);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const x = (i: number) => (i / (points.length - 1)) * (W - 2 * PATH) + PATH;
  const y = (v: number) => PATH + (1 - (v - min) / span) * (H - 2 * PATH);
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");

  const up = values[values.length - 1] >= values[0];
  const colour = up ? "var(--data-gain)" : "var(--data-loss)";

  return (
    // No fixed width: this line sits in a 264px column and so has to shrink along.
    // preserveAspectRatio="none" stretches the viewBox, and vector-effect keeps the
    // line width out of that.
    <svg
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      fill="none"
      role="img"
      aria-label={tr("Value over the last month, {0}", up ? "stijgend" : "dalend")}
      className={`ds-spark w-full ${className}`}
    >
      <path d={line} stroke={colour} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
