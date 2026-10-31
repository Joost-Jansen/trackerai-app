// The allocation over time (/api/etf-analysis/history): types and the arithmetic of the stacked chart, apart from
// the drawing so node can test it (scripts/test-allocation-history.mjs).

export type AllocationSeries = {
  /** The slices, fixed for the whole series: the top five by today's share, then "Other". */
  keys: string[];
  /** Per date, per key: the share of that date's analysed value, in percent. */
  pct: number[][];
  /** Per date, per key: euros. */
  value: number[][];
};

export type AllocationHistory = {
  dates: string[];
  /** Per date: the analysed (equity) value in euros, the sum of each date's `value`. */
  total: number[];
  sector: AllocationSeries;
  region: AllocationSeries;
  /** Positions valued with a stand-in price on some date (no price history). */
  estimated: { isin: string; name: string; base: string }[];
  /** "current": the look-through per fund is today's, applied to every past date. */
  breakdown_as_of: string;
  unavailable?: boolean;
};

/** Per date the lower and upper edge of each band, stacked in key order from zero. */
export function stackBands(rows: number[][]): { lo: number; hi: number }[][] {
  return rows.map((row) => {
    let at = 0;
    return row.map((v) => {
      const lo = at;
      at += Math.max(v, 0);
      return { lo, hi: at };
    });
  });
}

/** The colours by position, the same order lib/slices.ts gives the current card; "Other" is always grey. */
export function bandColours(keys: string[], palette: readonly string[], other: string, otherColour: string): string[] {
  let i = 0;
  return keys.map((k) => (k === other ? otherColour : palette[i++ % palette.length]));
}
