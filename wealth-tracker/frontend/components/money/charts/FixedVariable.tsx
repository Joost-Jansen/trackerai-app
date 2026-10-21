"use client";

// Fixed versus variable: per month what was already fixed before you chose
// anything (rent, subscriptions, insurance — see fixed_costs.py) and what you
// spent yourself. Two colours, stacked.

import { fmtEuro } from "@/lib/format";
import { ChartCard, Setting, Legend, monthsUntil, monthLabel, nameKey, percent, TipCard, useTip, type ChartProps } from "./base";
import { tr, trx } from "@/lib/i18n";

export const DEFAULT = { measure: "amount", months: "12" };
const IS_FIXED = tr("Fixed costs");
const FREE = tr("Variable");
const COLOURS = new Map([
  [IS_FIXED, "var(--cat-1)"],
  [FREE, "var(--cat-3)"],
]);

export default function FixedVariable({ ctx, inst, put, editing }: ChartProps) {
  const i = { ...DEFAULT, ...inst };
  const { tip, props } = useTip();
  const months = monthsUntil(ctx.time_window.to, ctx.boundaries, Number(i.months));
  const digits = months.map(() => ({ is_fixed: 0, free: 0 }));
  for (const r of ctx.allRows) {
    if (r.type !== "EXPENSE" || r.amount <= 0) continue;
    const k = months.findIndex((m) => r.date >= m.start && r.date <= m.end);
    if (k === -1) continue;
    if (ctx.fixedNames.has(nameKey(r.name))) digits[k].is_fixed += r.amount;
    else digits[k].free += r.amount;
  }
  const max = Math.max(1, ...digits.map((c) => (i.measure === "percent" ? 100 : c.is_fixed + c.free)));
  const withData = digits.filter((c) => c.is_fixed + c.free > 0);
  const avgFixed = withData.length ? withData.reduce((a, c) => a + c.is_fixed, 0) / withData.length : 0;
  const avgVariable = withData.length ? withData.reduce((a, c) => a + c.free, 0) / withData.length : 0;

  return (
    <ChartCard
      title={tr("Fixed and variable")}
      editing={editing}
      settings={
        <>
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
            label={tr("Months")}
            value={i.months}
            onChange={(w) => put("months", w)}
            options={[
              ["6", "6"],
              ["12", "12"],
              ["24", "24"],
            ]}
          />
        </>
      }
      info={
        <>
          {tr(
            "Fixed costs are debits that come back every month with about the same amount (see the Fixed costs block); the rest is variable: what you choose yourself.",
          )}
        </>
      }
    >
      {ctx.fixedNames.size === 0 ? (
        <p className="py-4 text-sm text-ink-muted">{tr("No fixed costs recognised yet; you'll see them after a few months.")}</p>
      ) : (
        <div className="relative flex flex-col gap-2" data-tip-area>
          <p className="text-sm">
            {trx(
              "On average {0} fixed ({1}) and {2} variable per {3}.",
              <b className="num">{fmtEuro(avgFixed)}</b>,
              percent(avgFixed + avgVariable ? (avgFixed / (avgFixed + avgVariable)) * 100 : 0),
              <b className="num">{fmtEuro(avgVariable)}</b>,
              ctx.monthWord,
            )}
          </p>
          <div className="flex h-48 items-end gap-1.5">
            {months.map((m, k) => {
              const c = digits[k];
              const t = c.is_fixed + c.free;
              const high = i.measure === "percent" ? (t ? 100 : 0) : t;
              return (
                <div key={m.key} className="flex h-full min-w-0 flex-1 flex-col justify-end">
                  <div className="flex flex-col-reverse overflow-hidden rounded-t-[4px]" style={{ height: `${(high / max) * 100}%` }}>
                    {(
                      [
                        [IS_FIXED, c.is_fixed],
                        [FREE, c.free],
                      ] as const
                    ).map(
                      ([name, w]) =>
                        w > 0 && (
                          <button
                            key={name}
                            type="button"
                            aria-label={`${name}, ${monthLabel(m.key, k, months)}: ${fmtEuro(w)}`}
                            className="w-full transition-[filter] hover:brightness-110 focus:outline-none focus-visible:brightness-110"
                            style={{
                              height: `${(w / t) * 100}%`,
                              background: COLOURS.get(name),
                              borderTop: "2px solid var(--surface-page)",
                            }}
                            {...props(
                              `${m.key}|${name}`,
                              {
                                title: monthLabel(m.key, 0, [m]),
                                rules: [
                                  { label: IS_FIXED, value: fmtEuro(c.is_fixed), colour: COLOURS.get(IS_FIXED), strong: name === IS_FIXED },
                                  { label: FREE, value: fmtEuro(c.free), colour: COLOURS.get(FREE), strong: name === FREE },
                                  { label: tr("fixed share"), value: percent(t ? (c.is_fixed / t) * 100 : 0) },
                                ],
                                foot: tr("Click for the transactions of that month"),
                              },
                              () => ctx.dest({ start: m.start, end: m.end }),
                            )}
                          />
                        ),
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex gap-1.5">
            {months.map((m, k) => (
              <span key={m.key} className="min-w-0 flex-1 truncate text-center text-[10px] text-ink-muted">
                {monthLabel(m.key, k, months)}
              </span>
            ))}
          </div>
          <Legend names={[IS_FIXED, FREE]} colours={COLOURS} />
          <TipCard tip={tip} />
        </div>
      )}
    </ChartCard>
  );
}
