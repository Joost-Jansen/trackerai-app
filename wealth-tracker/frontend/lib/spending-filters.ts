"use client";

// The Spending filters, in the address bar.
//
// Period, account, categories, direction and search term are in the URL. Then
// clicking through works — a bar in the chart opens Transactions with exactly
// that filter — and so do a link and going back in your browser. Whoever goes to
// another view through a tab loses the URL; that is why this tab remembers the
// last filters and puts them back, so the period moves along from Overview to
// Transactions.
//
// Except when you clicked through (via=overview): that filter is for that one
// look at Transactions, and does not go back along to Overview or another tab.

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { accountGroups } from "@/lib/account-groups";
import { currentCode, periodWindow, type DateWindow } from "@/lib/timeline";
import { inCategories } from "@/components/money/CategoryFilter";
import { modifySpendingQuery } from "@/lib/spending-query";
import type { Account, Transaction } from "@/lib/money";
import { COUNTS_AS, type CountsAs } from "@/lib/counts-as";

export type Direction = "all" | "in" | "out";

const STORED = "spending-filters";
export const DEFAULT_PERIOD = "3M";

export function useSpendingFilters(first: string, last: string, boundaries: string[] | null) {
  const sp = useSearchParams();
  const pathname = usePathname();
  const query = sp.toString();

  useEffect(() => {
    try {
      if (query) {
        if (!sp.get("via")) sessionStorage.setItem(STORED, query);
      } else {
        const old = sessionStorage.getItem(STORED);
        if (old) window.history.replaceState(null, "", `${pathname}?${old}`);
      }
    } catch {
      // Geen opslag: filters gaan dan niet mee naar een andere tab.
    }
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  const put = (modify: Record<string, string | string[] | null>) => {
    // Filters work on transactions that are already loaded. The History API works
    // directly together with useSearchParams here and prevents competing
    // router.replace navigations when switching quickly between periods or tabs.
    const next = modifySpendingQuery(window.location.search.slice(1), modify);
    try {
      if (next) sessionStorage.setItem(STORED, next);
      else sessionStorage.removeItem(STORED);
    } catch { /* no storage */ }
    window.history.replaceState(null, "", next ? `${pathname}?${next}` : pathname);
  };

  const start = sp.get("start");
  const end = sp.get("end");
  const period = currentCode(sp.get("period") ?? (start || end ? "Custom" : DEFAULT_PERIOD));
  const time_window: DateWindow = period === "Custom"
    ? { from: start ?? first, to: end ?? last }
    : periodWindow(period, first, last, boundaries);

  return {
    // The same shape as useTimeline, so TimelineControls uses it as is.
    timeline: {
      window: time_window,
      period: period,
      // The default period also stays explicit in the URL. 1M → 3M must not first
      // empty the address bar and then restore an old filter.
      choose: (p: string) => put({ period: p, start: null, end: null }),
      change: (w: DateWindow) => put({ period: "Custom", start: w.from, end: w.to }),
    },
    account: sp.get("account") ?? "",
    setAccount: (v: string) => put({ account: v || null }),
    categories: sp.getAll("category"),
    setCategories: (v: string[]) => put({ category: v }),
    direction: ((sp.get("direction") as Direction) || "all") as Direction,
    setDirection: (v: Direction) => put({ direction: v === "all" ? null : v }),
    /** Where the transactions count on Net worth (lib/counts-as.ts); empty is everything. */
    counts: sp.getAll("counts").filter((c): c is CountsAs => COUNTS_AS.some((k) => k.code === c)),
    setCounts: (v: CountsAs[]) => put({ counts: v }),
    search: sp.get("search") ?? "",
    setSearch: (v: string) => put({ search: v || null }),
    /** Is anything other than the default set? */
    active: [...sp.keys()].some((k) => k !== "period" || sp.get(k) !== DEFAULT_PERIOD),
    /** Clicked through from Overview: a filter for this one look. */
    via: sp.get("via"),
    /** Removes one filter: a parameter, or one value of it (a category). */
    fetchAway: (key: string, value?: string) => {
      if (key === "period") return put({ period: null, start: null, end: null });
      if (value !== undefined) return put({ [key]: sp.getAll(key).filter((w) => w !== value) });
      put({ [key]: null });
    },
    clear: () => {
      try { sessionStorage.removeItem(STORED); } catch { /* no storage */ }
      window.history.replaceState(null, "", pathname);
    },
  };
}

export type SpendingFilters = ReturnType<typeof useSpendingFilters>;

/** The account ids behind the account filter ("" is everything). */
export function accountIds(f: SpendingFilters, accounts: Account[]): number[] | null {
  if (!f.account) return null;
  const bank = accountGroups(accounts).find((g) => `bank:${g.id}` === f.account);
  return bank ? bank.accounts.map((a) => a.id) : [Number(f.account)];
}

/** Applies the filters. `period: false` leaves the period out — for a comparison with earlier.
 *  `countsAs` classifies a transaction for the "Counts as" filter (lib/counts-as.ts). */
export function filterRows(rows: Transaction[], f: SpendingFilters, accounts: Account[],
  { period = true, countsAs }: { period?: boolean; countsAs?: (t: Transaction) => CountsAs } = {}): Transaction[] {
  const ids = accountIds(f, accounts);
  const q = f.search.trim().toLocaleLowerCase("nl");
  return rows.filter((r) =>
    (!period || (r.date >= f.timeline.window.from && r.date <= f.timeline.window.to))
    && (!ids || ids.includes(r.account_id))
    && inCategories(r.category, f.categories)
    && (f.counts.length === 0 || !countsAs || f.counts.includes(countsAs(r)))
    // Spending is positive in the database: "in" is a negative amount.
    && (f.direction === "all" || (f.direction === "in" ? r.amount < 0 : r.amount > 0))
    && (!q || `${r.name} ${r.description} ${r.category ?? ""}`.toLocaleLowerCase("nl").includes(q)));
}

/** An address to Transactions with these filters, to click through from a chart. */
export function toTransactions(w: {
  start?: string; end?: string; categories?: string[]; search?: string; account?: string; direction?: Direction;
}): string {
  const p = new URLSearchParams();
  if (w.start || w.end) {
    p.set("period", "Custom");
    if (w.start) p.set("start", w.start);
    if (w.end) p.set("end", w.end);
  }
  w.categories?.forEach((c) => p.append("category", c));
  if (w.search) p.set("search", w.search);
  if (w.account) p.set("account", w.account);
  if (w.direction && w.direction !== "all") p.set("direction", w.direction);
  p.set("via", "overview");
  return `/spending/transactions?${p}`;
}
