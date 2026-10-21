import type { Transaction } from "./money";

/** For the ranking: only real variable payments to third parties. */
export function variableSpending(rows: Transaction[], isFixed: (name: string) => boolean, ownIbans: Set<string>): Transaction[] {
  return rows.filter(
    (r) =>
      r.type === "EXPENSE" &&
      r.amount > 0 &&
      !isFixed(r.name) &&
      !ownIbans.has((r.counterparty_iban ?? "").replace(/\s/g, "").toUpperCase()),
  );
}
