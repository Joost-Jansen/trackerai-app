// Typed contracts for /api/dashboard/* — one file, so a card and its endpoint
// can never quietly disagree about a field name.

import { tr } from "./i18n/tr";

export type DaySummary = {
  delta_eur: number;
  pct: number;
  complete: boolean;
  /** The oldest quote this figure was built from. */
  as_of: string | null;
  /**
   * True when that quote has missed a market close it should have been
   *  refreshed for — i.e. the move labelled "today" is not today's. Not a
   *  reason to hide the chip, a reason to mark it.
   */
  stale: boolean;
  /**
   * True on a weekend, a holiday, or before the opening bell: the exchange has
   *  not traded today, so `delta_eur` and `pct` are zero — which is what the
   *  portfolio really did today. The label says "market closed" beside it, and
   *  ignores `stale`: there is nothing to be behind on.
   */
  market_closed: boolean;
};

export type Summary = {
  summary: {
    net_investment: number;
    total_value: number;
    total_gain: number;
    unrealized_gain: number;
    unrealized_return_pct: number;
    realized_gain: number;
    total_dividends: number;
    /** Every transaction cost ever charged, positive. Already deducted inside
     *  unrealized_gain and realized_gain — subtract it only from the *_ex_costs
     *  pair below, never from these two. */
    total_costs: number;
    /** unrealized_gain and realized_gain with the costs lifted back out, so
     *  the hero's breakdown is a real sum:
     *    ..._ex_costs + ..._ex_costs + total_dividends - total_costs
     *      = total_gain + total_dividends
     *  Served by the dashboard router, not by calculate_portfolio_summary. */
    unrealized_gain_ex_costs: number;
    realized_gain_ex_costs: number;
    /** null once more has been taken out than ever went in — the denominator
     *  stops meaning "what you put in" there, and the sign flips. */
    total_return_pct: number | null;
    num_positions: number;
    prices_available: boolean;
  };
  latest_price_fetch: string | null;
  /** The oldest quote counting towards the totals — what they are really only
   *  as current as. `latest_price_fetch` is the newest and flatters the set. */
  oldest_price_fetch: string | null;
  num_positions: number;
  /** Open positions without any price. Non-empty means prices_available is
   *  false and every total above is left out ("—"); the dashboard names them. */
  unpriced: { isin: string; name: string }[];
  day: DaySummary | null;
};

export type SparklinePoint = { d: string; v: number };

/** A day on the own-portfolio value chart, all in EUR. */
export type ValuePoint = { d: string; invested: number; value: number; value_divs: number };

/**
 * A holding whose line is a stand-in rather than a measurement, and what it
 *  stood in with ("huidige price" / "aankoopprijs").
 */
export type EstimatedHolding = { isin: string; name: string; base: string };

export type ValueHistory = {
  points: ValuePoint[];
  estimated: EstimatedHolding[];
  /** True when the closes could not be fetched at all. The card says so rather
   *  than drawing every past day at today's price, which produced a perfectly
   *  flat line that reads like a portfolio that simply did not move. */
  unavailable?: boolean;
};

/**
 * The card's header figures for a range: end value, euro return, contributions
 *  and return %.
 *
 *  *slice* must be the daily points the chart draws (never the intraday bars —
 *  the reasoning below is about days), and *all* the full daily series.
 *
 *  The baseline is `slice[0]`, the first point drawn, so the number and the line
 *  always describe the same window. It used to be the point *before* the window,
 *  which measured a day more than was drawn: harmless over a month, but on 1D —
 *  where sliceByRange yields yesterday and today — it doubled the window, and a
 *  portfolio that fell yesterday and rose today showed a rising line over a
 *  negative return.
 *
 *  Null baseline when the slice reaches inception ("All", or any range older
 *  than the portfolio): with no earlier point the first purchase must count as
 *  inleg rather than as return, which is what keeps those totals equal to the
 *  hero's.
 */
export function rangeBreakdown(all: ValuePoint[], slice: ValuePoint[]) {
  if (all.length < 2 || slice.length < 2) return null;
  // The slice's own end, so a window dragged out on the chart that stops before
  // today measures up to where it stops. For the period buttons that is the last day.
  const e = slice[slice.length - 1];
  const base = slice[0].d > all[0].d ? slice[0] : null;
  const contrib = e.invested - (base ? base.invested : 0);
  const gain = e.value_divs - (base ? base.value_divs : 0) - contrib;
  // % return over the capital that was in play: what the window opened with plus
  // what you put in during it. Since inception that reduces to total money
  // invested — the same basis as the hero's "% sinds start" — and over a
  // sub-range it stops a window that opens on a near-empty portfolio from
  // reporting four-digit percentages. See splitChange for the caveat.
  //
  // value_divs on both sides of the fraction, never value below and value_divs
  // above: the gain is measured on the with-dividends series, so the base has
  // to be too. Dividends banked before the window opened are capital that was
  // already at work, and leaving them out of the denominator alone inflated the
  // percentage — YTD read 16,5% where the same window is 16,2%. Same
  // arithmetic, same reasoning and the same fix as returns_service.build, whose
  // "Wat je geld deed" row is this number on another tab.
  const denom = (base ? base.value_divs : 0) + Math.max(contrib, 0);
  return { end: e.value, gain, contrib, pct: denom > 0 ? (gain / denom) * 100 : null };
}

/** What the chart is being asked about right now: one point under the cursor, or
 *  the stretch between two fingers. The card's header renders this instead of
 *  its own figures while it is set, which is how the reading stays off the
 *  drawing — a tooltip floating over a 150px-high chart covers the line it is
 *  describing. */
export type Probe =
  { kind: "point"; point: ValuePoint } | ({ kind: "span"; a: ValuePoint; b: ValuePoint } & ReturnType<typeof splitChange>);

/** What happened between two points on the value chart, split into the part you
 *  paid for and the part the market did.
 *
 *  Same convention as the card's header (valueBreakdown in the dashboard page):
 *  `invested` only moves on a deposit or a withdrawal, so Δinvested *is* the
 *  contribution, and whatever is left of Δvalue is market movement. Those two
 *  add up to Δvalue exactly — which is the point, because a €701 jump that was
 *  €649 of fresh money is not a 5% return.
 *
 *  Dividends sit outside that sum on purpose: cash paid out is on the
 *  value+dividends line, not on the value line the two points were picked from.
 *  Which is also why `employed` below stays on `value` where rangeBreakdown's
 *  denominator uses `value_divs`: each fraction measures its own line, and it is
 *  mixing the two that inflates a percentage. Not a divergence between them —
 *  the same rule applied to two different numerators.
 *
 *  `pct` is market movement over the capital that was in play: the value you
 *  started with *plus* what you added during the window. The starting value
 *  alone blows up whenever a window opens on a near-empty portfolio — selecting
 *  Jan 2023 to Jun 2026 on a portfolio worth €100,87 that day, after €10.225,90
 *  of later deposits, reported +2.808,60%. Over the same stretch the honest
 *  answer is +27,43%.
 *
 *  It is an approximation: money that arrived on the last day counts as fully at
 *  work, so a late deposit understates the return the way an early one used to
 *  overstate it. The Benchmarks tab has the time-weighted return, which is the
 *  version that survives cash flows properly. Null when no capital was at work.
 */
export function splitChange(a: ValuePoint, b: ValuePoint) {
  const delta = b.value - a.value;
  const contrib = b.invested - a.invested;
  const market = delta - contrib;
  const dividends = b.value_divs - b.value - (a.value_divs - a.value);
  const employed = a.value + Math.max(contrib, 0);
  return {
    delta,
    contrib,
    market,
    dividends,
    pct: employed > 0 ? (market / employed) * 100 : null,
    /** Below half a cent the two rows are the same number twice. */
    split: Math.abs(contrib) >= 0.005,
  };
}

/** Today's value per 5 minutes, for the 1D range. `d` carries a UTC offset, so
 *  the browser renders the bars in the reader's own timezone. `prev_close` is
 *  the portfolio's worth at the previous session's close — what the day is
 *  measured against. Both are empty on a holiday or a failed download. */
export type IntradayPoint = { d: string; value: number };

/** `anchored` is false when the backend could not pin both endpoints to the
 *  chip's two prices (a position it cannot value, or a price cache that is not
 *  from today). The line is then the minute feed's own answer to a question
 *  that has exactly one, so the card must not draw it — it falls back to the
 *  daily series, as it does on a holiday. */
export type Intraday = { points: IntradayPoint[]; prev_close: number | null; anchored: boolean };

/** The intraday bars as full ValuePoints, so the card can draw them with the
 *  same three series as any other range.
 *
 *  Both extra series are genuinely flat within a day: `invested` only moves on a
 *  transaction (which the intraday series holds at today's total by
 *  construction — see charts.portfolio_intraday_series), and the gap between
 *  value and value+dividends is cumulative dividend income, which only moves on
 *  a payout. So the last daily point supplies both offsets exactly. */
export function intradayAsValuePoints(bars: IntradayPoint[], lastDaily: ValuePoint | null): ValuePoint[] {
  const dividends = lastDaily ? lastDaily.value_divs - lastDaily.value : 0;
  const invested = lastDaily ? lastDaily.invested : 0;
  return bars.map((b) => ({
    d: b.d,
    invested,
    value: b.value,
    value_divs: b.value + dividends,
  }));
}

export type AllocationSlice = { name: string; pct: number };

export type Allocation = {
  sector: AllocationSlice[];
  region: AllocationSlice[];
  excluded_pct: number;
  num_positions: number;
};

export type DividendForecastItem = {
  isin: string;
  name: string | null;
  /**
   * Expected date. For a "estimate" this is schedule arithmetic — the UI must
   * only ever show it at month precision (part + month), never as an exact
   * day; only an "official" entry carries a real calendar date.
   */
  date: string;
  month: string; // "2026-09"
  part: Part;
  expected_eur: number | null;
  cadence: string | null;
  confidence: "high" | "medium" | "low";
  source: "estimate" | "official";
};

/** Where in the month an estimated payment falls: the honest precision of an estimate. */
export type Part = "early" | "mid" | "late";
export const partLabel = (part: string): string =>
  part === "early" ? tr("early") : part === "mid" ? tr("mid") : part === "late" ? tr("late") : part;

/** A payer's rhythm as the backend names it (monthly, quarterly, semiannual, annual). */
export const cadenceLabel = (cadence: string): string =>
  ({ monthly: tr("monthly"), quarterly: tr("quarterly"), semiannual: tr("semiannual"), annual: tr("annual") })[cadence] ?? cadence;

export type DividendStats = {
  this_month: number;
  this_year: number;
  outlook: { upcoming: DividendForecastItem[]; rest_of_year_eur: number };
};

export type Mover = {
  isin: string;
  name: string;
  ticker: string | null;
  day_delta_eur: number;
  day_pct: number;
};

export type Movers = { top: Mover | null; bottom: Mover | null };

export type SinceVisit = {
  last_seen_at: string;
  value_then: number;
  value_delta: number;
  dividends: { count: number; total_eur: number };
} | null;

export type NewsLabel = "Earnings" | "Dividend" | "Analyst" | "M&A" | "World" | "Macro";

export type NewsItem = {
  id: string;
  title: string;
  summary?: string | null;
  publisher: string | null;
  link: string | null;
  published: string | null;
  ticker: string | null;
  holding: string | null;
  label: NewsLabel;
  sentiment?: number | null;
  source_api?: "finnhub" | "alphavantage";
};

// The five biggest look-through holdings inside the user's ETFs, as ranked by
// the Allocation tab; returned alongside the etf-top feed so the page can name
// which companies the headlines are about.
export type EtfTopStock = {
  symbol: string | null;
  name: string | null;
};

export type ExDividend = {
  isin: string;
  ticker: string;
  name: string | null;
  ex_date: string;
  pay_date: string | null;
  estimate_eur: number | null;
};

export type PricesStatus = {
  last_updated: string | null;
  /**
   * The *oldest* quote still counting towards the totals. `last_updated` is
   *  the newest, so on a partly-failed refresh it reads "just now" while most
   *  of the portfolio is days behind; this is the number that says so.
   */
  oldest_price: string | null;
  count: number;
  last_import: string | null;
};

/** What POST /api/prices/refresh achieved. `updated_count` is the number of
 *  prices actually stored — it used to be the size of the whole cache, so a
 *  round that fetched nothing still answered with a full count. */
export type PricesRefresh = {
  updated_count: number;
  failed: { isin: string; name: string }[];
  skipped: number;
  complete: boolean;
};

// ---------------------------------------------------------------------------
// Ranges: the period buttons, as a slice of any date-keyed series. Pure, and
// tested through node in tests/test_dashboard_helpers.py alongside the figures
// the card prints from them.
//
// There used to be a rebase() here as well, turning a TWR index into percent
// for a portfolio-vs-MSCI-World card on the dashboard. The card is gone (TWR
// belongs on the Returns tab, beside the paragraph that makes it readable),
// and with it the helper and its endpoint.
// ---------------------------------------------------------------------------

// 3Y and 5Y were only on the Returns tab, where returns_service has had them for
// years. That was a difference without reason: a five-year portfolio jumped here
// from "1Y" to "All", and exactly in between lies the question whether a bad
// year was bad or just a year.
export const RANGES = ["1D", "1W", "1M", "3M", "YTD", "1Y", "3Y", "5Y", "All"] as const;
export type Range = (typeof RANGES)[number];

/** *d* shifted by whole calendar months, clamped to the target month's length.
 *
 *  setMonth() alone overflows instead of clamping: on 31 March it hands back
 *  3 March ("31 February"), so "1M" would then measure a month and three days.
 *  Clamping to the 28th is the reading a person gives it, and — because
 *  returns_service._range_starts does the identical arithmetic — it is what
 *  keeps the two tabs measuring one window per label. */
function addMonths(d: Date, months: number): Date {
  const day = d.getDate();
  const out = new Date(d);
  out.setDate(1);
  out.setMonth(out.getMonth() + months);
  const lastOfMonth = new Date(out.getFullYear(), out.getMonth() + 1, 0).getDate();
  out.setDate(Math.min(day, lastOfMonth));
  return out;
}

function rangeStart(last: Date, range: Range): Date | null {
  const d = new Date(last);
  switch (range) {
    case "1D":
      d.setDate(d.getDate() - 1);
      return d;
    case "1W":
      d.setDate(d.getDate() - 7);
      return d;
    case "1M":
      return addMonths(d, -1);
    case "3M":
      return addMonths(d, -3);
    case "YTD":
      return new Date(last.getFullYear(), 0, 1);
    case "1Y":
      // Twelve months, not setFullYear(-1): on 29 February that one overflows
      // to 1 March of the year before, the same off-by-a-day as setMonth.
      return addMonths(d, -12);
    case "3Y":
      return addMonths(d, -36);
    case "5Y":
      return addMonths(d, -60);
    case "All":
      return null;
  }
}

/**
 * `d` as YYYY-MM-DD in local time — toISOString() would convert to UTC here and
 *  fall back a day in Dutch summer time.
 */
function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * The period buttons this series can really draw.
 *
 * A window that starts before your first day gives exactly the same line as
 * "All". Without this filter a two-year portfolio had three buttons side by side
 * — 3Y, 5Y and All — that all did the same, and then the button looks broken
 * instead of empty. The same rule as returns_service._range_starts on the
 * Returns tab, which skips such a window too.
 *
 * "All" always stays, also with an empty series: there must be something to
 * point at.
 */
export function availableRanges(points: { d: string }[]): Range[] {
  if (points.length < 2) return ["All"];
  const first = points[0].d;
  const last = new Date(points[points.length - 1].d);
  return RANGES.filter((r) => {
    const start = rangeStart(last, r);
    return start === null || iso(start) > first;
  });
}

/**
 * Slice any date-keyed series to a range. The dashboard's value chart and the
 *  position page's price chart share this — the only thing a range means is
 *  "points since a start date", independent of what each point carries.
 *
 *  The cutoffs are calendar arithmetic (see addMonths), matching
 *  returns_service._months_before to the day, so a "3M" here and a "3M" on the
 *  Returns tab are the same three months. They were not: 91 days against a
 *  quarter put the two windows a day apart on most dates, and the same button
 *  showed +8,5% on one tab and +6,9% on the other.
 */
export function sliceByRange<T extends { d: string }>(points: T[], range: Range): T[] {
  if (points.length === 0) return points;
  const last = new Date(points[points.length - 1].d);
  const start = rangeStart(last, range);
  if (!start) return points;
  const from = iso(start);
  const sliced = points.filter((p) => p.d >= from);
  // A range needs two points to draw a line; fall back to the last two days
  // (matters for 1D over a weekend).
  return sliced.length >= 2 ? sliced : points.slice(-2);
}
