"use client";

// Are you on track? Your spending of this (salary) month added up day by day,
// next to what you had normally spent by that day. That way you see halfway
// through the month already whether you are above it, and where you end up at
// this pace.
//
// The month is the one in the bar at the top (ctx.month): an earlier month shows
// how it went, next to the months before that one.

import LineChart from "@trackerai/ui/charts/LineChart";
import { fmtDayMonth, fmtEuro } from "@/lib/format";
import { dayNumber, isoDay } from "@/lib/timeline";
import { today } from "@/lib/money";
import { ChartCard, MonthSetting, Setting, monthName, monthsUntil, nameKey, percent, type ChartProps } from "./base";
import { tr, trx } from "@/lib/i18n";

export const DEFAULT = { compare: "6", spending: "everything" };

export default function OnTrack({ ctx, inst, put, editing }: ChartProps) {
  const i = { ...DEFAULT, ...inst };
  const month = ctx.month;
  const final = month.end < today() ? month.end : today();
  const earlier = monthsUntil(isoDay(dayNumber(month.start) - 1), ctx.boundaries, Number(i.compare));
  const counts = (name: string) => {
    const is_fixed = ctx.fixedNames.has(nameKey(name));
    return i.spending === "everything" || (i.spending === "is_fixed" ? is_fixed : !is_fixed);
  };

  // Added up per day, from the start of every month.
  const cumulative = (m: { start: string; end: string }, end: string) => {
    const length = dayNumber(m.end) - dayNumber(m.start) + 1;
    const perDay = new Array(length).fill(0);
    for (const r of ctx.allRows) {
      if (r.type !== "EXPENSE" || r.date < m.start || r.date > end || !counts(r.name)) continue;
      perDay[dayNumber(r.date) - dayNumber(m.start)] += r.amount;
    }
    let s = 0;
    return perDay.map((w) => (s += w));
  };

  const length = dayNumber(month.end) - dayNumber(month.start) + 1;
  const days = Math.min(length, dayNumber(final) - dayNumber(month.start) + 1);
  const now = cumulative(month, final).slice(0, days);
  const first = ctx.allRows.reduce((d, r) => (r.date < d ? r.date : d), today());
  const series_list = earlier.filter((m) => m.start >= first && m.end < month.start).map((m) => cumulative(m, m.end));
  const normal = series_list.length
    ? Array.from({ length: length }, (_, k) => series_list.reduce((a, r) => a + r[Math.min(k, r.length - 1)], 0) / series_list.length)
    : [];

  const todayNow = now[now.length - 1] ?? 0;
  const todayNormal = normal[days - 1] ?? 0;
  const normalEnd = normal[normal.length - 1] ?? 0;
  const difference = todayNormal ? ((todayNow - todayNormal) / todayNormal) * 100 : null;
  const expected = todayNormal ? (todayNow / todayNormal) * normalEnd : null;
  const date = (k: number) => isoDay(dayNumber(month.start) + k);

  const change = (d: number) => (
    <span className="num" style={{ color: d > 5 ? "var(--text-loss)" : d < -5 ? "var(--text-gain)" : undefined }}>
      ({d >= 0 ? "+" : "−"}
      {percent(Math.abs(d))})
    </span>
  );
  const title = ctx.running ? tr("Are you on track?") : tr("On track in {0}?", monthName(month.key));
  const settings = (
    <>
      <MonthSetting ctx={ctx} />
      <Setting
        label={tr("Compare with")}
        value={i.compare}
        onChange={(w) => put("compare", w)}
        options={[
          ["3", tr("3 months")],
          ["6", tr("6 months")],
          ["12", tr("12 months")],
        ]}
      />
      <Setting
        label={tr("Spending")}
        value={i.spending}
        onChange={(w) => put("spending", w)}
        options={[
          ["everything", tr("Everything")],
          ["variable", tr("Only variable")],
          ["is_fixed", tr("Only fixed")],
        ]}
      />
    </>
  );

  return (
    <ChartCard
      title={title}
      editing={editing}
      settings={settings}
      meta={
        <span className="num text-xs text-ink-muted">
          {fmtDayMonth(month.start)} – {fmtDayMonth(month.end)}
        </span>
      }
      info={
        <>
          {trx(
            "Your spending in the {0} from {1} up to and including {2}, added up day by day, next to your normal {3}: the average of the {4} {5} before.{6}",
            ctx.monthWord,
            fmtDayMonth(month.start),
            fmtDayMonth(month.end),
            ctx.monthWord,
            i.compare,
            ctx.boundaries ? tr("salary months") : tr("months"),
            i.spending !== "everything"
              ? tr(" Only {0}.", i.spending === "is_fixed" ? tr("recognised fixed costs") : tr("variable spending"))
              : "",
          )}
        </>
      }
    >
      {i.spending === "is_fixed" && ctx.fixedNames.size === 0 ? (
        <p className="py-4 text-sm text-ink-muted">{tr("No fixed costs recognised yet to compare.")}</p>
      ) : series_list.length === 0 ? (
        <p className="py-4 text-sm text-ink-muted">{tr("No earlier months to compare with yet.")}</p>
      ) : (
        <>
          <p className="pb-3 text-sm">
            {trx(
              "Up to and including {0}: {1} spent{2}.{3}",
              fmtDayMonth(final),
              <b className="num">{fmtEuro(todayNow)}</b>,
              difference !== null && (
                <>
                  {" "}
                  {days < length
                    ? trx("(usually around this day {0} {1})", <span className="num">{fmtEuro(todayNormal)}</span>, change(difference))
                    : trx("(usually {0} {1})", <span className="num">{fmtEuro(todayNormal)}</span>, change(difference))}
                </>
              ),
              expected !== null && days < length && (
                <span className="text-ink-muted">
                  {" "}
                  {trx(
                    "At this pace you'll end up around {0}; usually {1}.",
                    <span className="num">{fmtEuro(expected)}</span>,
                    <span className="num">{fmtEuro(normalEnd)}</span>,
                  )}
                </span>
              ),
            )}
          </p>
          <LineChart
            format={fmtEuro}
            ariaLabel={tr("Spending in {0}, added up, next to a normal month", monthName(month.key))}
            height={230}
            xFormat={(d) => fmtDayMonth(d)}
            series={[
              { label: tr("Usual"), colour: "var(--chart-2)", dash: "dashed", points: normal.map((w, k) => ({ d: date(k), v: w })) },
              {
                label: ctx.running ? tr("This month") : monthName(month.key),
                colour: "var(--chart-1)",
                points: now.map((w, k) => ({ d: date(k), v: w })),
              },
            ]}
          />
        </>
      )}
    </ChartCard>
  );
}
