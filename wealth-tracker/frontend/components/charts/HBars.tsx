"use client";

// Horizontal bars: one row per category, sorted, longest on top.
//
// Replaces charts.region_allocation_chart (countries) and
// charts.stock_exposure_chart (companies). Those two had a donut and a Plotly
// bar chart, but share the same problem: dozens of categories with a small
// tail. A donut with thirty slices is unreadable and a Plotly bar chart had a
// fixed height of `max(420, n * 30 + 100)` px that knew nothing of the card it
// was in.
//
// What the bar length is measured against is a choice per list — see `scale`. On
// Allocation it is against the *whole* everywhere, so half a bar means the same
// on every card: half your money. On a ranking without a denominator (payouts
// per fund) the largest item is the only sensible denominator.

import { useId, useState } from "react";
import { ChevronDownIcon } from "@trackerai/ui/icons";
import { fmtEu } from "@/lib/format";
import { tr } from "@/lib/i18n";

export type HBar = {
  label: string;
  /**
   * Key for lighting up from outside — see `activeId`. Without this a row cannot be
   *  linked to anything else; the label cannot do that, because it is translated
   *  and the map next to it calculates in the backend's names.
   */
  id?: string;
  /** What the bar length and the sorting are based on. */
  value: number;
  /** What is to the right of the bar. Default: `value` as a percentage. */
  display?: string;
  /**
   * The other number, quietly next to it. A country is a share *and* an amount,
   *  and which of the two you are looking for depends on why you look.
   */
  secondary?: string;
  /**
   * A small line below the label, for example through which ETFs. Collapsed: with
   *  twenty rows that is three lines of grey text per bar, which makes the list
   *  itself unreadable while you wanted to scan it.
   */
  meta?: string;
};

function Amounts({ row }: { row: HBar }) {
  return (
    <span className="flex flex-none items-baseline gap-2">
      {row.secondary && <span className="num text-[11px] text-ink-muted">{row.secondary}</span>}
      <span className="num font-semibold">
        {row.display ?? fmtEu(row.value, { decimals: 1, suffix: "%" })}
      </span>
    </span>
  );
}

/**
 * One bar. A separate component because every row keeps its own open/closed —
 *  one set of open labels in the parent would make every row redraw as soon as
 *  you open one anywhere.
 */
function Row({
  row,
  peak,
  colour,
  idPrefix,
  active,
  onActive,
}: {
  row: HBar;
  peak: number;
  colour: string;
  idPrefix: string;
  /** Whether this row is lit up now. */
  active: boolean;
  /** Pointing; `undefined` if this list is not linked to anything. */
  onActive?: (id: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const metaId = `${idPrefix}-${row.label.replace(/\W+/g, "-")}`;
  // Point, never toggle: on a phone a toggle turns itself off again straight away
  // (focus comes before the click) and then tapping does nothing.
  const link =
    onActive && row.id
      ? {
          onPointerEnter: () => onActive(row.id!),
          onPointerDown: () => onActive(row.id!),
        }
      : {};

  const line = (
    <>
      <span className="min-w-0 truncate">{row.label}</span>
      <Amounts row={row} />
    </>
  );

  return (
    <div
      {...link}
      // The lit row gets a band behind it instead of a different bar colour: the
      // colour of the bar is the distribution it belongs to, and changing it to say "I
      // am pointing here" makes two things speak the same language. The negative
      // margin keeps the bars themselves aligned.
      className={
        active ? "-mx-1.5 rounded-sm px-1.5" : onActive && row.id ? "-mx-1.5 px-1.5" : undefined
      }
      style={active ? { background: "var(--surface-hover)" } : undefined}
    >
      {row.meta ? (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls={metaId}
          className="flex w-full items-baseline justify-between gap-3 text-left text-[12.5px] hover:text-text"
        >
          <span className="flex min-w-0 items-baseline gap-1">
            <span className="min-w-0 truncate">{row.label}</span>
            <ChevronDownIcon
              className={`h-3 w-3 flex-none translate-y-[1px] text-ink-muted transition-transform ${
                open ? "rotate-180" : ""
              }`}
            />
          </span>
          <Amounts row={row} />
        </button>
      ) : (
        <div className="flex items-baseline justify-between gap-3 text-[12.5px]">{line}</div>
      )}
      {/* aria-hidden: the length says nothing the number next to it doesn't already say literally. */}
      <div aria-hidden="true" className="mt-1 h-2 rounded-full"
        style={{ background: "var(--surface-inset)" }}>
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.max((Math.abs(row.value) / peak) * 100, 1)}%`,
            background: colour,
          }}
        />
      </div>
      {row.meta && open && (
        <div id={metaId} className="mt-1 text-[11px] leading-snug text-ink-muted">
          {row.meta}
        </div>
      )}
    </div>
  );
}

export default function HBars({
  rows,
  max,
  colour = "var(--chart-1)",
  scale = "max",
  total,
  emptyLabel = tr("No data available."),
  activeId,
  onActive,
}: {
  rows: HBar[];
  /** How many rows to show. The rest is not drawn but is counted. */
  max?: number;
  colour?: string;
  /**
   * What the bar length is measured against.
   *
   * `total` — against the whole. For a distribution: then half a bar really means
   * half your portfolio, and not "half of the largest item". That is what you want
   * on Allocation, and it is what *all* bars there do: two cards one below the
   * other with the same bar length for a very different amount is letting one
   * card contradict the other.
   *
   * `max` — against the largest visible item. Only for a ranking where there is no
   * whole to measure against.
   */
  scale?: "max" | "total";
  /**
   * The whole, if that is not the sum of these rows. For the companies the rows
   * hold amounts and the list covers some 99.6% of the analysed equity value;
   * measured against its own sum every bar would be slightly too long, and the
   * percentage next to it (which does calculate against that whole) would no
   * longer match.
   */
  total?: number;
  emptyLabel?: string;
  /**
   * Which row is lit up, by `HBar.id`. For a list that sits next to something
   * else showing the same figures — on Allocation the world map — so pointing at
   * one thing moves the other along.
   */
  activeId?: string | null;
  /** Pass pointing on. Without this the rows cannot be pointed at. */
  onActive?: (id: string | null) => void;
}) {
  const idPrefix = useId();

  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm text-ink-muted">{emptyLabel}</p>;
  }

  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const shown = max ? sorted.slice(0, max) : sorted;
  const hidden = sorted.length - shown.length;
  // Never against 0 — then the width becomes NaN. `total` only counts when it is
  // positive: an empty portfolio passes 0, and then the sum of the rows is still a
  // better denominator than dividing by nothing.
  const whole =
    total && total > 0 ? total : sorted.reduce((s, r) => s + Math.abs(r.value), 0);
  const peak =
    scale === "total" || (total && total > 0)
      ? Math.max(whole, Number.EPSILON)
      : Math.max(...shown.map((r) => Math.abs(r.value)), Number.EPSILON);

  return (
    <div>
      <div
        className="flex flex-col gap-2"
        // Only for the mouse. Lifting a finger *also* fires pointerleave, and then the
        // row was off again before you had seen it.
        onPointerLeave={onActive ? (e) => e.pointerType === "mouse" && onActive(null) : undefined}
      >
        {shown.map((row) => (
          <Row
            key={row.label}
            row={row}
            peak={peak}
            colour={colour}
            idPrefix={idPrefix}
            active={activeId !== undefined && activeId !== null && row.id === activeId}
            onActive={onActive}
          />
        ))}
      </div>
      {hidden > 0 && (
        // Never cut off silently: a list that stops at 20 without saying so reads as
        // "this is everything".
        <p className="mt-2.5 border-t border-border pt-2 text-[11px] text-ink-muted">
          <span className="num">{hidden}</span>{" "}
          {hidden === 1 ? tr("smaller item not shown") : tr("smaller items not shown")}
        </p>
      )}
    </div>
  );
}
