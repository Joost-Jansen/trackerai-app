// Brokers: where the portfolio is held, and what was entered at each by hand.
//
// The contract of /api/brokers (backend/app/routers/brokers.py). A broker is a
// code ("degiro", "trade_republic"); its cash is an account of kind "broker"
// whose provider is that code, and it counts on the investments stack of net
// worth. Positions of the same fund at two brokers add up per ISIN everywhere
// except on the Portfolio tab, which lists each broker's line apart.

import type { Account } from "@/lib/money";
import { tr } from "@/lib/i18n";

export type BrokerKind = "buy" | "sell" | "deposit" | "withdrawal" | "interest" | "dividend" | "fee" | "tax";

export type BrokerAccount = Account & { broker: string; broker_label: string };

export type BrokersOverview = {
  brokers: { code: string; label: string }[];
  accounts: BrokerAccount[];
  kinds: BrokerKind[];
};

export type LedgerEntry = {
  id: number;
  date: string;
  /** Positive is money into the broker account. */
  amount: number;
  kind: BrokerKind | "other" | null;
  description: string | null;
  source: "import" | "manual";
  /** Where a manual entry can be deleted; null for an imported one (it comes back with the next import). */
  ref: { table: string; id: number } | null;
};

/** The kinds in the order the form offers them, with their label. */
export function kindLabel(kind: string | null): string {
  switch (kind) {
    case "buy":
      return tr("Buy");
    case "sell":
      return tr("Sell");
    case "deposit":
      return tr("Deposit");
    case "withdrawal":
      return tr("Withdrawal");
    case "interest":
      return tr("Interest");
    case "dividend":
      return tr("Dividend");
    case "fee":
      return tr("Costs");
    case "tax":
      return tr("Tax");
    default:
      return tr("Other");
  }
}

export const KIND_ORDER: BrokerKind[] = ["buy", "sell", "deposit", "withdrawal", "interest", "dividend", "fee", "tax"];

/** Kinds that are about a product (an ISIN), not only about money. */
export const needsIsin = (kind: BrokerKind) => kind === "buy" || kind === "sell" || kind === "dividend";

/**
 * A number of units: "2,8901" and "2.8901" are both 2.8901. Unlike an amount, a
 *  quantity has no thousands separators: a savings plan buys 1.234 units far more
 *  often than anyone types a thousand units with a dot.
 */
export function readQuantity(text: string): number | null {
  const t = (text ?? "").trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) && n > 0 ? n : null;
}
