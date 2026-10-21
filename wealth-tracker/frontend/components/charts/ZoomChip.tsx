"use client";

// The period you dragged out on a chart, as a chip next to the period buttons.
// The × goes back to the button that was on. Same chip as Net worth's filter bar.

import { fmtDayMonthYear } from "@/lib/format";
import { tr } from "@/lib/i18n";

export type ZoomWindow = { from: string; to: string };

export default function ZoomChip({ zoom, onClear }: { zoom: ZoomWindow; onClear: () => void }) {
  const label = `${fmtDayMonthYear(zoom.from)} – ${fmtDayMonthYear(zoom.to)}`;
  return (
    <button
      type="button"
      onClick={onClear}
      title={tr("Remove filter {0}", label)}
      aria-label={tr("Remove filter {0}", label)}
      className="time-filterbar__chip shrink-0 self-start rounded-full border px-2.5 py-1 text-xs"
    >
      <span className="num">{label}</span>
      <span aria-hidden>×</span>
    </button>
  );
}

/** The points within a dragged window; the whole series when it would leave fewer than two. */
export function sliceByZoom<T extends { d: string }>(points: T[], zoom: ZoomWindow | null): T[] {
  if (!zoom) return points;
  const inside = points.filter((p) => p.d >= zoom.from && p.d <= zoom.to);
  return inside.length >= 2 ? inside : points;
}
