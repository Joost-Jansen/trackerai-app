// Splitting a change in net worth into where it came from.
//
//   change = saved + market + bank & cash + debt
//
//   saved        income minus spending, from the bank transactions
//   market       measured on the holdings themselves: their change in value,
//                minus what went into them (buys minus sells), plus dividend.
//                Money moved between the bank and the broker is never a gain or a
//                loss here, however the bank transfer was labelled. Without that
//                data (an older answer) it falls back to the investments' change
//                minus the transfers labelled as investing.
//   debt         the change in your own debts: repayments make it positive,
//                interest negative. Money you hold for friends is left out.
//   bank & cash  what is left. It is told apart further in `detail`:
//                  friends      money advanced for friends that is not back yet;
//                               with a category set for shared costs (Settings) this
//                               is your own share and moves to `saved` as spending
//                  unlabelled   transactions without a category
//                  corrections  balances that don't follow the transactions:
//                               a manual balance, a missing export
//                  transfers    the rest: repayments leaving the bank, transfers
//                               to accounts outside your net worth, cash
//                  listed       what the transactions behind the Bank & cash link
//                               add up to: the categories that land there, those
//                               without a category, and friends' money unless it
//                               counts as spending. Null with an older answer.
//
// The last part is a remainder on purpose, so everything always adds up to the
// change and a gap in the data shows up instead of disappearing.

export type Flow = {
  d: string;
  saved: number;
  to_investments: number;
  others?: number;
  unlabelled?: number;
  bank_flow?: number;
  bank_tx?: number;
};

type Balance = {
  d: string;
  investments: number;
  bank: number;
  debt: number;
  net: number;
  held?: number;
  portfolio?: number;
  portfolio_invested?: number;
  portfolio_dividends?: number;
};

export type Bridge = {
  change: number;
  /** All null when the bank data does not cover the period. */
  saved: number | null;
  market: number | null;
  bank: number | null;
  debt: number | null;
  detail: { friends: number; unlabelled: number; corrections: number; transfers: number; listed: number | null } | null;
  /** Your own share of shared costs counted as spending in `saved` (negative = spent). */
  shared: number;
};

/**
 * `sharedAsSpending`: your own share of a "Niet meetellen" pot counts as spending.
 * The friends part of Bank & cash is exactly minus the change in that share (see
 * shared_costs.py), so it moves to Saved as a whole.
 */
export function bridge(from: Balance, to: Balance, flows: Flow[], sharedAsSpending = false): Bridge {
  const change = to.net - from.net;
  const debt = ownDebt(from, to);
  // Before the first bank transaction there is nothing to split with.
  if (!flows.length || from.d < dayBefore(flows[0].d)) {
    return { change, saved: null, market: null, bank: null, debt: null, detail: null, shared: 0 };
  }
  let saved = 0,
    deposited = 0,
    others = 0,
    unlabelled = 0,
    bankFlow = 0,
    bankTx = 0;
  for (const f of flows) {
    if (f.d > from.d && f.d <= to.d) {
      saved += f.saved;
      deposited += f.to_investments;
      others += f.others ?? 0;
      unlabelled += f.unlabelled ?? 0;
      bankFlow += f.bank_flow ?? 0;
      bankTx += f.bank_tx ?? 0;
    }
  }
  const market = onHoldings(from) && onHoldings(to) ? holdingsMarket(from, to) : to.investments - from.investments - deposited;
  let friends = (to.held ?? 0) - (from.held ?? 0) + others;
  const shared = sharedAsSpending ? friends : 0;
  saved += shared;
  if (sharedAsSpending) friends = 0;
  const bank = change - saved - market - debt;
  const corrections = to.bank - from.bank - bankFlow;
  const transfers = bank - friends - unlabelled - corrections;
  const listed = flows[0].bank_tx !== undefined ? bankTx + unlabelled + (sharedAsSpending ? 0 : others) : null;
  return { change, saved, market, bank, debt, detail: { friends, unlabelled, corrections, transfers, listed }, shared };
}

/** The change in your own debts: repayments positive, interest negative; money held for friends left out. */
function ownDebt(from: Balance, to: Balance): number {
  return to.debt - (to.held ?? 0) - (from.debt - (from.held ?? 0));
}

const onHoldings = (p: Balance) => p.portfolio !== undefined && p.portfolio_invested !== undefined;

/** What the holdings did: their change in value, minus what went into them, plus dividend. */
function holdingsMarket(from: Balance, to: Balance): number {
  return (
    to.portfolio! -
    from.portfolio! -
    (to.portfolio_invested! - from.portfolio_invested!) +
    ((to.portfolio_dividends ?? 0) - (from.portfolio_dividends ?? 0))
  );
}

function dayBefore(d: string): string {
  const t = new Date(`${d}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() - 1);
  return t.toISOString().slice(0, 10);
}

/**
 * Where the change came from, so far: one point of `bridgeSeries`. `unsplit` is what saving and bank & cash added
 * together before the bank data starts (nothing to tell them apart with); `banked` says whether this point is in
 * the bank data, so `saved` and `bank` mean something.
 */
export type SourcePoint = {
  d: string;
  change: number;
  saved: number;
  market: number;
  bank: number;
  debt: number;
  unsplit: number;
  banked: boolean;
};

/**
 * The split of `bridge`, at every point: from the first point to each later one. That is how much saving, the
 * market, bank & cash and debt have added to net worth since the start, day by day; at the last point it is exactly
 * what the tiles above the chart show.
 *
 * Market (on the holdings) and debt (from the balances) need no bank data, so they run from the start even when the
 * bank data starts later. Saving and bank & cash do need it: until then their sum is `unsplit`, which stays where it
 * was once the bank data starts, and from there `bridge` splits the rest. Null without any bank data, or when the
 * points before it lack the holdings to measure the market on.
 */
export function bridgeSeries(points: Balance[], flows: Flow[], sharedAsSpending = false): SourcePoint[] | null {
  if (points.length < 2 || !flows.length) return null;
  const covered = dayBefore(flows[0].d);
  let k = points.findIndex((p) => p.d >= covered);
  if (k < 0) k = points.length - 1; // the bank data starts after the last point: nothing is split
  if (k > 0 && !points.slice(0, k + 1).every(onHoldings)) return null;
  const from = points[0];
  // Before the bank data: market and debt measured directly, the rest unsplit.
  const early = (to: Balance): SourcePoint => {
    const change = to.net - from.net;
    const market = k > 0 ? holdingsMarket(from, to) : 0;
    const debt = ownDebt(from, to);
    return { d: to.d, change, saved: 0, market, bank: 0, debt, unsplit: change - market - debt, banked: false };
  };
  const out = points.slice(0, k + 1).map(early);
  out[k] = { ...out[k], banked: true };
  const base = out[k];
  for (const to of points.slice(k + 1)) {
    const b = bridge(points[k], to, flows, sharedAsSpending);
    out.push({
      d: to.d,
      change: base.change + b.change,
      saved: b.saved!,
      market: base.market + b.market!,
      bank: b.bank!,
      debt: base.debt + b.debt!,
      unsplit: base.unsplit,
      banked: true,
    });
  }
  return out;
}
