// The shapes the money screens share, plus the handful of agreements you need to
// know on all three.
//
// **The sign.** Spending is positive, income negative. That comes from the ING
// export (Af/Bij) and runs through the whole backend. Do not flip it here;
// `showAmount` only flips it where a screen asks for it, and then says so.
//
// **Three columns for the category.** `category_auto` is what the rules
// concluded, `category_manual` is what you decided, and `category` is the answer
// — manual if there is one, otherwise auto. A screen always reads `category` and
// always writes to manual.

import { tr } from "@/lib/i18n";

export type Kind = "bank" | "cash" | "manual" | "broker" | "debt";
export type Provider = "ing" | "bunq" | "revolut" | "enablebanking" | "degiro" | "manual";
/** Which stack of your net worth an account falls on. Comes from the backend. */
export type Stack = "bank" | "investments" | "debt";
export type CategoryType = "EXPENSE" | "INCOME" | "INTERNAL";
export type CategoryRole = "spending" | "income" | "bank" | "investments" | "debt" | "own" | "others";
export type Field = "N" | "T" | "A" | "P";
export type Direction = "" | "D" | "C";

export type Account = {
  id: number;
  kind: Kind;
  provider: Provider;
  name: string;
  iban: string | null;
  currency: string;
  active: number;
  created_at: string;
  balance: number | null;
  balance_date: string | null;
  /** "sync", "manual", "schedule" (interest and repayment) or "transfer" (updated with transfers from your other accounts). */
  balance_source: string | null;
  stack: Stack | null;
  /** Interest and required repayment of a debt, or null. */
  schedule: DebtSchedule | null;
  /** First day of the current month: the 1st, or your last salary. */
  period_start: string;
  /** How much the balance changed since then; null without a balance from before that day. */
  since_period_start: number | null;
};

export type DebtSchedule = { interest: number; repayment: number; from_date: string };

export type Balance = {
  id?: number;
  account_id?: number;
  date: string;
  balance: number;
  source: string;
  /** Only for a calculated month (source "schedule"). */
  interest?: number;
  repayment?: number;
};

export type Transaction = {
  id: number;
  account_id: number;
  date: string;
  amount: number;
  name: string;
  counterparty_iban: string | null;
  description: string;
  category_auto: string | null;
  category_manual: string | null;
  /** Where category_auto came from: a rule, learned from your own labels, or a suggestion from Claude. */
  category_source?: "rule" | "learned" | "ai" | null;
  category: string | null;
  type: CategoryType | null;
  /** From an export, entered by hand, or derived (your share of shared costs: no real transaction). */
  source: "import" | "manual" | "derived";
};

export type Category = {
  id: number;
  group_name: string;
  name: string;
  type: CategoryType;
  sort_order: number;
  /** The app itself relies on this name (Salaris, Eigen rekeningen, …): cannot be renamed. */
  is_fixed?: boolean;
  /** The app relies on how this category counts (its type): cannot be changed. */
  type_locked?: boolean;
  /** What it does on Net worth, a step finer than the type (categorization.role_of). */
  role?: CategoryRole;
};

export type Rule = {
  id: number;
  priority: number;
  field: Field;
  pattern: string;
  direction: Direction;
  category: string;
  active: number;
};

export type ImportReport = {
  provider: string;
  account: Account;
  account_created: boolean;
  was_read: number;
  saved: number;
  skipped: number;
  unreadable: { line_number: number; reason: string }[];
};

/** One consent at a bank, from GET /api/connections. */
export type Consent = {
  id: number;
  bank: string;
  country: string;
  status: "waiting" | "active" | "expired" | "error";
  valid_until: string | null;
  last_fetched: string | null;
  error: string | null;
  created_at: string;
  accounts: { id: number; name: string; iban: string | null }[];
};

/** GET /api/connections — never the key itself. */
export type ConnectionStatus = { configured: boolean; app_id: string | null; consents: Consent[] };

/** POST /api/connections/enablebanking/fetch */
export type FetchReport = {
  accounts: number;
  added: number;
  balances: number;
  errors: string[];
  /** Consents that had been fetched shortly before (only with a threshold). */
  skipped: number;
};

/** One file from POST /api/uploads/bank: what it delivered, or why not. */
export type BankImportResult =
  | { file: string; error: string }
  | {
      file: string;
      provider: string;
      /** "balances" is a balance overview: states, no transactions. */
      kind: "transactions" | "balances";
      accounts: {
        account: Account;
        created: boolean;
        saved: number;
        skipped: number;
        balances: number;
      }[];
      was_read: number;
      saved: number;
      skipped: number;
      /** Days with a balance from this file. */
      balances: number;
      unreadable: { line_number: number; reason: string }[];
    };

export type RelabelReport = { labelled: number; unknown: number; coverage: number };

export const KINDS: { value: Kind; label: string }[] = [
  { value: "bank", label: tr("Bank account") },
  { value: "cash", label: tr("Cash") },
  { value: "manual", label: tr("Manual") },
  { value: "broker", label: tr("Broker (outside this app)") },
  // A debt is always stored negative, however you enter it.
  { value: "debt", label: tr("Debt (loan, student debt)") },
];

export const FIELDS: { value: Field; label: string }[] = [
  { value: "N", label: tr("Counterparty name") },
  { value: "T", label: tr("Description and counter account") },
  { value: "A", label: tr("Both") },
  { value: "P", label: tr("Looks like a person's name") },
];

export const DIRECTIONS: { value: Direction; label: string }[] = [
  { value: "", label: tr("Both directions") },
  { value: "D", label: tr("Only out") },
  { value: "C", label: tr("Only in") },
];

/**
 * The amount as a person reads it: an expense as a cost, an income as a receipt.
 * Internally in the database an expense is positive; in a list "−42.50" for a
 * grocery is more understandable than "42.50".
 */
export function showAmount(amount: number): number {
  return -amount;
}

/** GET /api/budget — per group actual next to budget; see budget.py. */
export type BudgetOverview = {
  /** Ascending, "2026-09". */
  months: string[];
  complete: Record<string, boolean>;
  groups: {
    group_name: string;
    /** Per month; null without a budget. */
    budget: number | null;
    /** Over the last complete months; null without a complete month. */
    median: number | null;
    /** Net: refunds on the group already count against it. */
    actual: Record<string, number>;
    /** What came back on the group per month (Tikkie, return), positive; only months with something. */
    back?: Record<string, number>;
    /**
     * Current month, groups with a budget: what you expect to have spent up to today
     *  — recognised fixed costs on their usual day, the rest evenly over the month.
     */
    expected?: number | null;
  }[];
  total: { budget: number | null; actual: Record<string, number> };
  /** The current month, "2026-09". */
  current?: string;
};

/** A counterparty without a category, from GET /api/categories/unknown. */
export type UnknownCounterparty = {
  name: string;
  count: number;
  /** The database's sign convention: spending positive. */
  total: number;
  last: string;
  example: string | null;
  /** A payment processor (Mollie, Adyen, ...): different shops sit behind the name. */
  processor?: boolean;
};

/**
 * The priority of a rule made from one counterparty. 25 is below the fixed costs
 * and above the shop rules: specific enough to win over a general pattern, not
 * so low that it hijacks an INTERNAL rule.
 */
export const RULE_PRIORITY_COUNTERPARTY = 25;

/**
 * The pattern for "everything from this counterparty": the name literally, with
 * the regex characters taken out. Deliberately not smarter: a guessed pattern
 * that is too broad silently labels things you did not mean. Capitals, like the
 * shipped rules; the engine matches case-insensitively anyway.
 */
export function rulePattern(name: string): string {
  return name
    .trim()
    .toUpperCase()
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** An IBAN in readable blocks of four. */
export function showIban(iban: string | null): string {
  return iban ? (iban.match(/.{1,4}/g) ?? [iban]).join(" ") : "–";
}

/** The first day of the month, n months back — for the period buttons. */
export function monthsBack(n: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - n, 1);
  return d.toISOString().slice(0, 10);
}

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * An amount as a person types it, or null if it is not one.
 *
 * "2.000" is two thousand, not two: `Number("2.000")` gave 2, and then there was
 * a balance of two euros where you meant two thousand, without an error. Rules:
 * if there are both dots and commas, the last sign is the decimal. Only a comma
 * is a decimal. Only dots in groups of three ("2.000", "1.250.000") are
 * thousands; otherwise the dot is a decimal ("12.50"). A euro sign, spaces and a
 * leading minus are allowed.
 */
export function readAmount(text: string): number | null {
  let t = (text ?? "").replace(/[€\s]/g, "").replace(/^\+/, "");
  if (!t) return null;
  const min = t.startsWith("-") || t.startsWith("−");
  t = t.replace(/^[-−]/, "");
  if (!/^[\d.,]+$/.test(t)) return null;
  const point = t.lastIndexOf(".");
  const comma = t.lastIndexOf(",");
  if (point >= 0 && comma >= 0) {
    const dec = point > comma ? "." : ",";
    const thousand = dec === "." ? "," : ".";
    t = t.split(thousand).join("").replace(dec, ".");
  } else if (comma >= 0) {
    if ((t.match(/,/g) ?? []).length > 1) return null;
    t = t.replace(",", ".");
  } else if (point >= 0 && /^\d{1,3}(\.\d{3})+$/.test(t)) {
    t = t.split(".").join("");
  }
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? (min ? -n : n) : null;
}
