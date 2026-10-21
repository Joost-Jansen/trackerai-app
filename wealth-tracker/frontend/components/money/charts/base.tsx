"use client";

// The building blocks of the charts on Spending → Overview.
//
// Three agreements every chart here follows:
//
//   * **Colour belongs to the name, not to the place.** Which groups get their own
//     colour depends on their size, but which colour follows the order of your
//     taxonomy. That way Boodschappen does not change colour because it was a
//     month larger than Wonen. The series --cat-1..6 has been checked for
//     distinctness, also for colour-blind people (see globals.css).
//   * **Pointing shows the number.** Every bar, every box and every cell has its
//     own hover card, also with the keyboard. On a touch screen the first tap
//     shows the card and the second does what a click does.
//   * **Settings per chart, and choose which yourself.** Every chart has a ⚙ with
//     what you can change about it; the page remembers that with your account.

import { useLayoutEffect, useRef, useState } from "react";
import { Button, Section, Tabs } from "@/components/ds";
import { fmtMonth } from "@/lib/format";
import { dayNumber, isoDay } from "@/lib/timeline";
import { boundaryIndex } from "@/lib/month-periods";
import type { Category, Transaction } from "@/lib/money";
import { intlLocale, tr } from "@/lib/i18n";

export type Month = { key: string; start: string; end: string };

/** The `n` months up to and including the one in which `end` falls: calendar, or from salary to salary. */
export function monthsUntil(end: string, boundaries: string[] | null, n: number): Month[] {
  if (boundaries?.length) {
    const i = boundaryIndex(end, boundaries);
    const off: Month[] = [];
    for (let k = Math.max(0, i - n + 1); k <= i; k++) {
      const final = k + 1 < boundaries.length ? isoDay(dayNumber(boundaries[k + 1]) - 1) : end;
      off.push({ key: boundaries[k].slice(0, 7), start: boundaries[k], end: final });
    }
    return off;
  }
  const off: Month[] = [];
  const d = new Date(`${end.slice(0, 7)}-01T00:00:00Z`);
  for (let k = 0; k < n; k++) {
    const start = d.toISOString().slice(0, 10);
    const final = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).toISOString().slice(0, 10);
    off.unshift({ key: start.slice(0, 7), start, end: final });
    d.setUTCMonth(d.getUTCMonth() - 1);
  }
  return off;
}

/**
 * The months you can look at one by one: from the month of your first data up to
 * and including the current one, ascending. Always at least the current month.
 */
export function monthChoices(first: string, boundaries: string[] | null, last: string): Month[] {
  const n = boundaries?.length ? boundaries.length
    : (Number(last.slice(0, 4)) - Number(first.slice(0, 4))) * 12 + Number(last.slice(5, 7)) - Number(first.slice(5, 7)) + 1;
  const all = monthsUntil(last, boundaries, Math.max(1, n));
  const shown = all.filter((m) => m.end >= first);
  return shown.length ? shown : all.slice(-1);
}

/** "Sep 2026": a month on its own, where the year is not obvious. */
export const monthName = (key: string) => `${fmtMonth(key)} ${key.slice(0, 4)}`;

/** "Sep", with the year added where it is needed: at the first and at a new year. */
export function monthLabel(key: string, i: number, items: { key: string }[]): string {
  const year = i === 0 || key.slice(0, 4) !== items[i - 1]?.key.slice(0, 4);
  return year ? `${fmtMonth(key)} '${key.slice(2, 4)}` : fmtMonth(key);
}

/** The roll-up of the smallest items: "Other" (Dutch "Overig"). */
export const MISC = tr("Other");
export const COLOURS = [1, 2, 3, 4, 5, 6].map((n) => `var(--cat-${n})`);
export const COLOUR_MISC = "var(--cat-other)";

/**
 * The colour per name follows its fixed place in the taxonomy, never the size.
 *
 * But never two the same in one chart: there are more groups than colours, so the
 * preferred colour (place modulo six) may already be taken — Wonen and Vrije tijd
 * both became blue. Then the first free one. Only when there are more names than
 * colours do they share one.
 */
export function coloursFor(names: string[], sort_order: string[]): Map<string, string> {
  const spot = (n: string) => {
    const i = sort_order.indexOf(n);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  const card = new Map<string, string>();
  const occupied = new Set<string>();
  [...names].filter((n) => n !== MISC)
    .sort((a, b) => spot(a) - spot(b) || a.localeCompare(b, "nl"))
    .forEach((n, i) => {
      const preference = COLOURS[(spot(n) === Number.MAX_SAFE_INTEGER ? i : spot(n)) % COLOURS.length];
      const colour = !occupied.has(preference) ? preference : COLOURS.find((k) => !occupied.has(k)) ?? preference;
      occupied.add(colour);
      card.set(n, colour);
    });
  card.set(MISC, COLOUR_MISC);
  return card;
}

export type Distribution = "groups" | "categories" | "counterparties";

export type Context = {
  /** Transactions in the chosen period, with the filters. */
  rows: Transaction[];
  /** The same filters, without period: for month charts and comparisons. */
  allRows: Transaction[];
  /** The twelve months before the period ("normal"), and the transactions in them. */
  base: Month[];
  baseRows: Transaction[];
  time_window: { from: string; to: string };
  boundaries: string[] | null;
  /** How many months the period covers (partial months pro rata). */
  months: number;
  categories: Category[];
  groupOf: (c: string | null) => string;
  categoriesOf: (group_name: string) => string[];
  /** The counterparties of your fixed costs, as nameKey. */
  fixedNames: Set<string>;
  /** IBANs of this user's accounts, for own transfers. */
  ownIbans: Set<string>;
  monthWord: string;
  /** The month the month cards look at (the month in the bar at the top), and whether it is the current one. */
  month: Month;
  running: boolean;
  /** All months you can choose, ascending; the last is the current month. */
  monthChoices: Month[];
  /** Chooses the month for every month card at once; "" is back to the current month. */
  setMonth: (key: string) => void;
  dest: (w: { start?: string; end?: string; categories?: string[]; search?: string }) => void;
};

export function keyOf(r: Transaction, v: Distribution, ctx: Context): string {
  if (v === "groups") return ctx.groupOf(r.category);
  if (v === "categories") return r.category ?? "Onbekend";
  return r.name;
}

export function orderOf(v: Distribution, ctx: Context): string[] {
  if (v === "groups") return [...new Set(ctx.categories.map((c) => c.group_name)), "Onbekend"];
  if (v === "categories") return ctx.categories.map((c) => c.name);
  return [];
}

/** The Transactions filter that belongs to a name in this distribution. */
export function filterFor(name: string, v: Distribution, ctx: Context): { categories?: string[]; search?: string } {
  if (name === MISC) return {};
  if (v === "groups") return { categories: ctx.categoriesOf(name) };
  if (v === "categories") return { categories: [name] };
  return { search: name };
}

/** The same key as fixed_costs.py: capitals, without digits and double spaces. */
export function nameKey(name: string): string {
  return name.toUpperCase().replace(/\d+/g, "").replace(/\s+/g, " ").trim();
}

export const summed = (rows: Transaction[]) => rows.reduce((a, r) => a + r.amount, 0);
export const percent = (v: number) => `${v.toLocaleString(intlLocale, { maximumFractionDigits: 0 })}%`;

/** Measured width of an element: charts that calculate in pixels themselves. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(640);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth || 640);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 640));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

// ---------------------------------------------------------------------------
// The hover card
// ---------------------------------------------------------------------------

export type TipContent = {
  title: string;
  rules: { label: string; value: string; colour?: string; strong?: boolean }[];
  foot?: string;
};

type TipStand = { x: number; y: number; w: number; content: TipContent; key: string };

/**
 * A hover card for a chart. `props(key, content, run)` goes on every pointable
 * surface; the surface around it carries `data-tip-area` and `relative`, and
 * `<TipCard tip={tip} />` sits in it.
 */
export function useTip() {
  const [tip, setTip] = useState<TipStand | null>(null);
  const touch = useRef(false);

  function place(e: { currentTarget: EventTarget & HTMLElement; clientX?: number; clientY?: number },
    key: string, content: TipContent) {
    const area = e.currentTarget.closest("[data-tip-area]") as HTMLElement | null;
    if (!area) return;
    const r = area.getBoundingClientRect();
    if (e.clientX) {
      setTip({ x: e.clientX - r.left, y: (e.clientY ?? 0) - r.top, w: r.width, content, key });
    } else {
      const b = e.currentTarget.getBoundingClientRect();
      setTip({ x: b.left + b.width / 2 - r.left, y: b.top - r.top, w: r.width, content, key });
    }
  }

  function props(key: string, content: TipContent, run?: () => void) {
    return {
      onPointerDown: (e: React.PointerEvent<HTMLElement>) => { touch.current = e.pointerType === "touch"; },
      onPointerMove: (e: React.PointerEvent<HTMLElement>) => { if (e.pointerType !== "touch") place(e, key, content); },
      onPointerLeave: () => setTip(null),
      onFocus: (e: React.FocusEvent<HTMLElement>) => place(e, key, content),
      onBlur: () => setTip(null),
      onClick: (e: React.MouseEvent<HTMLElement>) => {
        // Touch: first the card, only on the second tap on the same surface click through.
        if (touch.current && tip?.key !== key) {
          place(e, key, content);
          return;
        }
        run?.();
      },
    };
  }

  return { tip, props };
}

/** The card itself: the number in front and strong, the label after it. */
export function TipCard({ tip }: { tip: TipStand | null }) {
  if (!tip) return null;
  const x = tip.x < 130 ? "0%" : tip.x > tip.w - 130 ? "-100%" : "-50%";
  return (
    <div role="tooltip" className="pointer-events-none absolute z-20 min-w-[11rem] max-w-[17rem] rounded-md px-3 py-2 text-xs shadow-lg"
      style={{ left: tip.x, top: tip.y, transform: `translate(${x}, calc(-100% - 10px))`, background: "var(--surface-inverse)", color: "var(--text-inverse)" }}>
      <div className="mb-1 font-semibold">{tip.content.title}</div>
      {tip.content.rules.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5" style={{ color: "var(--text-on-ink-muted)" }}>
            {r.colour && <span aria-hidden className="inline-block h-[3px] w-3 rounded-full" style={{ background: r.colour }} />}
            {r.label}
          </span>
          <span className={`num ${r.strong ? "font-semibold" : ""}`}>{r.value}</span>
        </div>
      ))}
      {tip.content.foot && <div className="mt-1.5" style={{ color: "var(--text-on-ink-muted)" }}>{tip.content.foot}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The card around a chart
// ---------------------------------------------------------------------------

export type Editing = { up?: () => void; down?: () => void; hide: () => void };

export type ChartProps = {
  ctx: Context;
  inst: Record<string, string>;
  put: (key: string, value: string) => void;
  editing?: Editing;
};

/** A setting as a row of buttons: "Measure in: € | %". */
export function Setting({ label, value, options, onChange }: {
  label: string; value: string; options: [string, string][]; onChange: (v: string) => void;
}) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className="text-[11.5px] text-ink-muted">{label}</span>
      <Tabs variant="segmented" ariaLabel={label} items={options.map(([id, l]) => ({ id, label: l }))} value={value} onChange={onChange} />
    </span>
  );
}

/**
 * The month as a setting of a month card: the current month and the three before
 * it, plus the chosen month when it lies further back. It is the same month as in
 * the bar at the top, so changing it here changes every month card.
 */
export function MonthSetting({ ctx }: { ctx: Context }) {
  const recent = ctx.monthChoices.slice(-4).reverse();
  const options = recent.map((m, k): [string, string] =>
    [m.key, k === 0 ? tr("This {0}", ctx.monthWord) : k === 1 ? tr("Previous {0}", ctx.monthWord) : monthName(m.key)]);
  if (!recent.some((m) => m.key === ctx.month.key)) options.push([ctx.month.key, monthName(ctx.month.key)]);
  const current = recent[0]?.key;
  return <Setting label={tr("Month")} value={ctx.month.key} options={options}
    onChange={(key) => ctx.setMonth(key === current ? "" : key)} />;
}

export function ChartCard({ title, info, meta, settings, editing, children }: {
  title: string;
  info?: React.ReactNode;
  meta?: React.ReactNode;
  /** The buttons behind ⚙. */
  settings?: React.ReactNode;
  editing?: Editing;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Section
      label={title}
      info={info}
      meta={editing ? undefined : meta}
      action={editing ? (
        <span className="flex gap-1">
          <Button size="sm" variant="ghost" disabled={!editing.up} onClick={editing.up} aria-label={tr("{0} up", title)}>↑</Button>
          <Button size="sm" variant="ghost" disabled={!editing.down} onClick={editing.down} aria-label={tr("{0} down", title)}>↓</Button>
          <Button size="sm" variant="ghost" onClick={editing.hide}>{tr("Hide")}</Button>
        </span>
      ) : settings ? (
        <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <span aria-hidden>⚙</span> {open ? tr("Done") : tr("Set up")}
        </Button>
      ) : undefined}
    >
      {open && settings && !editing && (
        <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2.5 rounded-md p-3" style={{ background: "var(--surface-inset)" }}>
          {settings}
        </div>
      )}
      {children}
    </Section>
  );
}

/** The legend of a bar chart: a square per name, in the order of the chart. */
export function Legend({ names, colours }: { names: string[]; colours: Map<string, string> }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 pt-2 text-xs text-ink-muted">
      {names.map((n) => (
        <span key={n} className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: colours.get(n) }} />{n}
        </span>
      ))}
    </div>
  );
}
