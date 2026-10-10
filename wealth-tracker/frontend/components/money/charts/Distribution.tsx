"use client";

// Where the money went, as areas: the larger the box, the more money. Click a
// group and you see the categories in it, click in there and you see the
// counterparties; a counterparty opens the transactions. The path at the top
// brings you back.

import { useState } from "react";
import { fmtEuro } from "@/lib/format";
import {
  ChartCard, Setting, COLOUR_MISC, coloursFor, MISC, percent, TipCard, useWidth, useTip, type ChartProps,
} from "./base";
import { tr, trx } from "@/lib/i18n";

export const DEFAULT = { measure: "amount" };
const HEIGHT = 320;
const MAX_SLOTS = 16;

type Slot = { name: string; value: number; x: number; y: number; w: number; h: number };

/** Squarified treemap: boxes as square as possible, the largest top left. */
function squarify(items: { name: string; value: number }[], x0: number, y0: number, w0: number, h0: number): Slot[] {
  const total = items.reduce((a, i) => a + i.value, 0);
  if (!total) return [];
  const scale = (w0 * h0) / total;
  let rest = items.map((i) => ({ ...i, opp: i.value * scale }));
  const slots: Slot[] = [];
  let x = x0, y = y0, w = w0, h = h0;
  const worst = (row: { opp: number }[], short: number) => {
    const s = row.reduce((a, r) => a + r.opp, 0);
    const mx = Math.max(...row.map((r) => r.opp));
    const mn = Math.min(...row.map((r) => r.opp));
    return Math.max((short * short * mx) / (s * s), (s * s) / (short * short * mn));
  };
  while (rest.length) {
    const short = Math.min(w, h);
    let n = 1;
    while (n < rest.length && worst(rest.slice(0, n + 1), short) <= worst(rest.slice(0, n), short)) n++;
    const row = rest.slice(0, n);
    const s = row.reduce((a, r) => a + r.opp, 0);
    if (w >= h) {
      const kw = s / h;
      let cy = y;
      for (const r of row) { const kh = r.opp / kw; slots.push({ name: r.name, value: r.value, x, y: cy, w: kw, h: kh }); cy += kh; }
      x += kw; w -= kw;
    } else {
      const kh = s / w;
      let cx = x;
      for (const r of row) { const kw = r.opp / kh; slots.push({ name: r.name, value: r.value, x: cx, y, w: kw, h: kh }); cx += kw; }
      y += kh; h -= kh;
    }
    rest = rest.slice(n);
  }
  return slots;
}

export default function Distribution({ ctx, inst, put, editing }: ChartProps) {
  const i = { ...DEFAULT, ...inst };
  const [pad, setPath] = useState<string[]>([]);
  const { tip, props } = useTip();
  const [ref, width] = useWidth<HTMLDivElement>();

  const spending = ctx.rows.filter((r) => r.type === "EXPENSE" && r.amount > 0);
  const group_name = pad[0];
  const category = pad[1];
  const here = spending.filter((r) => (!group_name || ctx.groupOf(r.category) === group_name) && (!category || (r.category ?? "Onbekend") === category));
  const level = !group_name ? "group_name" : !category ? "category" : "counterparty";
  const key = (r: typeof spending[number]) =>
    level === "group_name" ? ctx.groupOf(r.category) : level === "category" ? (r.category ?? "Onbekend") : r.name;

  const perName = new Map<string, { w: number; n: number }>();
  for (const r of here) {
    const k = key(r);
    const c = perName.get(k) ?? { w: 0, n: 0 };
    c.w += r.amount;
    c.n += 1;
    perName.set(k, c);
  }
  let items = [...perName.entries()].map(([name, c]) => ({ name, value: c.w, n: c.n })).sort((a, b) => b.value - a.value);
  const misc = items.length > MAX_SLOTS ? items.slice(MAX_SLOTS - 1) : [];
  if (items.length > MAX_SLOTS) {
    const rest = items.slice(MAX_SLOTS - 1);
    items = [...items.slice(0, MAX_SLOTS - 1), { name: MISC, value: rest.reduce((a, r) => a + r.value, 0), n: rest.reduce((a, r) => a + r.n, 0) }];
  }
  const total = items.reduce((a, r) => a + r.value, 0);
  const slots = squarify(items, 0, 0, width, HEIGHT);

  // Colour: at the top per group (the top 6 in taxonomy order); below that the group's colour.
  const groupOrder = [...new Set(ctx.categories.map((c) => c.group_name)), "Onbekend"];
  const allGroups = new Map<string, number>();
  for (const r of spending) allGroups.set(ctx.groupOf(r.category), (allGroups.get(ctx.groupOf(r.category)) ?? 0) + r.amount);
  const topGroups = [...allGroups.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([g]) => g);
  const colours = coloursFor(topGroups, groupOrder);
  const colour = (name: string) => (level === "group_name" ? colours.get(name) ?? COLOUR_MISC : colours.get(group_name!) ?? COLOUR_MISC);

  const click = (name: string) => {
    if (name === MISC) return;
    if (level === "group_name") setPath([name]);
    else if (level === "category") setPath([group_name!, name]);
    else ctx.dest({ start: ctx.time_window.from, end: ctx.time_window.to, categories: [category!], search: name });
  };
  const fmt = (w: number) => (i.measure === "percent" ? percent(total ? (w / total) * 100 : 0) : fmtEuro(w));

  return (
    <ChartCard title={tr("Breakdown")} editing={editing}
      settings={<Setting label={tr("Measure in")} value={i.measure} onChange={(w) => put("measure", w)} options={[["amount", "€"], ["percent", tr("% of the whole")]]} />}
      info={<>{tr("Your spending in this period as areas: the larger, the more. Click a group for the categories in it, and a category for the counterparties; a counterparty opens the transactions.")}</>}>
      <nav aria-label={tr("Where you are")} className="flex flex-wrap items-center gap-1.5 pb-3 text-xs">
        <button type="button" className={pad.length ? "underline underline-offset-4" : "font-semibold"} onClick={() => setPath([])}>{tr("All spending")}</button>
        {group_name && <><span className="text-ink-muted">›</span>
          <button type="button" className={category ? "underline underline-offset-4" : "font-semibold"} onClick={() => setPath([group_name])}>{group_name}</button></>}
        {category && <><span className="text-ink-muted">›</span><span className="font-semibold">{category}</span></>}
        <span className="ml-auto text-right text-ink-muted"><span className="num block">{trx("{0} total", fmtEuro(total))}</span>
          <span className="num block">{trx("average {0} per {1}", fmtEuro(ctx.months > 0 ? total / ctx.months : 0), ctx.monthWord)}</span>
        </span>
      </nav>
      {items.length === 0 ? <p className="py-4 text-sm text-ink-muted">{tr("No spending in this period.")}</p> : (<>
        <div ref={ref} className="relative w-full" style={{ height: HEIGHT }} data-tip-area>
          {slots.map((slot) => {
            const item = items.find((x) => x.name === slot.name)!;
            const large = slot.w > 70 && slot.h > 36;
            return (
              <button key={slot.name} type="button" aria-label={`${slot.name}: ${fmtEuro(slot.value)}`}
                className="absolute overflow-hidden rounded-[4px] p-1.5 text-left text-[11px] leading-tight transition-[filter] hover:brightness-110 focus:outline-none focus-visible:brightness-110"
                style={{ left: slot.x + 1, top: slot.y + 1, width: Math.max(0, slot.w - 2), height: Math.max(0, slot.h - 2), background: colour(slot.name),
                  color: "var(--cat-label)" }}
                {...props(slot.name, {
                  title: slot.name,
                  rules: [
                    { label: tr("spent"), value: fmtEuro(slot.value), colour: colour(slot.name), strong: true },
                    { label: tr("average per {0}", ctx.monthWord), value: fmtEuro(ctx.months > 0 ? slot.value / ctx.months : 0) },
                    { label: tr("share of the whole"), value: percent(total ? (slot.value / total) * 100 : 0) },
                    { label: tr("transactions"), value: String(item.n) },
                  ],
                  foot: slot.name === MISC ? undefined : level === "counterparty" ? tr("Click for the transactions") : tr("Click to look inside"),
                }, () => click(slot.name))}>
                {large && (
                  <>
                    <span className="block truncate font-semibold">{slot.name}</span>
                    <span className="num block opacity-90">{fmt(slot.value)}</span>
                  </>
                )}
              </button>
            );
          })}
          <TipCard tip={tip} />
        </div>
        {misc.length > 0 && (
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer underline underline-offset-4">{trx("Other: see {0} items", misc.length)}</summary>
            <ul className="mt-2 grid gap-1 sm:grid-cols-2">
              {misc.map((r) => (
                <li key={r.name}>
                  <button type="button" className="flex w-full justify-between gap-3 rounded px-1.5 py-1 text-left hover:bg-surface-2"
                    onClick={() => click(r.name)}>
                    <span className="truncate">{r.name}</span><span className="num whitespace-nowrap">{fmtEuro(r.value)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </>)}
    </ChartCard>
  );
}
