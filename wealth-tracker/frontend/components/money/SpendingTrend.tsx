"use client";
import { ChartCard, Setting, type Editing } from "@/components/money/charts/base";
import LineChart from "@trackerai/ui/charts/LineChart";
import { fmtEuro, fmtMonth } from "@/lib/format";
import type { Transaction } from "@/lib/money";
import { monthKey } from "@/lib/month-periods";
import { currentCode } from "@/lib/timeline";
import { tr, trx } from "@/lib/i18n";

/** `boundaries`: with the salary month a month runs from salary to salary. */
export default function SpendingTrend({ rows, boundaries, unit: savedUnit = "month", onUnitChange, editing }: {
  rows: Transaction[]; boundaries?: string[] | null; unit?: string; onUnitChange?: (value: string) => void; editing?: Editing;
}) {
  const unit = currentCode(savedUnit); // "Maand"/"Jaar" from before the English rename
  const grouped = new Map<string, { income: number; expense: number; count: number }>();
  for (const r of rows) {
    if (r.type !== "INCOME" && r.type !== "EXPENSE") continue;
    const key = unit === "year" ? r.date.slice(0, 4) : monthKey(r.date, boundaries ?? null);
    if (!grouped.has(key)) grouped.set(key, { income: 0, expense: 0, count: 0 });
    const p = grouped.get(key)!;
    p.count++;
    if (r.type === "INCOME") p.income -= r.amount;
    else p.expense += r.amount;
  }
  const points = [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  const date = (key: string) => unit === "year" ? `${key}-01-01` : `${key}-01`;
  return <ChartCard title={tr("Income and spending over time")} editing={editing}
    settings={<Setting label={tr("Summarise per")} value={unit} onChange={(w) => onUnitChange?.(w)} options={[["month", tr("Month")], ["year", tr("Year")]]} />}>
    <p className="pb-3 text-xs text-ink-muted">{trx("Only booked amounts in the chosen period and accounts. Incomplete months and missing imports can affect the picture. Internal transfers don't count. Periods without bookings aren't shown.{0}", boundaries && unit === "month" && tr(" A month runs from salary to salary and is named after the month in which it starts."))}</p>
    <div className="mb-3 flex gap-5 text-xs text-ink-muted"><span>{tr("━ Income")}</span><span>{tr("┄ Spending")}</span></div>
    {points.length > 1 ? <LineChart endLabels={false} baseline={0} format={fmtEuro}
      xFormat={(d) => (unit === "year" ? d.slice(0, 4) : `${fmtMonth(d)} '${d.slice(2, 4)}`)} ariaLabel={tr("Income and spending per {0}", unit === "year" ? tr("year") : tr("month"))} series={[
      { label: tr("Income"), colour: "var(--chart-5)", points: points.map(([key,p]) => ({ d: date(key), v: p.income })) },
      { label: tr("Spending"), colour: "var(--chart-3)", dash: "dashed", points: points.map(([key,p]) => ({ d: date(key), v: p.expense })) },
    ]} /> : <p className="py-4 text-sm text-ink-muted">{trx("Choose a longer period to compare different {0}.", unit === "year" ? tr("years") : tr("months"))}</p>}
    <details className="pt-3 text-xs">
      <summary className="cursor-pointer text-ink-muted">{tr("Amounts and what's left as a table")}</summary>
      <div className="overflow-x-auto"><table className="mt-3 w-full text-right num"><thead><tr><th className="text-left">{unit === "year" ? tr("Year") : tr("Month")}</th><th>{tr("Income")}</th><th>{tr("Spending")}</th><th>{tr("Left over")}</th></tr></thead><tbody>
        {points.map(([key,p]) => <tr key={key} className="border-t" style={{borderColor:"var(--rule)"}}><td className="py-2 text-left">{key}</td><td>{fmtEuro(p.income)}</td><td>{fmtEuro(p.expense)}</td><td>{fmtEuro(p.income-p.expense)}</td></tr>)}
      </tbody></table></div>
    </details>
  </ChartCard>;
}
