"use client";

// What is in "Other" — and nothing else.
//
// The bar above gives the largest categories each their own row with their own
// percentage, and sweeps the rest into one segment "Other". That segment was a
// dead end: you saw how much it was, never what it consisted of. This is the
// follow-up.
//
// *Only* the follow-up: this list started as the full ranking with a rule where
// "Other" began, which was right when the bar was still one stacked bar with a
// legend. Since every category has its own row and its own bar, that ranking was
// redrawing the top five row by row — the same label, the same percentage, the
// same bar, twice one below the other.
//
// The bars are scaled against the *whole*, like the bar above: these items
// *should* be dashes of nothing, and making them as long as the largest item
// above would polish away exactly the ratio you came to look up.

import { fmtEu } from "@/lib/format";
import { localName } from "@/lib/slices";
import type { AllocationSlice } from "@/lib/dashboard";
import { tr, trx } from "@/lib/i18n";

export default function SliceTable({
  slices,
  /** What the row that sums up these categories is called — "Other". */
  foldedAs = localName("Other"),
  /**
   * The percentage on that row. Passed in and not added up here: the sum of
   *  separately rounded tenths is almost never exactly the rounded whole, and then
   *  this sentence names a number that shows differently right above it.
   */
  foldedPct,
  /** What the bar length is measured against; 100 by default (whole percents). */
  whole = 100,
  /** The same colour as the segment these items were in. */
  colour = "var(--n-400)",
  unit = "%",
  /**
   * Two decimals for a tail of tenths of percents; otherwise half the list reads
   *  as "0.0%".
   */
  decimals = 1,
}: {
  slices: AllocationSlice[];
  foldedAs?: string;
  foldedPct: number;
  whole?: number;
  colour?: string;
  unit?: string;
  decimals?: number;
}) {
  const sorted = [...slices].sort((a, b) => b.pct - a.pct);
  const peak = Math.max(whole, Number.EPSILON);
  // The smallest number that is still something at this number of decimals. At the
  // bottom of this tail are items that fall below it, and "0.00%" next to a country
  // name reads as "nothing" while the answer to "am I in there?" is yes.
  const floor = 10 ** -decimals;
  const pct = (value: number) =>
    value < floor
      ? `<${fmtEu(floor, { decimals, suffix: unit })}`
      : fmtEu(value, { decimals, suffix: unit });

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] leading-snug text-ink-muted">{trx("Together the row “{0}” above, of {1}.", foldedAs, <span className="num">{fmtEu(foldedPct, { decimals: 1, suffix: unit })}</span>)}</p>
      {sorted.map((slice) => (
        <div key={slice.name}>
          <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
            {/* The issuers have a category "Other" of their own, and here it almost always falls in
                the tail. Untranslated it would be called "Other" — exactly the name of the row that
                sums up this whole list, so a row that looks like a repetition of the heading. */}
            <span className="min-w-0 truncate">
              {slice.name === "Other" ? tr("No category") : localName(slice.name)}
            </span>
            <span className="num flex-none font-semibold">
              {pct(slice.pct)}
            </span>
          </div>
          <div aria-hidden="true" className="mt-1 h-1.5 rounded-full"
            style={{ background: "var(--surface-inset)" }}>
            <div
              className="h-full rounded-full"
              style={{
                // No minimum of 1% as in HBars: here items of 0.44% sit next to items of 0.01%,
                // and a minimum width makes those two equally long — then the bar draws the
                // opposite of what the number next to it says.
                width: `${(slice.pct / peak) * 100}%`,
                background: colour,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
