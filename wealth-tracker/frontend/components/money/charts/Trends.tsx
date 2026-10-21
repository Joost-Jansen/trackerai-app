"use client";

// Trends and risers: per group a small line over the months, and at the top the
// groups that rose or fell most compared to your normal month. Small charts side
// by side instead of one tangle of lines: that way each group can be read on its
// own.

import { fmtEuro } from "@/lib/format";
import {
  filterFor,
  ChartCard,
  Setting,
  monthsUntil,
  monthLabel,
  percent,
  keyOf,
  TipCard,
  useTip,
  type ChartProps,
  type Distribution,
} from "./base";
import { tr, trx } from "@/lib/i18n";

export const DEFAULT = { divide: "groups", count: "9" };
// A difference below this amount per month is not a riser or faller, but noise.
const MIN_DIFFERENCE = 10;

export default function Trends({ ctx, inst, put, editing }: ChartProps) {
  const i = { ...DEFAULT, ...inst };
  const { tip, props } = useTip();
  const v = i.divide as Distribution;
  const months = monthsUntil(ctx.time_window.to, ctx.boundaries, 12);

  const series = new Map<string, number[]>();
  for (const r of ctx.allRows) {
    if (r.type !== "EXPENSE") continue;
    const m = months.findIndex((x) => r.date >= x.start && r.date <= x.end);
    if (m === -1) continue;
    const k = keyOf(r, v, ctx);
    const row = series.get(k) ?? new Array(months.length).fill(0);
    row[m] += r.amount;
    series.set(k, row);
  }
  const now = new Map<string, number>();
  for (const r of ctx.rows) if (r.type === "EXPENSE") now.set(keyOf(r, v, ctx), (now.get(keyOf(r, v, ctx)) ?? 0) + r.amount);
  const normal = new Map<string, number>();
  for (const r of ctx.baseRows) if (r.type === "EXPENSE") normal.set(keyOf(r, v, ctx), (normal.get(keyOf(r, v, ctx)) ?? 0) + r.amount);

  const names = [...series.keys()];
  const digit = (n: string) => {
    const pm = ctx.months > 0 ? (now.get(n) ?? 0) / ctx.months : 0;
    const nm = ctx.base.length ? (normal.get(n) ?? 0) / ctx.base.length : null;
    return { pm, nm, difference: nm !== null ? pm - nm : null };
  };
  const movers = names.map((n) => ({ n, ...digit(n) })).filter((x) => x.difference !== null && Math.abs(x.difference) >= MIN_DIFFERENCE);
  const risers = [...movers]
    .filter((x) => x.difference! > 0)
    .sort((a, b) => b.difference! - a.difference!)
    .slice(0, 3);
  const fallers = [...movers]
    .filter((x) => x.difference! < 0)
    .sort((a, b) => a.difference! - b.difference!)
    .slice(0, 3);
  const shown = names
    .sort((a, b) => series.get(b)!.reduce((s, w) => s + w, 0) - series.get(a)!.reduce((s, w) => s + w, 0))
    .slice(0, i.count === "all" ? undefined : Number(i.count));

  const Mover = ({ x }: { x: (typeof movers)[number] }) => (
    <li>
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 py-1 text-left text-[12.5px] hover:underline"
        onClick={() => ctx.dest({ start: ctx.time_window.from, end: ctx.time_window.to, ...filterFor(x.n, v, ctx) })}
      >
        <span className="truncate">{x.n}</span>
        <span className="num whitespace-nowrap">
          {trx(
            "{0}{1}/mo{2}",
            x.difference! > 0 ? "+" : "−",
            fmtEuro(Math.abs(x.difference!)),
            x.nm ? (
              <span className="text-ink-muted">
                {" "}
                ({x.difference! > 0 ? "+" : "−"}
                {percent(Math.abs(x.difference! / x.nm) * 100)})
              </span>
            ) : null,
          )}
        </span>
      </button>
    </li>
  );

  return (
    <ChartCard
      title={tr("Trends and risers")}
      editing={editing}
      settings={
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
            label={tr("Number")}
            value={i.count}
            onChange={(w) => put("count", w)}
            options={[
              ["6", "6"],
              ["9", "9"],
              ["all", tr("All of them")],
            ]}
          />
        </>
      }
      info={
        <>
          {trx(
            "Risers and fallers: this period per {0} against your normal month. Below, per {1}, the last twelve months; the dot is the latest.",
            ctx.monthWord,
            v === "groups" ? "group_name" : "category",
          )}
        </>
      }
    >
      {names.length === 0 ? (
        <p className="py-4 text-sm text-ink-muted">{tr("No spending in these months.")}</p>
      ) : (
        <>
          {(risers.length > 0 || fallers.length > 0) && (
            <div className="grid gap-6 pb-4 sm:grid-cols-2">
              <div>
                <p className="pb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">{tr("More than usual")}</p>
                {risers.length ? (
                  <ul>
                    {risers.map((x) => (
                      <Mover key={x.n} x={x} />
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-ink-muted">{tr("Nothing notable.")}</p>
                )}
              </div>
              <div>
                <p className="pb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">{tr("Less than usual")}</p>
                {fallers.length ? (
                  <ul>
                    {fallers.map((x) => (
                      <Mover key={x.n} x={x} />
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-ink-muted">{tr("Nothing notable.")}</p>
                )}
              </div>
            </div>
          )}
          <div className="relative grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-tip-area>
            {shown.map((n) => {
              const r = series.get(n)!;
              const mx = Math.max(1, ...r);
              const W = 160,
                H = 36;
              const pt = (w: number, k: number) => [(k / Math.max(1, r.length - 1)) * W, H - (w / mx) * (H - 4) - 2];
              const c = digit(n);
              return (
                <div key={n} className="rounded-md p-2.5" style={{ border: "1px solid var(--rule)" }}>
                  <button
                    type="button"
                    className="flex w-full items-baseline justify-between gap-2 text-left text-[12.5px] hover:underline"
                    onClick={() => ctx.dest({ start: ctx.time_window.from, end: ctx.time_window.to, ...filterFor(n, v, ctx) })}
                  >
                    <span className="truncate font-semibold">{n}</span>
                    <span className="num whitespace-nowrap text-xs">
                      {trx(
                        "{0}/mo{1}",
                        fmtEuro(c.pm),
                        c.difference !== null && Math.abs(c.difference) >= MIN_DIFFERENCE && (
                          <span className="text-ink-muted"> {c.difference > 0 ? "↑" : "↓"}</span>
                        ),
                      )}
                    </span>
                  </button>
                  <svg viewBox={`0 0 ${W} ${H}`} className="mt-1.5 h-9 w-full overflow-visible" preserveAspectRatio="none" aria-hidden>
                    <polyline
                      fill="none"
                      stroke="var(--text-secondary)"
                      strokeWidth="1.5"
                      vectorEffect="non-scaling-stroke"
                      points={r.map((w, k) => pt(w, k).join(",")).join(" ")}
                    />
                    <circle
                      cx={pt(r[r.length - 1], r.length - 1)[0]}
                      cy={pt(r[r.length - 1], r.length - 1)[1]}
                      r="2.5"
                      fill="var(--cat-1)"
                    />
                  </svg>
                  <div className="-mt-9 flex h-9">
                    {r.map((w, k) => (
                      <span
                        key={k}
                        className="h-full flex-1"
                        tabIndex={0}
                        role="img"
                        aria-label={`${n}, ${monthLabel(months[k].key, 0, [months[k]])}: ${fmtEuro(w)}`}
                        {...props(`${n}|${k}`, {
                          title: `${n} · ${monthLabel(months[k].key, 0, [months[k]])}`,
                          rules: [{ label: tr("spent"), value: fmtEuro(w), strong: true }],
                        })}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
            <TipCard tip={tip} />
          </div>
        </>
      )}
    </ChartCard>
  );
}
