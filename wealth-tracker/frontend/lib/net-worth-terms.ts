// What each part of a change in net worth means, in one place: the month table's
// column headers and the cards above the chart explain themselves with these.

import { tr } from "@/lib/i18n";

export const TERMS = {
  netAtEnd: () => tr("Your net worth on the last day of the month: investments plus bank & cash, minus debt."),
  change: () => tr("How much your net worth changed in the month. It is always Saved + Market + Bank & cash + Debt."),
  saved: () => tr("Income minus spending, as on the Spending page. Transfers between your own accounts, to investments and in “Niet meetellen” don't count here. Click a number to see its transactions; Categories shows which category counts where."),
  market: () => tr("What your holdings did by themselves: price changes and dividend. Buying, selling and moving money to or from your broker don't count. It comes from your holdings, not from transactions, so there is nothing to click through to."),
  bank: () => tr("What moved on your bank accounts and your broker's cash apart from saving and investing: gifts, money for and from friends, transfers to accounts outside your net worth, and balances that don't match the transactions. Click a number to see its transactions, or the month for the details."),
  debt: () => tr("How your own debts changed: a repayment makes it positive, interest negative. Money you hold for friends isn't included."),
};
