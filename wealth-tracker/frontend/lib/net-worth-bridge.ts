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
  const debt = to.debt - (to.held ?? 0) - (from.debt - (from.held ?? 0));
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
  const onHoldings =
    from.portfolio_invested !== undefined &&
    to.portfolio_invested !== undefined &&
    from.portfolio !== undefined &&
    to.portfolio !== undefined;
  const market = onHoldings
    ? to.portfolio! -
      from.portfolio! -
      (to.portfolio_invested! - from.portfolio_invested!) +
      ((to.portfolio_dividends ?? 0) - (from.portfolio_dividends ?? 0))
    : to.investments - from.investments - deposited;
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

function dayBefore(d: string): string {
  const t = new Date(`${d}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() - 1);
  return t.toISOString().slice(0, 10);
}
