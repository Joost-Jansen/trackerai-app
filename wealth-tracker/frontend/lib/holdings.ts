// Typed contract for /api/holdings/overview — the Portfolio tab.
//
// Every price-derived field is nullable on purpose: a position whose price
// could not be fetched reports an em dash, never a zero. See
// backend/app/services/holdings_service.py for what each number means.

import type { DaySummary } from "./dashboard";
import { tr } from "@/lib/i18n";

export type AssetType = "share" | "tracker";

export type Holding = {
  isin: string;
  name: string;
  ticker: string | null;
  /** Read off the product name by the backend — DeGiro's export has no type. */
  asset_type: AssetType;
  /** DeGiro's venue code ("EAM", "XET", "TDG"), or null when unknown. */
  exchange: string | null;
  /** The broker that holds this line ("degiro", "trade_republic"). The same fund
   *  at two brokers is two rows, each with that broker's own average price. */
  broker: string;
  /** The broker's name, for display. */
  broker_label: string;
  shares_held: number;
  current_price: number | null;
  previous_close: number | null;
  current_value: number | null;
  /** GAK: average price paid per share, transaction costs excluded, so it is
   *  directly comparable to current_price. */
  avg_cost_ex_costs: number | null;
  invested_ex_costs: number;
  /** Every euro ever paid on a buy of this ISIN, costs included — the base
   *  Totale W/V % is measured against. */
  invested_gross: number;
  realized_eur: number;
  dividends_eur: number;
  costs_eur: number;
  unrealized_eur: number | null;
  unrealized_pct: number | null;
  /** Unrealized + realized + dividends - all transaction costs. */
  total_eur: number | null;
  total_pct: number | null;
  day_eur: number | null;
  day_pct: number | null;
  /**
   * Where the price of *this* position comes from: its own exchange (Tradegate,
   *  last trade) or the fund's Yahoo price. Null without a price.
   */
  price_provider: "yahoo" | "tradegate" | null;
  price_fetched_at: string | null;
};

export type HoldingsTotals = {
  value: number;
  num_positions: number;
  prices_available: boolean;
  total: { eur: number; pct: number | null; complete: boolean };
  unrealized: { eur: number; pct: number | null };
  realized_eur: number;
  dividends_eur: number;
  costs_eur: number;
  /** Per broker: value of its open lines and every cost it ever charged. */
  by_broker: BrokerTotal[];
  day: DaySummary | null;
};

export type BrokerTotal = {
  broker: string;
  label: string;
  value: number;
  num_positions: number;
  /** All transaction costs at this broker, closed positions included. */
  costs_eur: number;
  prices_available: boolean;
};

export type HoldingsOverview = {
  positions: Holding[];
  totals: HoldingsTotals;
  latest_price_fetch: string | null;
  /** The oldest quote counting towards these totals — see the dashboard's. */
  oldest_price_fetch: string | null;
};

// ---------------------------------------------------------------------------
// One position, one click deeper — /api/holdings/{isin}
// ---------------------------------------------------------------------------

/** The position itself plus the identity a page needs above it. `position` is
 *  byte-for-byte the row the overview lists, so the two screens cannot print a
 *  different GAK for the same holding. */
export type PositionDetail = {
  position: Holding;
  /** The Yahoo symbol its price comes from; null when none ever resolved. */
  ticker: string | null;
  /** The quote's currency. Non-EUR means every euro figure on the row is
   *  absent — the backend refuses to mix currencies into a EUR basis. */
  currency: string | null;
  /**
   * The currency the ticker trades in, which the price above the chart and
   *  the chart itself are in. USD for TSM, even though `currency` (the stored,
   *  converted quote) says EUR; every amount on `position` stays in euros.
   */
  quote_currency: string;
  /** The price in `quote_currency`. Null when it cannot be given exactly. */
  quote_price: number | null;
  price_fetched_at: string | null;
  /**
   * Where the price above comes from. `venue_fallback` is true when that
   *  listing is another exchange's than the one the position is held on — a
   *  Tradegate position priced off XETRA. Null without a ticker.
   */
  price_source: PriceSource | null;
  /** Whether /api/holdings/{isin}/tradegate has a quote to offer: only for a
   *  position held on Tradegate (beurs TDG). */
  tradegate_quote: boolean;
  first_buy: string | null;
  last_trade: string | null;
  num_transactions: number;
  /** True on a weekend, a holiday or before the opening bell — `position`'s
   *  day_pct is zero then, and the line beside it says why. */
  market_closed: boolean;
  /** The same ISIN held on another exchange: a separate position, with its own
   *  average price. Empty in the normal case. */
  other_venues: {
    exchange: string | null;
    broker: string;
    broker_label: string;
    shares_held: number;
    current_value: number | null;
  }[];
};

export type PriceSource = {
  provider: string;
  ticker: string;
  /** "XETRA", "Euronext Amsterdam", "VS" — null for a suffix the backend does not know. */
  listing_venue: string | null;
  position_venue: string | null;
  venue_fallback: boolean;
};

/**
 * Tradegate's own price — /api/holdings/{isin}/tradegate.
 *
 *  `last`, `bid` and `ask` are three separate numbers; if `last` is missing, it
 *  is null and is *not* derived from bid or ask. Tradegate provides no time of
 *  the quote: `quote_time` is always null, `fetched_at` is only the moment of
 *  fetching.
 */
export type TradegateQuoteOk = {
  status: "ok";
  isin: string;
  venue: string;
  venue_name: string;
  source: string;
  currency: string;
  last: number | null;
  bid: number | null;
  ask: number | null;
  previous_close: number | null;
  high: number | null;
  low: number | null;
  /** Tradegate's own change of `last` against the previous close, in %. */
  change_pct: number | null;
  volume: number | null;
  turnover: number | null;
  executions: number | null;
  trading_state: string;
  halted: boolean;
  quote_time: null;
  fetched_at: string;
  session_open: boolean;
  traded_today: boolean | null;
  /** The last attempt failed; this is a price fetched earlier. */
  stale: boolean;
  error: string | null;
  age_seconds: number;
};

export type TradegateQuote =
  | TradegateQuoteOk
  | {
      status: "unavailable" | "refused" | "no_data" | "invalid_isin" | "disabled" | "not_applicable";
      isin: string;
      message: string;
      error?: string | null;
    };

/**
 * What is *in* a fund: the largest holdings, the sectors and the countries.
 *
 *  Percentages are of the fund; `value` is your money — the weight of that item
 *  times the value of your position, so the amounts add up to the value at the
 *  top of the same page.
 *
 *  `source` is null when there is nothing to show: a share, or a fund whose
 *  issuer publishes no readable holdings list. Then the lists are empty and the
 *  page says so in one sentence.
 */
export type FundBreakdown = {
  /** "Vanguard (issuer)", "Index proxy (iShares AEX file)", of null. */
  source: string | null;
  quality: "exact" | "proxy" | null;
  /** Companies, not rows: two share classes of one company are one. */
  num_holdings: number;
  /** What percentage of the fund is in the ten largest holdings. */
  top10_pct: number | null;
  /**
   * The twenty largest, descending. The page shows ten and keeps ten behind an
   *  expand.
   */
  holdings: { name: string; symbol: string | null; pct: number; value: number | null }[];
  sectors: { name: string; pct: number }[];
  countries: { name: string; pct: number }[];
  /** *All* countries, also those that do not make it above the cut-off in `countries`. */
  num_countries: number;
};

/**
 * A close on the product's own price line. `c` is the price in the quote's
 *  currency — nothing here is multiplied by what you hold.
 */
export type PricePoint = { d: string; c: number };

export type PriceHistory = { points: PricePoint[] };

/** Today per five minutes. The first point is the previous session's close, and
 *  `prev_close` repeats it as the level the day is measured against. */
export type PriceIntraday = { points: PricePoint[]; prev_close: number | null };

/** What a price chart is being asked about: one point under the cursor, or the
 *  stretch between two fingers. Rendered by the card's header rather than by a
 *  tooltip — see PriceChart for why. */
export type PriceProbe =
  { kind: "point"; point: PricePoint } | ({ kind: "span"; a: PricePoint; b: PricePoint } & ReturnType<typeof priceChange>);

/** The move between two closes, in currency and percent.
 *
 *  Plain price arithmetic, and deliberately so: this is the one chart in the
 *  app with no cash flows in it, so unlike the portfolio's value line there is
 *  nothing to split into "what you added" and "what the market did". Null
 *  percent only when the earlier close is zero, which no real quote is. */
export function priceChange(a: PricePoint, b: PricePoint) {
  return { delta: b.c - a.c, pct: a.c > 0 ? (b.c / a.c - 1) * 100 : null };
}

export type Mode = "day" | "all";

/** The result a row shows in the active mode, as (euro, percent). */
export function resultFor(h: Holding, mode: Mode): [number | null, number | null] {
  return mode === "day" ? [h.day_eur, h.day_pct] : [h.total_eur, h.total_pct];
}

/** Section order and headings, following DeGiro's own grouping. */
export const GROUPS: { type: AssetType; label: string }[] = [
  { type: "share", label: tr("Shares") },
  { type: "tracker", label: tr("Trackers (ETF's)") },
];

/** Rows per section, in the order given, skipping sections with nothing in
 *  them — a portfolio of only funds should not show an empty "Aandelen". */
export function groupHoldings(rows: Holding[]): { label: string; rows: Holding[] }[] {
  return GROUPS.map((g) => ({
    label: g.label,
    rows: rows.filter((h) => h.asset_type === g.type),
  })).filter((g) => g.rows.length > 0);
}
