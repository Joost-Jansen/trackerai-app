// One period against the average of the X periods before it. The average
// share is time-weighted (all zone seconds summed / all seconds), so a
// week with twenty minutes does not count as much as a week with eight hours.
// Average hours are per period, empty periods count as zero.

import type { Format } from "@/lib/i18n";
import { ZONES, type Zone, type ZoneHistoryItem } from "@/lib/training";

export type ZoneCompareRow = {
  zone: Zone;
  pct: number | null;
  avgPct: number | null;
  diff: number | null;
  seconds: number;
  avgSeconds: number;
};

export type ZoneComparison = {
  target: ZoneHistoryItem;
  /** How many comparison periods there really are (fewer than X when the history is shorter). */
  periods: number;
  /** Of those, with heart-rate data. */
  withData: number;
  rows: ZoneCompareRow[];
  total: { seconds: number; avgSeconds: number };
  avgPct: Record<Zone, number> | null;
};

export function compareZones(items: ZoneHistoryItem[], x: number, which: "current" | "previous"): ZoneComparison | null {
  const idx = items.length - (which === "current" ? 1 : 2);
  if (idx < 0) return null;
  const target = items[idx];
  const base = items.slice(Math.max(0, idx - x), idx);
  const sum = Object.fromEntries(ZONES.map((z) => [z, base.reduce((s, i) => s + i.seconds[z], 0)])) as Record<Zone, number>;
  const baseTotal = ZONES.reduce((s, z) => s + sum[z], 0);
  const avgPct = baseTotal ? (Object.fromEntries(ZONES.map((z) => [z, (sum[z] / baseTotal) * 100])) as Record<Zone, number>) : null;
  const n = base.length || 1;
  const rows = ZONES.map((z) => {
    const pct = target.total_s ? (target.seconds[z] / target.total_s) * 100 : null;
    const avg = avgPct ? avgPct[z] : null;
    return { zone: z, pct, avgPct: avg, diff: pct != null && avg != null ? pct - avg : null, seconds: target.seconds[z], avgSeconds: sum[z] / n };
  });
  return {
    target,
    periods: base.length,
    withData: base.filter((i) => i.total_s > 0).length,
    rows,
    total: { seconds: target.total_s, avgSeconds: baseTotal / n },
    avgPct,
  };
}

export const fmtPct = (v: number | null) => (v == null ? "–" : `${Math.round(v)}%`);

/** "+3,2 pp" / "−1,0 pp": percentage points with a real minus sign. */
export function fmtPp(v: number | null, f?: Format): string {
  if (v == null) return "–";
  const r = Math.round(v * 10) / 10;
  if (r === 0) return "0 pp";
  return `${r > 0 ? "+" : "−"}${f ? f.num(Math.abs(r), 1) : Math.abs(r).toFixed(1).replace(".", ",")} pp`;
}
