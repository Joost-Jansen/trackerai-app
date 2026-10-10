// The vertical axis of a line chart: round values to label, and the number of
// decimals that goes with them.
//
// Lived in ValueChart.tsx, where it was written; the price chart on a position
// page needs the same axis, and a second copy of `niceTicks` is exactly the kind
// of duplication that gives two charts with a different scale after one change.

/**
 * Round intermediate values within [lo, hi], always 1/2/2.5/5 × 10ⁿ.
 *
 *  The step is not derived from (hi − lo)/n but chosen: the finest step that
 *  still gives at most `max` labels. A derived step can land just off, and then
 *  two labels remain for the whole height.
 */
export function niceTicks(lo: number, hi: number, max = 5): number[] {
  if (!Number.isFinite(hi - lo) || hi <= lo) return [];
  const top = Math.floor(Math.log10(hi - lo));
  const steps: number[] = [];
  for (let e = top - 3; e <= top + 1; e++) {
    for (const m of [1, 2, 2.5, 5]) steps.push(m * 10 ** e);
  }
  steps.sort((a, b) => a - b);
  const count = (s: number) => Math.floor(hi / s) - Math.ceil(lo / s) + 1;
  const step = steps.find((s) => count(s) <= max) ?? steps[steps.length - 1];

  const ticks: number[] = [];
  // The epsilon catches the floating point remainders that would otherwise make a
  // tick that falls exactly on `hi` fall just outside it.
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) {
    ticks.push(Math.abs(t) < step * 1e-9 ? 0 : t);
  }
  return ticks;
}

export function tickDecimals(ticks: number[]): number {
  if (ticks.length < 2) return 0;
  const step = Math.abs(ticks[1] - ticks[0]);
  if (step >= 1) return 0;
  return step >= 0.1 ? 1 : 2;
}
