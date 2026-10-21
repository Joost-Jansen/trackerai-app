"use client";

// Spending — Transactions: the one list to search *and* correct.
//
// Filter by period, account, category, direction or a name; set a category per
// row, or tick more and label them together. A category you set here is manual
// and wins over every rule; with "Make rule" it applies from then on to that
// counterparty.

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtEuro } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { Button, Checkbox, EmptyState, Section, Select, Tag } from "@/components/ds";
import FilterBlock, { ActiveFilters, PeriodsBar } from "@/components/money/SpendingFilters";
import { CategoryOptions, AddManually, MakeRule } from "@/components/money/TransactionActions";
import { useChooseFixedCost, type FixedCost } from "@/components/money/FixedCostsAdmin";
import { nameKey } from "@/components/money/charts/base";
import { boundariesOf, useMonthPeriods } from "@/lib/month-periods";
import { filterRows, useSpendingFilters } from "@/lib/spending-filters";
import { showAmount, today, type Category, type Account, type Transaction } from "@/lib/money";
import { tr, trx } from "@/lib/i18n";
import { countsAs } from "@/components/money/CategoryColumns";
import { countsAsOf } from "@/lib/counts-as";

const PER_PAGE = 100;
const signed = (v: number) => `${Math.round(v * 100) > 0 ? "+" : ""}${trueMinus(fmtEuro(Math.round(v * 100) / 100 || 0))}`;
const EXCLUDE = "Niet meetellen";

type Compare = (a: Transaction, b: Transaction) => number;
const kindRank = (r: Transaction) =>
  !r.category || r.category === "Onbekend" ? 0 : (({ EXPENSE: 1, INCOME: 2, INTERNAL: 3 } as Record<string, number>)[r.type ?? ""] ?? 4);
const SORTINGS: Record<string, { label: string; fn: Compare }> = {
  newest: { label: tr("Newest first"), fn: (a, b) => b.date.localeCompare(a.date) || b.id - a.id },
  oldest: { label: tr("Oldest first"), fn: (a, b) => a.date.localeCompare(b.date) || a.id - b.id },
  amount: { label: tr("Largest amount"), fn: (a, b) => Math.abs(b.amount) - Math.abs(a.amount) || b.id - a.id },
  name: { label: tr("Name"), fn: (a, b) => a.name.localeCompare(b.name, "nl") || b.date.localeCompare(a.date) },
  kind: { label: tr("To label first"), fn: (a, b) => kindRank(a) - kindRank(b) || b.date.localeCompare(a.date) },
};

function Transactions() {
  const qc = useQueryClient();
  const layout = useMonthPeriods();
  const boundaries = boundariesOf(layout.data);
  const transactions = useQuery({
    queryKey: ["bank_transactions", "overview"],
    queryFn: () => api.get<{ transactions: Transaction[] }>("/api/bank-transactions"),
  });
  const taxonomy = useQuery({ queryKey: ["categories"], queryFn: () => api.get<{ categories: Category[] }>("/api/categories") });
  const accountsQ = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<{ accounts: Account[] }>("/api/accounts") });
  // The same list as Overview (all accounts): which counterparties are fixed.
  const fixedQ = useQuery({
    queryKey: ["fixed-costs", ""],
    queryFn: () => api.get<{ fixed_costs: FixedCost[]; per_month: number }>("/api/spending/fixed-costs"),
  });
  const chooseFixed = useChooseFixedCost();
  const [onlyIsFixed, setOnlyIsFixed] = useState(false);

  const allRows = transactions.data?.transactions ?? [];
  const first = allRows.reduce((m, r) => (r.date < m ? r.date : m), today());
  const f = useSpendingFilters(first, today(), boundaries);
  // From the Bank & cash link on Net worth: that number, to set the list against.
  // Gone as soon as a filter changes (that drops `via`).
  const params = useSearchParams();
  const fromNetWorth =
    params.get("via") === "net-worth" && params.get("nw_bank") !== null
      ? { bank: Number(params.get("nw_bank")), corrections: Number(params.get("nw_corrections") ?? 0) }
      : null;
  const [sorting, setSorting] = useState("newest");
  const [page, setPage] = useState(0);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [target, setTarget] = useState("");
  const [manual, setManual] = useState(false);

  // Net worth, budget and month totals all hang on the category.
  const refresh = () => {
    qc.invalidateQueries();
  };
  const labelling = useMutation({
    mutationFn: ({ ids, category }: { ids: number[]; category: string | null }) =>
      api.put<{ updated: number }>("/api/bank-transactions/category", { ids, category }),
    onSuccess: (_d, { ids }) => {
      setChosen((old) => {
        const next = new Set(old);
        ids.forEach((i) => next.delete(i));
        return next;
      });
      refresh();
    },
  });
  const removal = useMutation({ mutationFn: (id: number) => api.del(`/api/bank-transactions/${id}`), onSuccess: refresh });

  if (transactions.isLoading || taxonomy.isLoading) {
    return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  const categories = taxonomy.data?.categories ?? [];
  const roleOf = new Map(categories.map((c) => [c.name, c.role]));
  const accounts = accountsQ.data?.accounts ?? [];
  const nameOf = new Map(accounts.map((r) => [r.id, r.name]));

  const is_fixed = new Set((fixedQ.data?.fixed_costs ?? []).map((v) => v.key));
  const isFixed = (t: Transaction) => t.type === "EXPENSE" && is_fixed.has(nameKey(t.name));
  const rows = filterRows(allRows, f, accounts, { countsAs: countsAsOf(roleOf, accounts) })
    .filter((t) => !onlyIsFixed || isFixed(t))
    .sort(SORTINGS[sorting].fn);
  const selection = rows.filter((r) => chosen.has(r.id));
  const sumSelection = selection.reduce((s, r) => s + showAmount(r.amount), 0);
  const sumFilter = rows.reduce((s, r) => s + showAmount(r.amount), 0);
  const everythingChosen = rows.length > 0 && selection.length === rows.length;
  const maxPage = Math.max(0, Math.ceil(rows.length / PER_PAGE) - 1);
  const current = Math.min(page, maxPage);
  const shown = rows.slice(current * PER_PAGE, (current + 1) * PER_PAGE);
  const toggle = (ids: number[], on: boolean) =>
    setChosen((old) => {
      const next = new Set(old);
      ids.forEach((i) => (on ? next.add(i) : next.delete(i)));
      return next;
    });

  return (
    <div className="flex flex-col gap-8">
      <PeriodsBar
        f={f}
        accounts={accounts}
        onClear={() => {
          f.clear();
          setPage(0);
        }}
      >
        <p className="mb-3 text-xs text-ink-muted">
          {tr("For one day set From and Up to and including to the same date. “Still to categorise” shows what still needs a label.")}
        </p>
        <p className="mb-3 text-xs text-ink-muted">
          {trx("{0} transactions · together {1}{2}", rows.length, sumFilter > 0 ? "+" : "", trueMinus(fmtEuro(sumFilter)))}
        </p>
        <ActiveFilters f={f} accounts={accounts} />
        <FilterBlock f={f} first={first} last={today()} accounts={accounts} categories={categories} lookup periods={false} />
      </PeriodsBar>
      {fromNetWorth && (
        <p className="-mt-4 text-xs text-ink-muted">
          {trx(
            "Bank & cash on Net worth: {0} = these transactions {1} + balance corrections {2} + money whose other half isn't a bank transaction {3}.",
            signed(fromNetWorth.bank),
            signed(sumFilter),
            signed(fromNetWorth.corrections),
            signed(fromNetWorth.bank - sumFilter - fromNetWorth.corrections),
          )}
        </p>
      )}

      <Section
        label={tr("Transactions")}
        info={
          <>
            {tr(
              "A category you set here always wins over the rules. Tick transactions to label them together. Handy for one-off things such as a holiday with friends. “Make rule” applies to that counterparty from then on; better not do that for something that happened only once.",
            )}
          </>
        }
        action={
          <span className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-ink-muted">
              {trx(
                "{0}Only fixed costs",
                <Checkbox
                  checked={onlyIsFixed}
                  aria-label={tr("Only fixed costs")}
                  onChange={(on) => {
                    setOnlyIsFixed(on);
                    setPage(0);
                  }}
                />,
              )}
            </label>
            <Select aria-label={tr("Sort by")} value={sorting} onChange={(e) => setSorting(e.target.value)}>
              {Object.entries(SORTINGS).map(([k, s]) => (
                <option key={k} value={k}>
                  {s.label}
                </option>
              ))}
            </Select>
          </span>
        }
      >
        {/* Plakt onder de kopbalk van de app (60px, z-30), niet erachter. */}
        <div
          className="sticky top-[105px] z-10 mb-3 flex flex-wrap items-end justify-between gap-3 rounded-md p-3"
          style={{ background: "var(--surface-inset)", border: "1px solid var(--rule)", boxShadow: "0 6px 12px -8px rgba(0,0,0,.18)" }}
        >
          <span className="text-sm">
            {trx(
              "{0} chosen{1}",
              <b className="num">{selection.length}</b>,
              selection.length > 0 && (
                <>
                  {" "}
                  {trx(
                    "· together {0}",
                    <b className="num">
                      {sumSelection > 0 ? "+" : ""}
                      {trueMinus(fmtEuro(sumSelection))}
                    </b>,
                  )}
                </>
              ),
            )}
          </span>
          <span className="flex flex-wrap items-end gap-2">
            {/* On the grey bar a filled dropdown would vanish: this one is raised. */}
            <Select aria-label={tr("Label as")} className="ds-select--raised" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">{tr("Label as…")}</option>
              <option value="__regels">{tr("(back to what the rules find)")}</option>
              <CategoryOptions categories={categories} />
            </Select>
            <Button
              variant="primary"
              disabled={!target || selection.length === 0 || labelling.isPending}
              onClick={() => labelling.mutate({ ids: selection.map((r) => r.id), category: target === "__regels" ? null : target })}
            >
              {labelling.isPending ? tr("Working…") : tr("Label {0}", selection.length || "").trim()}
            </Button>
          </span>
        </div>
        {target === EXCLUDE && selection.length > 0 && (
          <p className="pb-3 text-xs text-ink-muted">
            {tr(
              "Niet meetellen is no income and no expense. What you received from others and haven't paid on yet doesn't count as your net worth; what you paid more than you received is your own share.",
            )}
          </p>
        )}
        {chooseFixed.isError && (
          <p className="pb-2 text-xs" style={{ color: "var(--text-loss)" }}>
            {(chooseFixed.error as ApiError).message}
          </p>
        )}
        {labelling.isError && (
          <p className="pb-2 text-xs" style={{ color: "var(--text-loss)" }}>
            {(labelling.error as ApiError).message}
          </p>
        )}

        {rows.length === 0 ? (
          allRows.length === 0 ? (
            <EmptyState title={tr("No transactions yet")} body={tr("Connect your bank at Accounts, or upload an export via Update.")} />
          ) : (
            <EmptyState
              title={tr("Nothing with these filters")}
              body={tr("Choose a longer period or clear the filters.")}
              action={
                <Button size="sm" variant="secondary" onClick={() => f.clear()}>
                  {tr("Clear filters")}
                </Button>
              }
            />
          )
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-[12.5px]">
              <thead>
                <tr className="text-left text-ink-muted">
                  <th className="w-8 py-1.5">
                    <Checkbox
                      checked={everythingChosen}
                      aria-label={tr("Choose all {0}", rows.length)}
                      onChange={(on) =>
                        toggle(
                          rows.map((r) => r.id),
                          on,
                        )
                      }
                    />
                  </th>
                  <th className="py-1.5 font-normal">{tr("Date")}</th>
                  <th className="py-1.5 font-normal">{tr("Account")}</th>
                  <th className="py-1.5 font-normal">{tr("Counterparty")}</th>
                  <th className="py-1.5 text-right font-normal">{tr("Amount")}</th>
                  <th className="py-1.5 pl-4 font-normal">{tr("Category")}</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody>
                {shown.map((t) => {
                  const amount = showAmount(t.amount);
                  const own = t.category_manual !== null;
                  return (
                    <tr key={t.id} className="align-top" style={{ borderTop: "1px solid var(--rule)" }}>
                      <td className="py-2">
                        <Checkbox
                          checked={chosen.has(t.id)}
                          aria-label={tr("Choose {0} on {1}", t.name, t.date)}
                          onChange={(on) => toggle([t.id], on)}
                        />
                      </td>
                      <td className="num whitespace-nowrap py-2 text-ink-muted">{t.date}</td>
                      <td className="py-2 text-ink-muted">{nameOf.get(t.account_id) ?? "–"}</td>
                      <td className="py-2">
                        <span className="flex items-center gap-2">
                          <span className="min-w-0">{t.name}</span>
                          {/* Every tag of the row in one place, next to the name. They keep their own
                              width and never wrap: the name gives way. */}
                          <span className="flex shrink-0 items-center gap-1 whitespace-nowrap">
                            {isFixed(t) && (
                              <span title={tr("Comes back every month. Adjust with the button on the right, or at Categories.")}>
                                <Tag tone="brand">{tr("fixed cost")}</Tag>
                              </span>
                            )}
                            {t.source === "manual" && <Tag tone="neutral">{tr("by hand")}</Tag>}
                            {own && (
                              <span
                                title={
                                  t.category_auto && t.category_auto !== t.category
                                    ? tr("You chose this category; the rules said: {0}", t.category_auto)
                                    : tr("You chose this category")
                                }
                              >
                                <Tag tone="neutral">{tr("manual")}</Tag>
                              </span>
                            )}
                            {!own && t.category_source === "learned" && (
                              <span title={tr("This is how you labelled transactions with this counterparty before")}>
                                <Tag tone="neutral">{tr("learned")}</Tag>
                              </span>
                            )}
                            {!own && t.category_source === "ai" && (
                              <span title={tr("Suggested by Claude; choose a category yourself if it's wrong")}>
                                <Tag tone="neutral">AI</Tag>
                              </span>
                            )}
                          </span>
                        </span>
                        {t.description && <span className="block max-w-[26rem] truncate text-xs text-ink-muted">{t.description}</span>}
                      </td>
                      <td
                        className="num whitespace-nowrap py-2 text-right"
                        style={{ color: t.type === "INTERNAL" ? "var(--text-faint)" : amount > 0 ? "var(--text-gain)" : undefined }}
                      >
                        {trueMinus(fmtEuro(amount))}
                      </td>
                      <td className="py-2 pl-4">
                        <span className="flex items-center gap-1.5">
                          {/* Fixed width, so the dropdown never shrinks when a tag appears. Hovering
                              it says where the transaction counts on Net worth. */}
                          <select
                            className="ds-select w-52 shrink-0"
                            value={t.category ?? ""}
                            disabled={labelling.isPending}
                            title={
                              t.type
                                ? tr(
                                    "Counts as: {0}. Set per category at Categories.",
                                    countsAs({ type: t.type, role: roleOf.get(t.category ?? "") }),
                                  )
                                : undefined
                            }
                            aria-label={tr("Category of {0}", t.name)}
                            onChange={(e) => labelling.mutate({ ids: [t.id], category: e.target.value || null })}
                          >
                            <option value="">{tr("(the rules)")}</option>
                            <CategoryOptions categories={categories} />
                          </select>
                        </span>
                      </td>
                      <td className="py-2 text-right">
                        {t.category && t.category !== "Onbekend" && <MakeRule transaction={t} category={t.category} onDone={refresh} />}
                        {t.type === "EXPENSE" && t.amount > 0 && (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={chooseFixed.isPending || fixedQ.isLoading}
                            title={
                              isFixed(t)
                                ? tr("Stop counting {0} as a fixed cost", t.name)
                                : tr("Count {0} as a fixed cost, also in other months", t.name)
                            }
                            onClick={() => chooseFixed.mutate({ name: t.name, is_fixed: !isFixed(t) })}
                          >
                            {isFixed(t) ? tr("Not a fixed cost") : tr("Fixed cost")}
                          </Button>
                        )}
                        {t.source === "manual" && (
                          <Button size="sm" variant="ghost" disabled={removal.isPending} onClick={() => removal.mutate(t.id)}>
                            {tr("Delete")}
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {rows.length > PER_PAGE && (
          <div className="flex flex-wrap items-center justify-between gap-2 pt-3 text-xs text-ink-muted">
            <span>{trx("{0}–{1} of {2}", current * PER_PAGE + 1, Math.min((current + 1) * PER_PAGE, rows.length), rows.length)}</span>
            <span className="flex gap-2">
              <Button size="sm" variant="ghost" disabled={current === 0} onClick={() => setPage(current - 1)}>
                {tr("Previous")}
              </Button>
              <Button size="sm" variant="ghost" disabled={current === maxPage} onClick={() => setPage(current + 1)}>
                {tr("Next")}
              </Button>
            </span>
          </div>
        )}
      </Section>

      <Section
        label={tr("Add by hand")}
        info={<>{tr("For what isn't in any export: cash, a market, a refund that didn't come by anywhere else.")}</>}
        action={
          <Button size="sm" variant="ghost" onClick={() => setManual((v) => !v)}>
            {manual ? tr("Close") : tr("Add transaction")}
          </Button>
        }
      >
        {manual && <AddManually accounts={accounts} categories={categories} onDone={refresh} />}
      </Section>
    </div>
  );
}

export default function TransactionsPage() {
  // The filters are in the address bar; Next only reads that in the browser.
  return (
    <Suspense fallback={<div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />}>
      <Transactions />
    </Suspense>
  );
}
