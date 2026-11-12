// What was traded on a day, in one line under a chart's reading of that day:
// "sold €7,000 (S&P 500, ASML) · bought €1,900 (Alphabet)". At most three names a
// side, the largest first; the rest as a count, since the line has to stay a line.

import { fmtEuro } from "@/lib/format";
import { tr } from "@/lib/i18n";
import type { TradeDay, TradeSide } from "@/lib/trade-days";

const NAMES = 3;

function names(side: TradeSide): string {
  const rest = side.names.length - NAMES;
  return side.names.slice(0, NAMES).join(", ") + (rest > 0 ? ` +${rest}` : "");
}

export function tradeNote(day: TradeDay): string {
  const parts: string[] = [];
  if (day.sold.names.length > 0) parts.push(tr("sold {0} ({1})", fmtEuro(day.sold.total, { decimals: 0 }), names(day.sold)));
  if (day.bought.names.length > 0) parts.push(tr("bought {0} ({1})", fmtEuro(day.bought.total, { decimals: 0 }), names(day.bought)));
  return parts.join(" · ");
}
