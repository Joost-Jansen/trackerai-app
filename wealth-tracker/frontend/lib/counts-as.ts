// Where a transaction counts on Net worth, for the "Counts as" filter on
// Transactions: one answer per transaction, so the list behind a number holds
// exactly the transactions in it and nothing else.
//
// Built on the role the categories API sends (categorization.role_of), so it
// follows the backend instead of a second set of rules. An account outside net
// worth comes first: whatever its category, nothing on it counts (net_worth.series
// only uses active accounts with at least one balance).

import type { Account, CategoryRole, Transaction } from "@/lib/money";
import { tr } from "@/lib/i18n";

export type CountsAs = "saved" | "bank" | "friends" | "investments" | "debt" | "own" | "unlabelled" | "outside";

/** The order of the filter, and what each choice is called there. */
export const COUNTS_AS: { code: CountsAs; label: () => string; hint: () => string }[] = [
  { code: "saved", label: () => tr("Saved"), hint: () => tr("Spending and income") },
  { code: "bank", label: () => tr("Bank & cash"), hint: () => tr("Internal, with no other side elsewhere in net worth") },
  { code: "friends", label: () => tr("Money of others"), hint: () => tr("For or from friends, not your own money") },
  { code: "investments", label: () => tr("To investments"), hint: () => tr("Net zero: it reappears with your broker") },
  { code: "debt", label: () => tr("Debt repayment"), hint: () => tr("Net zero: it reappears as less debt") },
  { code: "own", label: () => tr("Between own accounts"), hint: () => tr("Net zero, savings included") },
  { code: "unlabelled", label: () => tr("No category"), hint: () => tr("Counts in Bank & cash until it has a category") },
  { code: "outside", label: () => tr("Not counted"), hint: () => tr("On an account outside net worth") },
];

const BY_ROLE: Record<CategoryRole, CountsAs> = {
  spending: "saved",
  income: "saved",
  bank: "bank",
  others: "friends",
  investments: "investments",
  debt: "debt",
  own: "own",
};

/** Whether an account takes part in net worth: active, of a kind net worth knows, with a balance. */
export const takesPart = (a: Account | undefined) =>
  Boolean(a && a.active && a.stack && a.balance !== null);

/** A classifier for transactions, from the category roles and the accounts. */
export function countsAsOf(roleOf: Map<string, CategoryRole | undefined>, accounts: Account[]) {
  const inNetWorth = new Set(accounts.filter(takesPart).map((a) => a.id));
  // Accounts not loaded yet: judge by category only, rather than call everything outside.
  const known = accounts.length > 0;
  return (t: Transaction): CountsAs => {
    if (known && !inNetWorth.has(t.account_id)) return "outside";
    const role = t.category ? roleOf.get(t.category) : undefined;
    // No category: Net worth counts it as unlabelled, in Bank & cash.
    return role ? BY_ROLE[role] : "unlabelled";
  };
}
