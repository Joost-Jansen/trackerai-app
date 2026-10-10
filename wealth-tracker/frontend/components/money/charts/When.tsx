"use client";

// When you spend: as a calendar (every day a box, the darker the more), per
// weekday, or per day of the (salary) month. One colour from light to dark: it is
// about how much, not about what.

import { fmtDayMonthYear, fmtEuro, WEEKDAY_ABBR } from "@/lib/format";
import { dayNumber, isoDay } from "@/lib/timeline";
import { today } from "@/lib/money";
import { ChartCard, Setting, nameKey, TipCard, useTip, type ChartProps } from "./base";
import { tr, trx } from "@/lib/i18n";

export const DEFAULT = { view: "calendar", spending: "everything" };
const WEEKDAYS = WEEKDAY_ABBR;
// A calendar of more than this many weeks becomes unreadably narrow.
const MAX_WEEKS = 26;

/** Monday = 0. */
const weekday = (d: string) => (new Date(`${d}T00:00:00Z`).getUTCDay() + 6) % 7;

export default function When({ ctx, inst, put, editing }: ChartProps) {
  const i = { ...DEFAULT, ...inst };
  const { tip, props } = useTip();
  const counts = (name: string) => i.spending === "everything" || !ctx.fixedNames.has(nameKey(name));

  const perDay = new Map<string, { w: number; n: number }>();
  for (const r of ctx.rows) {
    if (r.type !== "EXPENSE" || r.amount <= 0 || !counts(r.name)) continue;
    const c = perDay.get(r.date) ?? { w: 0, n: 0 };
    c.w += r.amount;
    c.n += 1;
    perDay.set(r.date, c);
  }
  const final = ctx.time_window.to < today() ? ctx.time_window.to : today();
  const start = Math.max(dayNumber(ctx.time_window.from), dayNumber(final) - MAX_WEEKS * 7 + 1);
  const days = Array.from({ length: dayNumber(final) - start + 1 }, (_, k) => isoDay(start + k));

  const colour = (w: number, max: number) =>
    w <= 0 ? "var(--surface-inset)" : `color-mix(in oklab, var(--cat-2) ${Math.round(20 + 80 * Math.min(1, w / max))}%, var(--surface-inset))`;
  const toDay = (d: string) => ctx.dest({ start: d, end: d });

  let content: React.ReactNode;
  if (i.view === "calendar") {
    const firstWeekday = weekday(days[0] ?? final);
    const cells: (string | null)[] = [...new Array(firstWeekday).fill(null), ...days];
    const weeks = Math.ceil(cells.length / 7);
    const max = Math.max(1, ...days.map((d) => perDay.get(d)?.w ?? 0));
    content = (
      <div className="flex gap-2">
        <div className="grid grid-rows-7 gap-[3px] pt-0 text-[10px] text-ink-muted">
          {WEEKDAYS.map((d) => <span key={d} className="flex h-[14px] items-center">{d}</span>)}
        </div>
        <div className="grid flex-1 grid-flow-col grid-rows-7 gap-[3px]" style={{ gridTemplateColumns: `repeat(${weeks}, minmax(0, 1fr))` }}>
          {cells.map((d, k) => d === null ? <span key={`leeg${k}`} /> : (
            <button key={d} type="button" aria-label={`${fmtDayMonthYear(d)}: ${fmtEuro(perDay.get(d)?.w ?? 0)}`}
              className="h-[14px] rounded-[3px] focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--text-primary)]"
              style={{ background: colour(perDay.get(d)?.w ?? 0, max) }}
              {...props(d, {
                title: fmtDayMonthYear(d),
                rules: [
                  { label: tr("spent"), value: fmtEuro(perDay.get(d)?.w ?? 0), strong: true },
                  { label: tr("transactions"), value: String(perDay.get(d)?.n ?? 0) },
                ],
                foot: perDay.get(d) ? tr("Click for the transactions of that day") : undefined,
              }, perDay.get(d) ? () => toDay(d) : undefined)} />
          ))}
        </div>
      </div>
    );
  } else {
    // Per weekday or per day of the month: average per time that day occurred.
    const slots = i.view === "weekday" ? 7 : 31;
    const summed = new Array(slots).fill(0);
    const times = new Array(slots).fill(0);
    const spot = (d: string) => {
      if (i.view === "weekday") return weekday(d);
      const boundary = ctx.boundaries ? [...ctx.boundaries].reverse().find((g) => g <= d) : `${d.slice(0, 7)}-01`;
      return Math.min(30, dayNumber(d) - dayNumber(boundary ?? d));
    };
    for (const d of days) {
      const k = spot(d);
      times[k] += 1;
      summed[k] += perDay.get(d)?.w ?? 0;
    }
    const gem = summed.map((s, k) => (times[k] ? s / times[k] : 0));
    const max = Math.max(1, ...gem);
    const label = (k: number) => (i.view === "weekday" ? WEEKDAYS[k] : String(k + 1));
    content = (
      <>
        <div className="flex h-40 items-end gap-[3px]">
          {gem.map((w, k) => (
            <button key={k} type="button" aria-label={`${label(k)}: ${fmtEuro(w)}`}
              className="min-w-0 flex-1 rounded-t-[4px] transition-[filter] hover:brightness-110 focus:outline-none focus-visible:brightness-110"
              style={{ height: `${Math.max(2, (w / max) * 100)}%`, background: "var(--cat-2)" }}
              {...props(String(k), {
                title: i.view === "weekday" ? tr("On {0}", label(k)) : tr("Day {0} of the {1}", k + 1, ctx.monthWord),
                rules: [
                  { label: tr("average spent"), value: fmtEuro(w), strong: true },
                  { label: tr("times in the period"), value: String(times[k]) },
                ],
              })} />
          ))}
        </div>
        <div className="flex gap-[3px] pt-1">
          {gem.map((_, k) => (
            <span key={k} className="min-w-0 flex-1 text-center text-[10px] text-ink-muted">
              {i.view === "weekday" || k === 0 || (k + 1) % 5 === 0 ? label(k) : ""}
            </span>
          ))}
        </div>
      </>
    );
  }

  return (
    <ChartCard title={tr("When you spend")} editing={editing}
      settings={<>
        <Setting label={tr("View")} value={i.view} onChange={(w) => put("view", w)}
          options={[["calendar", tr("Calendar")], ["weekday", tr("Per weekday")], ["maanddag", ctx.boundaries ? tr("Per day after salary") : tr("Per day of the month")]]} />
        <Setting label={tr("Spending")} value={i.spending} onChange={(w) => put("spending", w)} options={[["everything", tr("Everything")], ["variable", tr("Without fixed costs")]]} />
      </>}
      info={<>{i.view === "calendar"
        ? <>{tr("A box for each day of your period (at most half a year): the darker, the more you spent that day.")}</>
        : i.view === "weekday" ? <>{tr("What you spend on average on each day of the week.")}</>
        : <>{trx("What you spend on average on each day {0}.", ctx.boundaries ? tr("after your salary (day 1 is your salary day)") : tr("of the month"))}</>}</>}>
      <div className="relative" data-tip-area>
        {content}
        <TipCard tip={tip} />
      </div>
    </ChartCard>
  );
}
