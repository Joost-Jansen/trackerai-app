"use client";

// Spending — Overview: only insight, no lists to work in.
//
// At the top the key figures of your period next to a normal month. Below that
// charts that each answer one question: are you on track, where did it go per
// month, per group, as a distribution, what rises or falls, what is fixed, when
// do you spend, and what was large. Which charts are shown, in which order and
// with which settings, you choose yourself; the page remembers it with your
// account.
//
// Everything can be pointed at (a hover card with the numbers) and clicked: then
// Transactions opens with exactly that filter, just for that one look.
//
// "Normal" is the average of the twelve months before the chosen period, with the
// same account and category filters — months from before your first data do not
// count.
//
// Next to the period there is one month, also in the bar at the top: the cards
// about a single month (Are you on track?, Budget this month) look at it, and so
// does Budget. Changing it in one place changes it everywhere.

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDayMonthYear, fmtEuro } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { Button, EmptyState, Eyebrow, Section, Tag } from "@/components/ds";
import FilterBlock, { MonthPicker, PeriodsBar } from "@/components/money/SpendingFilters";
import SpendingTrend from "@/components/money/SpendingTrend";
import { ChartCard, Setting, monthChoices, monthsUntil, nameKey, type Editing, type Context } from "@/components/money/charts/base";
import MonthChart from "@/components/money/charts/MonthChart";
import GroupComparison from "@/components/money/charts/GroupComparison";
import OnTrack from "@/components/money/charts/OnTrack";
import BudgetThisMonth from "@/components/money/charts/BudgetThisMonth";
import Distribution from "@/components/money/charts/Distribution";
import Trends from "@/components/money/charts/Trends";
import When from "@/components/money/charts/When";
import FixedVariable from "@/components/money/charts/FixedVariable";
import { averageMonthBase, dayNumber, isoDay } from "@/lib/timeline";
import { boundariesOf, useMonthPeriods } from "@/lib/month-periods";
import { filterRows, toTransactions, accountIds, useSpendingFilters } from "@/lib/spending-filters";
import { countsAsOf } from "@/lib/counts-as";
import { variableSpending } from "@/lib/variable-spending";
import { today, type Category, type Account, type Transaction } from "@/lib/money";
import { intlLocale, tr, trx } from "@/lib/i18n";

// How many months "normal" covers.
const MONTHS = 12;

type Id =
  "price" | "budget" | "month" | "group_name" | "distribution" | "trends" | "fixed_variable" | "when" | "fixedcosts" | "top" | "income";
const TITLES: Record<Id, string> = {
  income: tr("Income and spending over time"),
  price: tr("Are you on track?"),
  budget: tr("Budget this month"),
  month: tr("Per month"),
  fixed_variable: tr("Fixed and variable"),
  group_name: tr("Per group"),
  distribution: tr("Breakdown"),
  trends: tr("Trends and risers"),
  when: tr("When you spend"),
  fixedcosts: tr("Fixed costs"),
  top: tr("Largest variable items"),
};
const ORDER = Object.keys(TITLES) as Id[];
type Item = { id: Id; visible: boolean; inst: Record<string, string> };
const DEFAULT: Item[] = ORDER.map((id) => ({ id, visible: true, inst: {} }));
const LAYOUT_VERSION = 4;

/** Your stored layout, completed with charts that were added later. */
function merge(stored: unknown): Item[] {
  const preference = stored as { version?: number; charts?: Partial<Item>[] } | null;
  const items = preference?.charts;
  if (!Array.isArray(items)) return DEFAULT;
  const seen = new Set<Id>();
  const known = items
    .filter((g): g is Item => {
      if (!g || !ORDER.includes(g.id as Id) || seen.has(g.id as Id)) return false;
      seen.add(g.id as Id);
      return true;
    })
    .map((g) => ({ id: g.id, visible: g.visible !== false, inst: g.inst && typeof g.inst === "object" ? g.inst : {} }));
  const layout = [...known, ...DEFAULT.filter((s) => !known.some((b) => b.id === s.id))];
  // Apply the requested order once to existing layouts. After that the user can
  // move these charts freely again.
  const version = preference?.version ?? 1;
  let off = layout;
  if (version < 3) {
    const in_front = ["income", "price", "month", "fixed_variable"] as Id[];
    const misc = layout.filter((g) => !in_front.includes(g.id) && g.id !== "top" && g.id !== "fixedcosts");
    const fixed = layout.find((g) => g.id === "fixedcosts");
    const top = layout.find((g) => g.id === "top");
    off = [...in_front.map((id) => layout.find((g) => g.id === id)!), ...misc, ...[fixed, top].filter((g): g is Item => !!g)];
  }
  // Version 4: "Budget this month" was added, right below "Are you on track?".
  if (version < 4) {
    const budget = off.find((g) => g.id === "budget")!;
    const without = off.filter((g) => g.id !== "budget");
    without.splice(without.findIndex((g) => g.id === "price") + 1, 0, budget);
    off = without;
  }
  return off;
}

/** The layout of this page, stored with your account; saved shortly after you change something. */
function useLayout() {
  const q = useQuery({
    queryKey: ["preferences", "spending_overview"],
    queryFn: () => api.get<{ value: unknown }>("/api/preferences/spending_overview"),
  });
  const [items, setItems] = useState<Item[] | null>(null);
  useEffect(() => {
    if (q.data && items === null) setItems(merge(q.data.value));
  }, [q.data, items]);
  const save = useMutation({
    mutationFn: (value: { version: number; charts: Item[] } | null) => api.put("/api/preferences/spending_overview", { value }),
    scope: { id: "spending-overview-preference" },
  });
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const put = (items: Item[]) => {
    setItems(items);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => save.mutate({ version: LAYOUT_VERSION, charts: items }), 500);
  };
  const restore = () => {
    clearTimeout(timer.current);
    setItems(DEFAULT);
    save.mutate(null);
  };
  return { items: items ?? merge(q.data?.value ?? null), put, restore, saveError: save.isError };
}

const sumType = (rows: Transaction[], type: string) => rows.filter((r) => r.type === type).reduce((a, r) => a + r.amount, 0) || 0;

function Comparison({ now, normal, moreIsGood }: { now: number; normal: number | null; moreIsGood: boolean }) {
  if (normal === null || normal <= 0) return null;
  const difference = ((now - normal) / normal) * 100;
  if (Math.abs(difference) < 1) return <span>{tr("as usual")}</span>;
  const good = difference > 0 === moreIsGood;
  return (
    <span style={{ color: good ? "var(--text-gain)" : "var(--text-loss)" }}>
      {trx("{0}{1}% vs. usual", difference > 0 ? "+" : "−", Math.abs(difference).toLocaleString(intlLocale, { maximumFractionDigits: 0 }))}
    </span>
  );
}

function Digit({ label, value, sub }: { label: string; value: string; sub?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-[5px]">
      <Eyebrow>{label}</Eyebrow>
      <span className="num font-display text-[21px] leading-tight tracking-[-0.02em]">{trueMinus(value)}</span>
      <span className="num min-h-[16px] text-xs leading-[16px] text-ink-muted">{sub ?? ""}</span>
    </div>
  );
}

type FixedCost = {
  name: string;
  category: string | null;
  group_name: string | null;
  amount: number;
  count: number;
  first: string;
  last: string;
  is_new: boolean;
  stopped: boolean;
};

function FixedCostsList({ items, perMonth }: { items: FixedCost[]; perMonth: number }) {
  if (items.length === 0) {
    return <p className="py-2 text-sm text-ink-muted">{tr("No debits found yet that come back every month.")}</p>;
  }
  const yearAgo = isoDay(dayNumber(today()) - 365);
  return (
    <>
      <p className="flex flex-wrap items-baseline justify-between gap-2 pb-2 text-sm">
        <span>{trx("Together {0} per month in running fixed costs.", <b className="num">{fmtEuro(perMonth)}</b>)}</span>
        <Link href="/categories#fixed-costs" className="text-xs underline underline-offset-4">
          {tr("Adjust")}
        </Link>
      </p>
      <ul className="flex flex-col">
        {items.map((v) => (
          <li
            key={v.name}
            className="flex flex-wrap items-center justify-between gap-2 py-2 text-[12.5px]"
            style={{ borderTop: "1px solid var(--rule)", opacity: v.stopped ? 0.55 : 1 }}
          >
            <Link href={toTransactions({ search: v.name, start: yearAgo, end: today() })} className="flex min-w-0 flex-col hover:underline">
              <span className="flex items-center gap-2">
                {v.name}
                {v.is_new && !v.stopped && <Tag tone="brand">{tr("new")}</Tag>}
                {v.stopped && <Tag tone="neutral">{tr("stopped?")}</Tag>}
              </span>
              <span className="text-xs text-ink-muted">
                {trx("{0} · {1}× · last {2}", v.category ?? "Onbekend", v.count, fmtDayMonthYear(v.last))}
              </span>
            </Link>
            <span className="num">{fmtEuro(v.amount)}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function LargestItems({
  ctx,
  inst,
  put,
  editing,
}: {
  ctx: Context;
  inst: Record<string, string>;
  put: (k: string, v: string) => void;
  editing?: Editing;
}) {
  const count = Number(inst.count ?? "8");
  const perName = new Map<string, { summed: number; n: number }>();
  const variable = variableSpending(ctx.rows, (name) => ctx.fixedNames.has(nameKey(name)), ctx.ownIbans);
  for (const r of variable) {
    const v = perName.get(r.name) ?? { summed: 0, n: 0 };
    v.summed += r.amount;
    v.n += 1;
    perName.set(r.name, v);
  }
  const topNames = [...perName.entries()].sort((a, b) => b[1].summed - a[1].summed).slice(0, count);
  const largest = [...variable].sort((a, b) => b.amount - a.amount).slice(0, count);
  const row = (key: string, links: React.ReactNode, amount: number, run: () => void, mean?: number) => (
    <li key={key} style={{ borderTop: "1px solid var(--rule)" }}>
      <button
        type="button"
        onClick={run}
        className="flex w-full items-center justify-between gap-2 py-2 text-left text-[12.5px] hover:bg-surface-2"
      >
        <span className="min-w-0 truncate">{links}</span>
        <span className="num whitespace-nowrap text-right">
          {fmtEuro(amount)}
          {mean !== undefined && (
            <span className="block text-[11px] text-ink-muted">{trx("avg. {0}/{1}", fmtEuro(mean), ctx.monthWord)}</span>
          )}
        </span>
      </button>
    </li>
  );
  return (
    <ChartCard
      title={tr("Largest variable items")}
      editing={editing}
      settings={
        <Setting
          label={tr("Number")}
          value={String(count)}
          onChange={(w) => put("count", w)}
          options={[
            ["5", "5"],
            ["8", "8"],
            ["12", "12"],
          ]}
        />
      }
      info={tr(
        "Largest variable spending in this period. Recognised fixed costs and transfers to your own accounts aren't here. Click to open the transactions.",
      )}
    >
      <div className="grid gap-6">
        <div>
          <p className="pb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">{tr("Where most of it went")}</p>
          <ul className="flex flex-col">
            {topNames.map(([name, v]) =>
              row(
                name,
                <>
                  {name} <span className="text-xs text-ink-muted">{v.n}×</span>
                </>,
                v.summed,
                () => ctx.dest({ start: ctx.time_window.from, end: ctx.time_window.to, search: name }),
                ctx.months > 0 ? v.summed / ctx.months : 0,
              ),
            )}
          </ul>
        </div>
        <div>
          <p className="pb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">{tr("Largest expenses")}</p>
          <ul className="flex flex-col">
            {largest.map((r) =>
              row(
                String(r.id),
                <>
                  {r.name}{" "}
                  <span className="text-xs text-ink-muted">
                    {fmtDayMonthYear(r.date)} · {r.category ?? "Onbekend"}
                  </span>
                </>,
                r.amount,
                () => ctx.dest({ start: r.date, end: r.date, search: r.name }),
              ),
            )}
          </ul>
        </div>
      </div>
    </ChartCard>
  );
}

function Overview() {
  const router = useRouter();
  const layout = useMonthPeriods();
  const boundaries = boundariesOf(layout.data);
  const transactions = useQuery({
    queryKey: ["bank_transactions", "overview"],
    // With your own share of shared costs (Settings): it is spending, even though
    // it is no single transaction.
    queryFn: () => api.get<{ transactions: Transaction[] }>("/api/bank-transactions?shared_shares=true"),
  });
  const taxonomy = useQuery({ queryKey: ["categories"], queryFn: () => api.get<{ categories: Category[] }>("/api/categories") });
  const accountsQ = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<{ accounts: Account[] }>("/api/accounts") });
  const { items, put: saveItems, restore, saveError } = useLayout();
  const [edit, setEdit] = useState(false);

  const allTx = transactions.data?.transactions ?? [];
  const first = allTx.reduce((m, r) => (r.date < m ? r.date : m), today());
  const f = useSpendingFilters(first, today(), boundaries);
  const accounts = accountsQ.data?.accounts ?? [];
  const ids = accountIds(f, accounts);
  const qs = ids ? ids.map((i) => `account_id=${i}`).join("&") : "";
  const fixed = useQuery({
    queryKey: ["fixed-costs", qs],
    queryFn: () => api.get<{ fixed_costs: FixedCost[]; per_month: number }>(`/api/spending/fixed-costs${qs ? `?${qs}` : ""}`),
  });

  if (transactions.isLoading || taxonomy.isLoading) {
    return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  if (transactions.isError) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>
        {tr("Transactions could not load. Try again.")}
      </p>
    );
  }
  if (allTx.length === 0) {
    return (
      <EmptyState
        title={tr("No transactions yet")}
        body={tr("Connect your bank at Accounts, or upload an export via Update. How that works is explained in Help.")}
        action={
          <Link href="/help/money#importing" className="underline underline-offset-4">
            {tr("How this works")}
          </Link>
        }
      />
    );
  }

  const categories = taxonomy.data?.categories ?? [];
  const time_window = f.timeline.window;
  const countsAs = countsAsOf(new Map(categories.map((c) => [c.name, c.role])), accounts);
  const allRows = filterRows(allTx, f, accounts, { period: false, countsAs });
  const rows = allRows.filter((r) => r.date >= time_window.from && r.date <= time_window.to);
  const months = averageMonthBase(time_window, f.timeline.period, boundaries);
  const firstShown = allRows.reduce((m, r) => (r.date < m ? r.date : m), today());
  const base = monthsUntil(isoDay(dayNumber(time_window.from) - 1), boundaries, MONTHS).filter((m) => m.start >= firstShown);
  const baseRows = base.length ? allRows.filter((r) => r.date >= base[0].start && r.date <= base[base.length - 1].end) : [];
  const monthWord = boundaries ? tr("salary month") : tr("month");
  const choices = monthChoices(first, boundaries, today());
  const month = choices.find((m) => m.key === f.month) ?? choices[choices.length - 1];

  const ctx: Context = {
    rows,
    allRows,
    base,
    baseRows,
    time_window,
    boundaries,
    months,
    categories,
    monthWord,
    month,
    running: month === choices[choices.length - 1],
    monthChoices: choices,
    setMonth: f.setMonth,
    groupOf: (c) => categories.find((x) => x.name === c)?.group_name ?? "Onbekend",
    categoriesOf: (g) => categories.filter((c) => c.group_name === g).map((c) => c.name),
    fixedNames: new Set((fixed.data?.fixed_costs ?? []).map((v) => nameKey(v.name))),
    ownIbans: new Set(accounts.map((r) => (r.iban ?? "").replace(/\s/g, "").toUpperCase()).filter(Boolean)),
    dest: (w) => router.push(toTransactions({ account: f.account, ...w })),
  };

  const spending = sumType(rows, "EXPENSE");
  const income = -sumType(rows, "INCOME") || 0;
  const normalOut = base.length ? sumType(baseRows, "EXPENSE") / base.length : null;
  const normalIn = base.length ? (-sumType(baseRows, "INCOME") || 0) / base.length : null;
  const perMonth = (v: number) => (months > 0 ? v / months : 0);

  const visible = items.filter((g) => g.visible);
  const hidden = items.filter((g) => !g.visible);
  const saveSettings = (id: Id) => (k: string, v: string) =>
    saveItems(items.map((x) => (x.id === id ? { ...x, inst: { ...x.inst, [k]: v } } : x)));
  const move = (id: Id, direction: -1 | 1) => {
    const follow = visible.map((x) => x.id);
    const target = follow[follow.indexOf(id) + direction];
    if (!target) return;
    const a = items.findIndex((x) => x.id === id);
    const b = items.findIndex((x) => x.id === target);
    const next = [...items];
    [next[a], next[b]] = [next[b], next[a]];
    saveItems(next);
  };
  const editingFor = (id: Id, k: number): Editing | undefined =>
    edit
      ? {
          up: k > 0 ? () => move(id, -1) : undefined,
          down: k < visible.length - 1 ? () => move(id, 1) : undefined,
          hide: () => saveItems(items.map((x) => (x.id === id ? { ...x, visible: false } : x))),
        }
      : undefined;

  const chart = (g: Item, k: number) => {
    const p = { ctx, inst: g.inst, put: saveSettings(g.id), editing: editingFor(g.id, k) };
    switch (g.id) {
      case "price":
        return <OnTrack key={g.id} {...p} />;
      case "budget":
        return <BudgetThisMonth key={g.id} {...p} />;
      case "month":
        return <MonthChart key={g.id} {...p} />;
      case "group_name":
        return <GroupComparison key={g.id} {...p} />;
      case "distribution":
        return <Distribution key={g.id} {...p} />;
      case "trends":
        return <Trends key={g.id} {...p} />;
      case "fixed_variable":
        return <FixedVariable key={g.id} {...p} />;
      case "when":
        return <When key={g.id} {...p} />;
      case "top":
        if (fixed.isLoading || accountsQ.isLoading || fixed.isError || accountsQ.isError) {
          return (
            <ChartCard key={g.id} title={tr("Largest variable items")} editing={p.editing}>
              <p className="py-3 text-sm text-ink-muted">
                {fixed.isError || accountsQ.isError
                  ? tr("Accounts or fixed costs could not load. Refresh the page to check this list.")
                  : tr("Loading fixed costs and own accounts…")}
              </p>
            </ChartCard>
          );
        }
        return <LargestItems key={g.id} {...p} />;
      case "fixedcosts":
        return (
          <ChartCard
            key={g.id}
            title={tr("Fixed costs")}
            editing={p.editing}
            info={tr(
              "Debits that come back every month with about the same amount (rent, subscriptions, insurance) found in your last year. A new one is marked; one that hasn't been debited for a while may have been cancelled.",
            )}
          >
            {fixed.isError ? (
              <p className="text-xs text-ink-muted">{tr("Fixed costs could not load. Refresh the page.")}</p>
            ) : fixed.isLoading ? (
              <p className="text-xs text-ink-muted">{tr("Loading…")}</p>
            ) : (
              <FixedCostsList items={fixed.data?.fixed_costs ?? []} perMonth={fixed.data?.per_month ?? 0} />
            )}
          </ChartCard>
        );
      case "income":
        return (
          <SpendingTrend
            key={g.id}
            rows={rows}
            boundaries={boundaries}
            unit={g.inst.unit ?? "month"}
            onUnitChange={(w) => saveSettings(g.id)("unit", w)}
            editing={p.editing}
          />
        );
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <PeriodsBar
        f={f}
        accounts={accounts}
        month={<MonthPicker choices={choices} value={month.key} monthWord={monthWord} onChange={f.setMonth} />}
      >
        <p className="mb-3 text-xs text-ink-muted">
          {tr(
            "Period, account and categories apply to everything on this page and carry over to the other tabs. The month next to the periods is for the cards about one month: Are you on track?, Budget this month and Budget.",
          )}
        </p>
        <FilterBlock f={f} first={first} last={today()} accounts={accounts} categories={categories} periods={false} />
      </PeriodsBar>

      <Section
        label={tr("This period")}
        action={
          <Button size="sm" variant={edit ? "primary" : "ghost"} onClick={() => setEdit((b) => !b)}>
            {edit ? tr("Done arranging") : tr("Arrange charts")}
          </Button>
        }
        info={
          <>
            {trx(
              "Average per {0}, next to a normal month: the average of the twelve months before. Internal (money between your own accounts, gifts, other people's money) doesn't count.",
              monthWord,
            )}
          </>
        }
      >
        <div className="grid grid-cols-2 gap-6 py-2 md:grid-cols-4">
          <Digit
            label={tr("Spending")}
            value={fmtEuro(spending)}
            sub={
              <>
                {trx(
                  "average {0} per {1} · {2}",
                  fmtEuro(perMonth(spending)),
                  monthWord,
                  <Comparison now={perMonth(spending)} normal={normalOut} moreIsGood={false} />,
                )}
              </>
            }
          />
          <Digit
            label={tr("Income")}
            value={fmtEuro(income)}
            sub={<>{trx("{0}/mo · {1}", fmtEuro(perMonth(income)), <Comparison now={perMonth(income)} normal={normalIn} moreIsGood />)}</>}
          />
          <Digit
            label={tr("Left over")}
            value={fmtEuro(income - spending)}
            sub={
              normalIn !== null && normalOut !== null ? tr("usually {0}/mo", fmtEuro(normalIn - normalOut)) : tr("income minus spending")
            }
          />
          <Digit
            label={tr("Savings rate")}
            value={income > 0 ? `${(((income - spending) / income) * 100).toLocaleString(intlLocale, { maximumFractionDigits: 0 })}%` : "–"}
            sub={
              normalIn && normalOut !== null && normalIn > 0
                ? tr("usually {0}%", (((normalIn - normalOut) / normalIn) * 100).toLocaleString(intlLocale, { maximumFractionDigits: 0 }))
                : tr("share of your income that was left")
            }
          />
        </div>
        {edit && (
          <p className="pt-2 text-xs text-ink-muted">
            {tr(
              "Put charts in the order you want with ↑ and ↓, or hide them. Per chart you set with ⚙ what it shows. It is saved with your account.",
            )}
          </p>
        )}
        {saveError && (
          <p role="alert" className="pt-2 text-xs" style={{ color: "var(--text-loss)" }}>
            {tr("Your chart layout could not be saved. Change a setting to try again.")}
          </p>
        )}
      </Section>

      {visible.map((g, k) => {
        // Both cards share the width when they are side by side. When hidden or moved
        // each card stays usable on its own.
        if (g.id === "top" && visible[k - 1]?.id === "fixedcosts") return null;
        if (g.id === "fixedcosts" && visible[k + 1]?.id === "top") {
          return (
            <div key="fixed-and-variable-items" className="spending-items grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
              {chart(g, k)}
              {chart(visible[k + 1], k + 1)}
            </div>
          );
        }
        return chart(g, k);
      })}

      {edit && (
        <Section
          label={tr("Hidden charts")}
          action={
            <Button size="sm" variant="ghost" onClick={restore}>
              {tr("Restore default")}
            </Button>
          }
        >
          {hidden.length === 0 ? (
            <p className="text-xs text-ink-muted">{tr("Everything is shown.")}</p>
          ) : (
            <ul className="flex flex-col">
              {hidden.map((g) => (
                <li
                  key={g.id}
                  className="flex items-center justify-between py-2 text-[13px]"
                  style={{ borderTop: "1px solid var(--rule)" }}
                >
                  {TITLES[g.id]}
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => saveItems(items.map((x) => (x.id === g.id ? { ...x, visible: true } : x)))}
                  >
                    {tr("Show")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </div>
  );
}

export default function SpendingPage() {
  // The filters are in the address bar; Next only reads that in the browser.
  return (
    <Suspense fallback={<div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />}>
      <Overview />
    </Suspense>
  );
}
