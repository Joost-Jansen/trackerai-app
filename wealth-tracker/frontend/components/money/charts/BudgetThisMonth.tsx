"use client";

// Budget this month: per main category what you spent this (salary) month, next
// to the budget you set for it under Budget. Compact: one thin bar per group,
// with a mark where you would be on this day of the month if you spent evenly.
// Beyond the budget the bar turns red.
//
// Budgets are per main category (budget.py): planning ten groups you keep up,
// forty categories you do not. They apply to all your accounts, so independent of
// the filters at the top. The month is the one in the bar at the top (ctx.month).

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDayMonth, fmtEuro } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { dayNumber } from "@/lib/timeline";
import { today, type BudgetOverview } from "@/lib/money";
import { ChartCard, MonthSetting, Setting, monthName, percent, TipCard, useTip, type ChartProps } from "./base";
import { tr, trx } from "@/lib/i18n";

export const DEFAULT = { show: "budget" };
// This much faster than planned (as a share of the budget) is worth mentioning.
const MARGIN = 0.05;

export default function BudgetThisMonth({ ctx, inst, put, editing }: ChartProps) {
  const i = { ...DEFAULT, ...inst };
  const { tip, props } = useTip();
  // Only the current month has a pace — a past month is done.
  const { month, running } = ctx;
  // Enough months back to reach the chosen one; one extra for a month without any spending.
  const back = ctx.monthChoices.length - 1 - ctx.monthChoices.indexOf(month);
  const n = Math.min(120, Math.max(4, back + 2));
  const q = useQuery({
    queryKey: ["budget", "this-month", n],
    queryFn: () => api.get<BudgetOverview>(`/api/budget?months=${n}`),
  });
  const length = dayNumber(month.end) - dayNumber(month.start) + 1;
  const day = running ? Math.min(length, dayNumber(today()) - dayNumber(month.start) + 1) : length;
  const pace = day / length;
  const end = month.end < today() ? month.end : today();
  const word = ctx.monthWord;
  const title = running ? tr("Budget this month") : tr("Budget {0}", monthName(month.key));

  // Net, as with Budget: a Tikkie on "Cafe & uitgaan" counts against the drinks.
  // `back` is that part, so you see why a group comes out low or even below zero.
  const allGroups = (q.data?.groups ?? []).map((g) => ({
    group_name: g.group_name, budget: g.budget, off: g.actual[month.key] ?? 0, back: g.back?.[month.key] ?? 0,
    // Expected up to today. The backend counts recognised fixed costs on their own
    // day (rent in one go); without that number simply the pace.
    expected: g.budget === null ? null
      : running && q.data?.current === month.key && g.expected != null ? g.expected : g.budget * pace,
  }));
  const withBudget = allGroups.filter((g) => g.budget);
  const rows = i.show === "all" ? allGroups.filter((g) => g.budget || g.off !== 0 || g.back > 0) : withBudget;
  const withBack = rows.filter((g) => g.back > 0);
  const budgetTotal = withBudget.reduce((a, g) => a + (g.budget ?? 0), 0);
  const fromTotal = withBudget.reduce((a, g) => a + g.off, 0);
  const expectedTotal = withBudget.reduce((a, g) => a + (g.expected ?? 0), 0);
  const quick = budgetTotal > 0 && fromTotal > expectedTotal + MARGIN * budgetTotal;
  const max = Math.max(1, ...rows.map((g) => Math.max(g.budget ?? 0, g.off)));

  return (
    <ChartCard title={title} editing={editing}
      settings={<>
        <MonthSetting ctx={ctx} />
        <Setting label={tr("Display")} value={i.show} onChange={(w) => put("show", w)}
          options={[["budget", tr("With budget")], ["all", tr("All main categories")]]} />
      </>}
      meta={<span className="num text-xs text-ink-muted">
        {fmtDayMonth(month.start)} – {fmtDayMonth(month.end)}{running && withBudget.length > 0 ? tr(" · day {0} of {1}", day, length) : ""}
      </span>}
      info={<>{trx("What you spent in this {0} ({1} – {2}) per main category, next to your budget. In the current {3} each bar has a marker: what you expect to have spent by today. Fixed costs the app recognises in your transactions (every month, about the same amount) count on the day they usually go out; the rest of the budget spread evenly over the {4}. If the bar is past the marker, you're spending faster than expected. Refunds on a group (a Tikkie, a return) are deducted from the spending. Which {5} you see you choose in the bar at the top or at Set up: it's the same for every card about one month. You set budgets at Budget; they apply to all your accounts, regardless of the filters at the top.", word, fmtDayMonth(month.start), fmtDayMonth(month.end), word, word, word)}</>}>
      {q.isLoading ? <p className="text-xs text-ink-muted">{tr("Loading…")}</p> : withBudget.length === 0 && i.show === "budget" ? (
        <p className="py-2 text-sm text-ink-muted">{trx("No budget yet. Set a monthly budget per main category at {0}. What you spend in a normal month is there as a suggestion.", <Link href="/spending/budget" className="underline underline-offset-4">Budget</Link>)}</p>
      ) : (
        <>
          {withBudget.length > 0 && (
            <p className="pb-2 text-sm">{trx("{0} of {1} spent · {2}{3}", <b className="num">{fmtEuro(fromTotal)}</b>, <span className="num">{fmtEuro(budgetTotal)}</span>, <span style={{ color: fromTotal > budgetTotal ? "var(--text-loss)" : undefined }}>
                {fromTotal > budgetTotal ? tr("{0} over budget", fmtEuro(fromTotal - budgetTotal)) : tr("{0} left", fmtEuro(budgetTotal - fromTotal))}
              </span>, running && quick && fromTotal <= budgetTotal && <span className="text-ink-muted">{" "}{tr("(faster than planned)")}</span>)}</p>
          )}
          <ul className="relative flex flex-col" data-tip-area>
            {rows.map((g) => {
              const remaining = g.budget !== null && g.off > g.budget;
              return (
                <li key={g.group_name} style={{ borderTop: "1px solid var(--rule)" }}>
                  <button type="button"
                    className="grid w-full grid-cols-[minmax(6.5rem,10rem)_1fr_12rem] items-center gap-3 py-1.5 text-left text-[12.5px] hover:bg-surface-2 focus:outline-none focus-visible:bg-surface-2"
                    {...props(g.group_name, {
                      title: g.group_name,
                      rules: [
                        ...(g.back > 0 ? [
                          { label: tr("spent"), value: fmtEuro(g.off + g.back) },
                          { label: tr("paid back"), value: trueMinus(fmtEuro(-g.back)) },
                          { label: "net", value: trueMinus(fmtEuro(g.off)), strong: true },
                        ] : [{ label: tr("spent"), value: fmtEuro(g.off), strong: true }]),
                        ...(g.budget !== null ? [
                          { label: "budget", value: fmtEuro(g.budget) },
                          { label: remaining ? tr("over budget") : tr("left to spend"), value: fmtEuro(Math.abs(g.budget - g.off)) },
                          ...(running ? [{ label: tr("expected by today"), value: fmtEuro(g.expected ?? 0) }] : []),
                        ] : [{ label: "budget", value: tr("none") }]),
                      ],
                      foot: tr("Click for the transactions of this {0}", word),
                    }, () => ctx.dest({ start: month.start, end, categories: ctx.categoriesOf(g.group_name) }))}>
                    <span className="truncate">{g.group_name}</span>
                    {g.budget !== null ? (
                      <span className="relative h-2 rounded-full" style={{ background: "var(--surface-inset)" }}>
                        <span className="absolute inset-y-0 left-0 rounded-full"
                          style={{ width: `${Math.max(0, Math.min(100, (g.off / g.budget) * 100))}%`, background: remaining ? "var(--text-loss)" : "var(--cat-2)" }} />
                        {running && <span aria-hidden className="absolute -inset-y-1 w-px" style={{ left: `${Math.min(100, ((g.expected ?? 0) / g.budget) * 100)}%`, background: "var(--text-primary)", opacity: 0.55 }} />}
                      </span>
                    ) : (
                      <span className="relative h-2 rounded-full" style={{ background: "var(--surface-inset)" }}>
                        <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(0, (g.off / max) * 100)}%`, background: "var(--cat-other)" }} />
                      </span>
                    )}
                    <span className="num whitespace-nowrap text-right text-xs">
                      {trueMinus(fmtEuro(g.off))}
                      {g.budget !== null ? (
                        <span style={{ color: remaining ? "var(--text-loss)" : "var(--text-muted)" }}>
                          {" "}/ {fmtEuro(g.budget)}{remaining ? ` · +${percent(((g.off - g.budget) / g.budget) * 100)}` : ""}
                        </span>
                      ) : <span className="text-ink-muted">{" "}{tr("· no budget")}</span>}
                    </span>
                  </button>
                </li>
              );
            })}
            <TipCard tip={tip} />
          </ul>
          {running && rows.some((g) => g.budget !== null) && (
            <p className="pt-2 text-xs text-ink-muted">{trx("The marker is what you expect to have spent by today: recognised fixed costs (rent, subscriptions) on the day they usually go out, the rest of the budget evenly over the {0}. Blue past the marker = faster than expected.", word)}</p>
          )}
          {withBack.length > 0 && (
            <p className="pt-1 text-xs text-ink-muted">{trx("Paid back (such as a Tikkie or return), already deducted: {0}", withBack.map((g, k) => (
                <span key={g.group_name}>{k > 0 && " · "}{g.group_name} <span className="num">{fmtEuro(g.back)}</span></span>
              )))}</p>
          )}
        </>
      )}
    </ChartCard>
  );
}
