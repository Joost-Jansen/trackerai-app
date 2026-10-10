"use client";

// Calendar month or from salary to salary. One choice for the whole app, in
// Settings: Spending, Net worth and Accounts all calculate with the same months.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonthYear } from "@/lib/format";
import { Button, Input, Select, Tabs } from "@/components/ds";
import type { Category } from "@/lib/money";
import { useMonthPeriods, type MonthPeriods } from "@/lib/month-periods";
import { tr, trx } from "@/lib/i18n";

const CALENDAR = tr("Calendar month");
const SALARY = tr("From salary to salary");

function Adjust({ m, onSave, busy }: { m: MonthPeriods; onSave: (v: Record<string, unknown>) => void; busy: boolean }) {
  const [day, setDay] = useState(m.day_configured ? String(m.day_configured) : "");
  const categories = useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<{ categories: Category[] }>("/api/categories"),
  });
  const income = (categories.data?.categories ?? []).filter((c) => c.type === "INCOME");

  return (
    <div className="flex flex-wrap items-end gap-2 pt-2">
      <Select label={tr("Salary is in category")} value={m.category} disabled={busy}
        onChange={(e) => onSave({ category: e.target.value })}>
        {!income.some((c) => c.name === m.category) && <option value={m.category}>{m.category}</option>}
        {income.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
      </Select>
      <Input label={tr("Salary day")} type="number" min={1} max={31} className="w-24"
        placeholder={m.recognised ? String(m.recognised.day) : "21"} value={day} onChange={(e) => setDay(e.target.value)} />
      <Button size="sm" variant="secondary" disabled={busy || !day} onClick={() => onSave({ day: Number(day) })}>{tr("Fix the day")}</Button>
      {m.day_configured && (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setDay(""); onSave({ day: null }); }}>{tr("Recognise again automatically")}</Button>
      )}
    </div>
  );
}

export default function MonthPeriodsChoice() {
  const qc = useQueryClient();
  const q = useMonthPeriods();
  const put = useMutation({
    mutationFn: (fields: Record<string, unknown>) => api.put<MonthPeriods>("/api/month-periods", fields),
    onSuccess: (d) => {
      qc.setQueryData(["month_periods"], d);
      // Every month total, budget and balance difference depends on it.
      qc.invalidateQueries();
    },
  });
  if (!q.data) return null;
  const m = q.data;
  const fmt = (d: string) => fmtDayMonthYear(d);

  let explanation: React.ReactNode;
  if (m.mode === "calendar") {
    explanation = tr("Monthly totals and averages run from the 1st to the last day of the month.");
  } else if (m.active === "calendar") {
    explanation = (
      <span style={{ color: "var(--text-loss)" }}>{trx("No salary recognised yet in the category “{0}”. Label your salary that way, or fix the day yourself below. Until then calendar months count.", m.category)}</span>
    );
  } else {
    explanation = (
      <>{trx("{0}, {1} on a weekend or public holiday{2}. This month runs from {3} up to and including {4}. Applies to monthly totals, averages, budget, net worth per month and debts.", m.day_configured
          ? <>{trx("Salary on day {0} (fixed)", m.day)}</>
          : <>{trx("Your salary usually comes in on day {0}", m.day)}</>, m.shift === "earlier" ? tr("earlier") : tr("later"), m.recognised && <>{" "}{trx("(recognised {0} times, last on {1})", m.recognised.count, fmt(m.recognised.last))}</>, fmt(m.current.start), fmt(m.current.end))}</>
    );
  }

  return (
    <div className="flex flex-col gap-1 pb-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-ink-muted">{tr("A month runs")}</span>
        <Tabs items={[CALENDAR, SALARY]} value={m.mode === "salary" ? SALARY : CALENDAR} variant="segmented"
          ariaLabel={tr("Where a month starts")}
          onChange={(v) => put.mutate({ mode: v === SALARY ? "salary" : "calendar" })} />
      </div>
      <p className="text-xs text-ink-muted">{explanation}</p>
      {m.mode === "salary" && (
        <details className="text-xs">
          <summary className="cursor-pointer text-ink-muted">{tr("Adjust salary day or category")}</summary>
          <Adjust key={`${m.day_configured}-${m.category}`} m={m} onSave={(v) => put.mutate(v)} busy={put.isPending} />
        </details>
      )}
      {put.isError && <p className="text-xs" style={{ color: "var(--text-loss)" }}>{(put.error as ApiError).message}</p>}
    </div>
  );
}
