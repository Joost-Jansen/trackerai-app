"use client";

// A category's type, shown as where it counts on Net worth, and changeable in
// place: spending and income make up Saved, internal categories land in Bank &
// cash. Market and Debt have no categories: they come from your holdings and
// your debt balances. Categories the app relies on keep their type.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Category, CategoryRole, CategoryType } from "@/lib/money";
import { tr } from "@/lib/i18n";

export const COLUMN_OF: Record<CategoryType, () => string> = {
  EXPENSE: () => tr("Saved, as spending"),
  INCOME: () => tr("Saved, as income"),
  INTERNAL: () => tr("Bank & cash"),
};

/** What a category does on Net worth, a step finer than the column: some internal
 *  categories have a known other side (investments, debt, your own accounts). */
export const ROLE_OF: Record<CategoryRole, () => string> = {
  spending: () => tr("Saved, as spending"),
  income: () => tr("Saved, as income"),
  bank: () => tr("Bank & cash"),
  investments: () => tr("To investments (net zero)"),
  debt: () => tr("Debt repayment (net zero)"),
  own: () => tr("Own accounts (net zero)"),
  others: () => tr("Money of others"),
};

/** The label for a category: its role when the backend sends one, else its column. */
export const countsAs = (c: Pick<Category, "type" | "role">) => (c.role ? ROLE_OF[c.role]() : COLUMN_OF[c.type]());

// Most common first: what you spend, what comes in, then what moves around.
export const COLUMN_ORDER: CategoryType[] = ["EXPENSE", "INCOME", "INTERNAL"];

export function TypeChoice({ category }: { category: Category }) {
  const qc = useQueryClient();
  const change = useMutation({
    mutationFn: (type: CategoryType) => api.put<{ categories: Category[] }>(`/api/categories/${category.id}/type`, { type }),
    onSuccess: () => qc.invalidateQueries(),
  });
  // Same look as "Move to…" next to it. A category the app relies on shows its
  // column in the same box, greyed out.
  return (
    <span className="inline-flex items-center gap-1">
      <select
        aria-label={tr("Column for {0}", category.name)}
        title={
          category.type_locked
            ? tr("The app relies on how this category counts.")
            : tr(
                "Where this category counts on Net worth. Spending and income make up Saved; Bank & cash is what moves between accounts and doesn't count as income or spending.",
              )
        }
        className="ds-select h-8 w-56 py-0 text-xs"
        value={category.type}
        disabled={category.type_locked || change.isPending}
        onChange={(e) => change.mutate(e.target.value as CategoryType)}
      >
        {category.type_locked ? (
          <option value={category.type}>{countsAs(category)}</option>
        ) : (
          COLUMN_ORDER.map((t) => (
            <option key={t} value={t}>
              {COLUMN_OF[t]()}
            </option>
          ))
        )}
      </select>
      {change.isError && (
        <span className="text-xs" style={{ color: "var(--text-loss)" }}>
          {change.error instanceof ApiError ? change.error.message : tr("Couldn't save. Try again.")}
        </span>
      )}
    </span>
  );
}

/**
 * "How categories count": what each choice means and how it adds up on Net
 * worth. Folded by default, so the page stays quiet until you want to know.
 */
export function CountsAsHelp() {
  const rows: [string, string][] = [
    [ROLE_OF.spending(), tr("Money you spent. It shows on Spending and lowers Saved on Net worth.")],
    [ROLE_OF.income(), tr("Money you earned. It raises Saved on Net worth.")],
    [
      ROLE_OF.bank(),
      tr(
        "Money that is neither income nor spending, such as a gift or a transfer to an account outside your net worth. It lands in Bank & cash on Net worth.",
      ),
    ],
    [
      ROLE_OF.investments(),
      tr("Money to your broker. It leaves your bank and arrives in your investments, so your net worth stays the same."),
    ],
    [ROLE_OF.debt(), tr("A repayment. Your bank balance goes down and so does your debt, so your net worth stays the same.")],
    [ROLE_OF.own(), tr("Money between your own accounts, such as to your savings account. It changes nothing.")],
    [
      ROLE_OF.others(),
      tr("Money that passes through you for others, such as a trip you organise. Only your own share counts, as you set in Settings."),
    ],
  ];
  return (
    <details className="py-2 text-sm">
      <summary className="cursor-pointer text-ink-muted">{tr("How categories count")}</summary>
      <div className="flex max-w-[72ch] flex-col gap-2 pt-3">
        <p className="text-ink-muted">
          {tr(
            "On Net worth every change splits into Saved, Market, Bank & cash and Debt. The category of a transaction decides where it goes:",
          )}
        </p>
        <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-[14rem_1fr]">
          {rows.map(([term, meaning]) => (
            <div key={term} className="contents">
              <dt className="font-medium">{term}</dt>
              <dd className="text-ink-muted">{meaning}</dd>
            </div>
          ))}
        </dl>
        <p className="text-ink-muted">
          {tr(
            "Market and Debt don't come from categories: Market is what your holdings did, Debt how your debts changed. Change a category's choice with the dropdown on the right; the ones the app relies on are fixed.",
          )}
        </p>
      </div>
    </details>
  );
}
