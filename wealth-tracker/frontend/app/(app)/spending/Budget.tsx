"use client";

// Budget — the month overview from the old spreadsheet: per group what you
// wanted to spend next to what it became, the difference, and how much is used.
//
// Three agreements you see back here (the arithmetic is in budget.py):
//
//   * **No budget is not zero.** A group without a budget has no difference and
//     no percentage; otherwise everything you did not plan is in the red.
//   * **The median as a suggestion.** What you spent in a normal month, over the
//     last complete months. One click sets it as the budget.
//   * **An incomplete month is hatched.** The current month, or a month for
//     which not every account has an export, is not an outcome yet.

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtEuro, fmtMonth } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { Button, Input, Section, Select } from "@/components/ds";
import Bars, { type BarDatum } from "@trackerai/ui/charts/Bars";
import { readAmount, today, type BudgetOverview, type Category } from "@/lib/money";
import { boundariesOf, monthPeriod, useMonthPeriods } from "@/lib/month-periods";
import { toTransactions } from "@/lib/spending-filters";
import { tr, trx } from "@/lib/i18n";

const WITHIN = "var(--chart-3)";
const ABOVE_IT = "var(--text-loss)";

/**
 * A median as budget: rounded up to a tenner, so it is a number you would pick
 *  yourself and a normal month falls just within it.
 */
const asBudget = (median: number) => Math.ceil(median / 10) * 10;

/** "Sep 2025": across thirteen months the same month occurs twice. */
const monthYear = (m: string) => `${fmtMonth(m)} ${m.slice(0, 4)}`;

function useSaveBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ group_name, amount }: { group_name: string; amount: number | null }) =>
      api.put<BudgetOverview>(`/api/budget/${encodeURIComponent(group_name)}`, { amount }),
    onSuccess: (data) => qc.setQueryData(["budget"], data),
  });
}

/** The budget field of one group. Saves on blur or Enter; empty removes it. */
function BudgetField({ group_name, budget }: { group_name: string; budget: number | null }) {
  const [text, setText] = useState(budget != null ? String(budget).replace(".", ",") : "");
  const [error, setError] = useState<string | null>(null);
  const put = useSaveBudget();

  const save = () => {
    const empty = text.trim() === "";
    const amount = empty ? null : readAmount(text);
    if (!empty && (amount === null || amount < 0)) {
      setError(tr("No amount"));
      return;
    }
    setError(null);
    if (amount === budget || (empty && budget === null)) return;
    put.mutate({ group_name, amount });
  };

  return (
    <Input
      aria-label={tr("Budget per month for {0}", group_name)}
      inputMode="decimal"
      placeholder="–"
      className="w-24 text-right"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      error={error ?? (put.isError ? (put.error as ApiError).message : undefined)}
    />
  );
}

function Percentage({ actual, budget }: { actual: number; budget: number | null }) {
  if (budget == null || budget <= 0) return <span className="text-ink-muted">–</span>;
  const part = Math.round((actual / budget) * 100);
  return (
    <span className="num" style={part > 100 ? { color: ABOVE_IT } : undefined}>
      {part}%
    </span>
  );
}

export default function Budget() {
  const [choice, setChoice] = useState<string | null>(null);
  const put = useSaveBudget();
  const overview = useQuery({
    queryKey: ["budget"],
    queryFn: () => api.get<BudgetOverview>("/api/budget?months=13"),
  });
  const taxonomy = useQuery({ queryKey: ["categories"], queryFn: () => api.get<{ categories: Category[] }>("/api/categories") });
  const boundaries = boundariesOf(useMonthPeriods().data);

  const data = overview.data;
  if (!data || data.months.length === 0) return null;

  const { months, complete, groups, total } = data;
  const month = choice && months.includes(choice) ? choice : months[months.length - 1];
  const budget = total.budget;

  const bars: BarDatum[] = months.map((m) => {
    const w = Math.max(total.actual[m] ?? 0, 0);
    const estimate = !complete[m];
    const segments =
      budget == null
        ? [{ key: "spending", value: w, colour: WITHIN, estimate: estimate }]
        : [
            { key: "within", value: Math.min(w, budget), colour: WITHIN, estimate: estimate },
            { key: "erboven", value: Math.max(0, w - budget), colour: ABOVE_IT, estimate: estimate },
          ];
    return {
      key: m,
      label: fmtMonth(m),
      title: `${monthYear(m)}${estimate ? tr(" (not complete yet)") : ""}`,
      segments,
      note: budget == null ? undefined : `budget ${fmtEuro(budget)}`,
    };
  });

  const completeMonths = months.filter((m) => complete[m]);
  const within = budget == null ? 0 : completeMonths.filter((m) => (total.actual[m] ?? 0) <= budget).length;
  const summary =
    budget == null
      ? tr("Spending per month. Set a budget per group below, then you see where it went over.")
      : tr("Budget {0} per month; {1} of the {2} complete months within it.", fmtEuro(budget), within, completeMonths.length);

  const totalActual = total.actual[month] ?? 0;

  // Clicking through to Transactions: this month, the group's categories.
  const period = monthPeriod(month, boundaries);
  const end = period.end < today() ? period.end : today();
  const categories = taxonomy.data?.categories ?? [];
  const toGroup = (group_name: string) =>
    toTransactions({ start: period.start, end, categories: categories.filter((c) => c.group_name === group_name).map((c) => c.name) });

  return (
    <Section
      label="Budget"
      meta={budget != null ? <span className="num">{trx("{0} per month", fmtEuro(budget))}</span> : undefined}
      info={
        <>{trx("Per group what you want to spend per month, next to what it became. The {0} is what you spent in a normal month, over the last year of complete months, a good first budget. Hatched months aren't complete yet: the current month, or a month for which not every account has an export. Transfers to your own accounts don't count. What comes back on a group (a Tikkie, a return) is taken off the spending; how much that was is shown under the amount. Click a bar to choose that month, and a group to see the transactions in it.", <strong>{tr("median")}</strong>)}</>
      }
    >
      <Bars
        bars={bars}
        legend={
          budget == null
            ? undefined
            : [
                { key: "within", label: tr("Within budget"), colour: WITHIN },
                { key: "erboven", label: tr("Over budget"), colour: ABOVE_IT },
              ]
        }
        format={(v) => fmtEuro(v)}
        summary={summary}
        labelEvery={2}
        ariaLabel={tr("Spending per month against the budget")}
        onSelect={setChoice}
      />

      <div className="flex flex-wrap items-end justify-between gap-3 pt-5">
        <div className="max-w-[12rem]">
          <Select label={tr("Month")} value={month} onChange={(e) => setChoice(e.target.value)}>
            {[...months].reverse().map((m) => (
              <option key={m} value={m}>
                {monthYear(m)}
                {complete[m] ? "" : tr(" (incomplete)")}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div className="overflow-x-auto pt-3">
        <table className="w-full min-w-[620px] text-[12.5px]">
          <thead>
            <tr className="text-left text-ink-muted">
              <th className="py-1.5 font-normal">{tr("Group")}</th>
              <th className="py-1.5 text-right font-normal">Budget</th>
              <th className="py-1.5 text-right font-normal">{tr("Actual")}</th>
              <th className="py-1.5 text-right font-normal">{tr("Difference")}</th>
              <th className="py-1.5 text-right font-normal">{tr("Of budget")}</th>
              <th className="py-1.5 text-right font-normal">{tr("Median")}</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const actual = g.actual[month] ?? 0;
              const difference = g.budget == null ? null : g.budget - actual;
              return (
                <tr key={g.group_name} style={{ borderTop: "1px solid var(--rule)" }}>
                  <td className="py-1.5 align-middle">
                    {categories.length > 0 ? (
                      <Link href={toGroup(g.group_name)} title={tr("Transactions of {0} in {1}", g.group_name, monthYear(month))}
                        className="underline decoration-[var(--rule)] underline-offset-4 hover:decoration-current">
                        {g.group_name}
                      </Link>
                    ) : g.group_name}
                  </td>
                  <td className="py-1.5 text-right align-middle">
                    <div className="flex justify-end">
                      {/* Rebuild when the budget changes from outside (the median button),
                          otherwise the field shows the old text. */}
                      <BudgetField key={`${g.group_name}:${g.budget}`} group_name={g.group_name} budget={g.budget} />
                    </div>
                  </td>
                  <td className="num py-1.5 text-right align-middle">
                    {trueMinus(fmtEuro(actual))}
                    {/* Netto: wat terugkwam (Tikkie, retour) is er al af. */}
                    {(g.back?.[month] ?? 0) > 0 && (
                      <span className="block text-[11px] text-ink-muted" title={tr("Paid back on this group, already deducted")}>{trx("{0} back", fmtEuro(g.back![month]))}</span>
                    )}
                  </td>
                  <td
                    className="num py-1.5 text-right align-middle"
                    style={difference != null && difference < 0 ? { color: ABOVE_IT } : undefined}
                  >
                    {difference == null ? <span className="text-ink-muted">–</span> : trueMinus(fmtEuro(difference))}
                  </td>
                  <td className="py-1.5 text-right align-middle">
                    <Percentage actual={actual} budget={g.budget} />
                  </td>
                  <td className="num py-1.5 text-right align-middle">
                    {g.median == null ? (
                      <span className="text-ink-muted">–</span>
                    ) : (
                      <span className="inline-flex items-center justify-end gap-2">
                        {fmtEuro(g.median)}
                        {g.budget !== asBudget(g.median) && g.median > 0 && (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={put.isPending}
                            title={tr("Set budget to {0}", fmtEuro(asBudget(g.median)))}
                            onClick={() => put.mutate({ group_name: g.group_name, amount: asBudget(g.median!) })}
                          >{tr("Use")}</Button>
                        )}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
            <tr style={{ borderTop: "1px solid var(--rule-strong, var(--rule))" }} className="font-semibold">
              <td className="py-2">{tr("Total")}</td>
              <td className="num py-2 text-right">{budget == null ? "–" : fmtEuro(budget)}</td>
              <td className="num py-2 text-right">{trueMinus(fmtEuro(totalActual))}</td>
              <td
                className="num py-2 text-right"
                style={budget != null && budget - totalActual < 0 ? { color: ABOVE_IT } : undefined}
              >
                {budget == null ? "–" : trueMinus(fmtEuro(budget - totalActual))}
              </td>
              <td className="py-2 text-right">
                <Percentage actual={totalActual} budget={budget} />
              </td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
    </Section>
  );
}
