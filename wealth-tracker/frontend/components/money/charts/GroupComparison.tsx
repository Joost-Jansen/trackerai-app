"use client";

// Per group: what you spent per month in the period, with a mark at your normal
// month. Pointing shows the numbers; clicking opens the transactions.

import { fmtEuro } from "@/lib/format";
import { filterFor, ChartCard, Setting, percent, keyOf, TipCard, useTip, type ChartProps, type Distribution } from "./base";
import { tr, trx } from "@/lib/i18n";

export const DEFAULT = { divide: "groups", sort: "largest" };

export default function GroupComparison({ ctx, inst, put, editing }: ChartProps) {
  const i = { ...DEFAULT, ...inst };
  const { tip, props } = useTip();
  const v = i.divide as Distribution;

  const digits = new Map<string, { now: number; n: number; base: number }>();
  const grab = (k: string) => digits.get(k) ?? { now: 0, n: 0, base: 0 };
  for (const r of ctx.rows)
    if (r.type === "EXPENSE") {
      const k = keyOf(r, v, ctx);
      const c = grab(k);
      c.now += r.amount;
      c.n += 1;
      digits.set(k, c);
    }
  for (const r of ctx.baseRows)
    if (r.type === "EXPENSE") {
      const k = keyOf(r, v, ctx);
      const c = grab(k);
      c.base += r.amount;
      digits.set(k, c);
    }
  const rows = [...digits.entries()]
    .map(([name, c]) => ({
      name,
      n: c.n,
      total: c.now,
      now: ctx.months > 0 ? c.now / ctx.months : 0,
      normal: ctx.base.length ? c.base / ctx.base.length : null,
    }))
    .filter((r) => r.now > 0 || (r.normal ?? 0) > 0)
    .sort((a, b) => (i.sort === "difference" ? b.now - (b.normal ?? 0) - (a.now - (a.normal ?? 0)) : b.now - a.now))
    .slice(0, v === "groups" ? undefined : 15);
  const max = Math.max(1, ...rows.flatMap((r) => [r.now, r.normal ?? 0]));

  const settings = (
    <>
      <Setting
        label={tr("Split by")}
        value={i.divide}
        onChange={(w) => put("divide", w)}
        options={[
          ["groups", tr("Groups")],
          ["categories", tr("Categories")],
        ]}
      />
      <Setting
        label={tr("Sort on")}
        value={i.sort}
        onChange={(w) => put("sort", w)}
        options={[
          ["largest", tr("Largest")],
          ["difference", tr("Most increase")],
        ]}
      />
    </>
  );

  return (
    <ChartCard
      title={v === "groups" ? tr("Per group") : tr("Per category")}
      editing={editing}
      settings={settings}
      meta={<span className="text-xs text-ink-muted">{tr("bar: this period · line: usual")}</span>}
      info={
        <>
          {trx(
            "What you spent in this period per {0}, with a line at your normal month (the average of the twelve months before). A bar past the line: more than usual.",
            ctx.monthWord,
          )}
        </>
      }
    >
      {rows.length === 0 ? (
        <p className="py-4 text-sm text-ink-muted">{tr("No spending in this period.")}</p>
      ) : (
        <ul className="relative flex flex-col" data-tip-area>
          {rows.map((r) => {
            const difference = r.normal ? ((r.now - r.normal) / r.normal) * 100 : null;
            return (
              <li key={r.name} style={{ borderTop: "1px solid var(--rule)" }}>
                <button
                  type="button"
                  className="grid w-full grid-cols-[minmax(7rem,11rem)_1fr_auto] items-center gap-3 py-2 text-left text-[12.5px] hover:bg-surface-2 focus:outline-none focus-visible:bg-surface-2"
                  {...props(
                    r.name,
                    {
                      title: r.name,
                      rules: [
                        { label: tr("per {0}, now", ctx.monthWord), value: fmtEuro(r.now), colour: "var(--cat-1)", strong: true },
                        ...(r.normal !== null ? [{ label: "normal", value: fmtEuro(r.normal) }] : []),
                        ...(difference !== null
                          ? [{ label: "difference", value: `${difference >= 0 ? "+" : "−"}${percent(Math.abs(difference))}` }]
                          : []),
                        { label: tr("in the whole period"), value: `${fmtEuro(r.total)} · ${r.n}×` },
                      ],
                      foot: tr("Click for the transactions"),
                    },
                    () => ctx.dest({ start: ctx.time_window.from, end: ctx.time_window.to, ...filterFor(r.name, v, ctx) }),
                  )}
                >
                  <span className="truncate">{r.name}</span>
                  <span className="relative h-2.5 rounded-full" style={{ background: "var(--surface-inset)" }}>
                    <span
                      className="absolute inset-y-0 left-0 rounded-full"
                      style={{ width: `${(r.now / max) * 100}%`, background: "var(--cat-1)" }}
                    />
                    {r.normal !== null && (
                      <span
                        aria-hidden
                        className="absolute -inset-y-1 w-0.5"
                        style={{ left: `${(r.normal / max) * 100}%`, background: "var(--text-primary)" }}
                      />
                    )}
                  </span>
                  <span className="num whitespace-nowrap text-right text-xs">
                    {trx(
                      "{0}/mo {1}",
                      fmtEuro(r.now),
                      difference !== null && Math.abs(difference) >= 1 && (
                        <span className="text-ink-muted">
                          {difference > 0 ? "+" : "−"}
                          {percent(Math.abs(difference))}
                        </span>
                      ),
                    )}
                  </span>
                </button>
              </li>
            );
          })}
          <TipCard tip={tip} />
        </ul>
      )}
    </ChartCard>
  );
}
