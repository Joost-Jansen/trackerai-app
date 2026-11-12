// The days you bought or sold, for the marks under the value and returns charts.
//
// One entry per day, not per transaction: a switch is ten orders on one morning,
// and ten marks on one spot read as a smudge. A day with any sale is a "sell" day,
// because that is a day the portfolio itself changed; a day with only buys is
// most often the monthly purchase and gets the quieter mark.

export type TradeTransaction = {
  date: string;
  name: string;
  transaction_type: string;
  total_eur: number | null;
};

export type TradeSide = { total: number; names: string[] };
export type TradeDay = { d: string; kind: "buy" | "sell"; sold: TradeSide; bought: TradeSide };

function side(amounts: Map<string, number>): TradeSide {
  const names = [...amounts.entries()].sort((a, b) => b[1] - a[1]).map(([n]) => n);
  return { total: [...amounts.values()].reduce((s, v) => s + v, 0), names };
}

/** Buys and sales per day, oldest first; within a side the largest amount first. */
export function tradeDays(transactions: TradeTransaction[]): TradeDay[] {
  const byDay = new Map<string, { sold: Map<string, number>; bought: Map<string, number> }>();
  for (const t of transactions) {
    const kind = t.transaction_type === "SELL" ? "sold" : t.transaction_type === "BUY" ? "bought" : null;
    if (!kind) continue;
    const d = t.date.slice(0, 10);
    const day = byDay.get(d) ?? { sold: new Map(), bought: new Map() };
    byDay.set(d, day);
    day[kind].set(t.name, (day[kind].get(t.name) ?? 0) + Math.abs(t.total_eur ?? 0));
  }
  return [...byDay.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([d, day]) => ({ d, kind: day.sold.size > 0 ? "sell" : "buy", sold: side(day.sold), bought: side(day.bought) }));
}
