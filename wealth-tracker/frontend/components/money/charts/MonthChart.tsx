"use client";

// Per month (or salary month): your spending, stacked per group, category or
// counterparty — or as lines. Pointing shows the amount, the share of that month
// and the average; clicking opens that month under Transactions.

import LineChart from "@trackerai/ui/charts/LineChart";
import { fmtEuro } from "@/lib/format";
import {
  filterFor,
  ChartCard,
  Setting,
  coloursFor,
  Legend,
  monthsUntil,
  monthLabel,
  MISC,
  percent,
  keyOf,
  TipCard,
  useTip,
  orderOf,
  type ChartProps,
  type Distribution,
} from "./base";
import { tr, trx } from "@/lib/i18n";

export const DEFAULT = { divide: "groups", measure: "amount", view: "gestapeld", months: "12", top: "6" };

export default function MonthChart({ ctx, inst, put, editing }: ChartProps) {
  const i = { ...DEFAULT, ...inst };
  const { tip, props } = useTip();
  const v = i.divide as Distribution;
  const months = monthsUntil(ctx.time_window.to, ctx.boundaries, Number(i.months));

  const perMonth = new Map<string, Map<string, number>>();
  const perName = new Map<string, number>();
  for (const r of ctx.allRows) {
    if (r.type !== "EXPENSE") continue;
    const m = months.find((x) => r.date >= x.start && r.date <= x.end);
    if (!m) continue;
    const k = keyOf(r, v, ctx);
    const row = perMonth.get(m.key) ?? new Map<string, number>();
    row.set(k, (row.get(k) ?? 0) + r.amount);
    perMonth.set(m.key, row);
    perName.set(k, (perName.get(k) ?? 0) + r.amount);
  }
  const top = [...perName.entries()]
    .filter(([, w]) => w > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, Number(i.top))
    .map(([k]) => k);
  const colours = coloursFor(top, orderOf(v, ctx));
  const names = [...top].sort((a, b) => [...colours.keys()].indexOf(a) - [...colours.keys()].indexOf(b));
  if (perName.size > top.length) names.push(MISC);

  const value = (m: string, n: string) => {
    const row = perMonth.get(m);
    if (!row) return 0;
    if (n !== MISC) return Math.max(0, row.get(n) ?? 0);
    return [...row.entries()].filter(([k]) => !top.includes(k)).reduce((a, [, w]) => a + Math.max(0, w), 0);
  };
  const monthTotal = (m: string) => names.reduce((a, n) => a + value(m, n), 0);
  const show = (m: string, n: string) =>
    i.measure === "percent" ? (monthTotal(m) ? (value(m, n) / monthTotal(m)) * 100 : 0) : value(m, n);
  const fmt = i.measure === "percent" ? percent : fmtEuro;
  const average = (n: string) => months.reduce((a, m) => a + value(m.key, n), 0) / Math.max(1, months.length);
  const max = Math.max(1, ...months.map((m) => (i.measure === "percent" ? 100 : monthTotal(m.key))));
  const toMonth = (m: { start: string; end: string }, n: string) => ctx.dest({ start: m.start, end: m.end, ...filterFor(n, v, ctx) });

  const settings = (
    <>
      <Setting
        label={tr("Split by")}
        value={i.divide}
        onChange={(w) => put("divide", w)}
        options={[
          ["groups", tr("Groups")],
          ["categories", tr("Categories")],
          ["counterparties", tr("Counterparties")],
        ]}
      />
      <Setting
        label={tr("Measure in")}
        value={i.measure}
        onChange={(w) => put("measure", w)}
        options={[
          ["amount", "€"],
          ["percent", tr("% of the month")],
        ]}
      />
      <Setting
        label={tr("View")}
        value={i.view}
        onChange={(w) => put("view", w)}
        options={[
          ["gestapeld", tr("Stacked")],
          ["lijnen", tr("Lines")],
        ]}
      />
      <Setting
        label={tr("Months")}
        value={i.months}
        onChange={(w) => put("months", w)}
        options={[
          ["6", "6"],
          ["12", "12"],
          ["24", "24"],
        ]}
      />
      <Setting
        label={tr("Own colour for")}
        value={i.top}
        onChange={(w) => put("top", w)}
        options={[
          ["3", "top 3"],
          ["6", "top 6"],
        ]}
      />
    </>
  );

  return (
    <ChartCard
      title={ctx.boundaries ? tr("Per salary month") : tr("Per month")}
      editing={editing}
      settings={settings}
      info={
        <>
          {trx(
            "Your spending per {0}, split by {1}; the months in your period fill the view. Point at a piece for the amount, click to open those transactions.",
            ctx.monthWord,
            i.divide === "groups" ? "group_name" : i.divide === "categories" ? "category" : "counterparty",
          )}
        </>
      }
    >
      {names.length === 0 ? (
        <p className="py-4 text-sm text-ink-muted">{tr("No spending in these months.")}</p>
      ) : i.view === "lijnen" ? (
        <LineChart
          format={fmt}
          ariaLabel={tr("Spending per month")}
          height={240}
          xFormat={(d) => {
            const k = months.findIndex((m) => m.start === d);
            return k === -1 ? d : monthLabel(months[k].key, k, months);
          }}
          series={names.map((n) => ({
            label: n,
            colour: colours.get(n) ?? "var(--cat-other)",
            points: months.map((m) => ({ d: m.start, v: show(m.key, n) })),
          }))}
        />
      ) : (
        <div className="relative flex flex-col gap-2" data-tip-area>
          <div className="flex h-56 items-end gap-1.5" role="img" aria-label={tr("Spending per month, stacked")}>
            {months.map((m, mi) => {
              const t = i.measure === "percent" ? 100 : monthTotal(m.key);
              const within = m.end >= ctx.time_window.from && m.start <= ctx.time_window.to;
              return (
                <div key={m.key} className="flex h-full min-w-0 flex-1 flex-col justify-end" style={{ opacity: within ? 1 : 0.5 }}>
                  <div className="flex flex-col-reverse overflow-hidden rounded-t-[4px]" style={{ height: `${(t / max) * 100}%` }}>
                    {names.map((n) => {
                      const w = show(m.key, n);
                      if (w <= 0) return null;
                      const share = monthTotal(m.key) ? (value(m.key, n) / monthTotal(m.key)) * 100 : 0;
                      return (
                        <button
                          key={n}
                          type="button"
                          aria-label={`${n}, ${monthLabel(m.key, mi, months)}: ${fmt(w)}`}
                          className="w-full transition-[filter] hover:brightness-110 focus:outline-none focus-visible:brightness-110"
                          style={{ height: `${(w / t) * 100}%`, background: colours.get(n), borderTop: "2px solid var(--surface-page)" }}
                          {...props(
                            `${m.key}|${n}`,
                            {
                              title: `${n} · ${monthLabel(m.key, 0, [m])}`,
                              rules: [
                                { label: tr("spent"), value: fmtEuro(value(m.key, n)), colour: colours.get(n), strong: true },
                                { label: tr("share of the month"), value: percent(share) },
                                { label: tr("average per {0}", ctx.monthWord), value: fmtEuro(average(n)) },
                                { label: tr("whole month"), value: fmtEuro(monthTotal(m.key)) },
                              ],
                              foot: n === MISC ? tr("Click for all transactions of that month") : tr("Click for the transactions"),
                            },
                            () => toMonth(m, n),
                          )}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex gap-1.5">
            {months.map((m, mi) => (
              <span key={m.key} className="min-w-0 flex-1 truncate text-center text-[10px] text-ink-muted">
                {monthLabel(m.key, mi, months)}
              </span>
            ))}
          </div>
          <Legend names={names} colours={colours} />
          <TipCard tip={tip} />
        </div>
      )}
    </ChartCard>
  );
}
