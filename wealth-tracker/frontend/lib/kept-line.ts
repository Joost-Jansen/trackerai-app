// The kept portfolio as a line on the Returns chart, next to your own and the indices.
//
// The backend gives the kept holdings' growth since the snapshot's day (1.0 on
// that day, dividends reinvested, no money in or out: /api/what-if/index). Drawn
// on the indexed chart it starts on your own line, so the two lines are one up
// to the snapshot and split after it. A snapshot older than the period shown
// starts on the period's first day instead, as every line there does.

export type IndexPoint = { d: string; v: number };

const round = (v: number) => Math.round(v * 1e4) / 1e4;

/** The last point on or before *d*, if any. */
function at(points: IndexPoint[], d: string): IndexPoint | undefined {
  let found: IndexPoint | undefined;
  for (const p of points) {
    if (p.d > d) break;
    found = p;
  }
  return found;
}

export function keptLine(portfolio: IndexPoint[], growth: IndexPoint[]): IndexPoint[] {
  if (portfolio.length === 0 || growth.length === 0) return [];
  const start = growth[0].d > portfolio[0].d ? growth[0].d : portfolio[0].d;
  if (start > portfolio[portfolio.length - 1].d) return [];
  const base = at(portfolio, start)!.v;
  const g0 = at(growth, start)!.v;
  if (!g0) return [];
  return [{ d: start, v: base }, ...growth.filter((g) => g.d > start).map((g) => ({ d: g.d, v: round((base * g.v) / g0) }))];
}
