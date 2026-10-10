/**
 * A breakdown that reads as an addition: signed rows, a rule, then the total.
 *
 * Written for the dashboard's hero, which replaced three side-by-side chips
 * with it. Chips are fine for three figures of the same kind, but the moment
 * costs joined them as a negative the row stopped being scannable — a column of
 * aligned amounts ending in a ruled total is how a subtraction is read, and it
 * makes the claim the numbers actually satisfy ("these four make that one")
 * legible instead of implied.
 *
 * The position page needs the identical claim one holding at a time
 * (ongerealiseerd + gerealiseerd + dividend − kosten = totale W/V), which is
 * what moved it out of that page and into its own file.
 *
 * `total` is optional because a caller can already be showing it: the hero puts
 * "Totaalrendement +€3.543,57" above the rows in display type, and repeating the
 * same label and amount under a rule says nothing the reader has not just read.
 * The rule still closes the column.
 */

import SignedAmount from "@/components/SignedAmount";

export default function BreakdownList({
  rows,
  total,
}: {
  rows: { label: string; value: number | null; info?: React.ReactNode }[];
  total?: { label: string; value: number | null };
}) {
  return (
    <dl className="text-[13px]">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-3 py-[5px]">
          <dt className="flex items-center gap-1 text-ink-muted">
            {r.label}
            {r.info}
          </dt>
          <dd>
            <SignedAmount value={r.value} prefix="€" />
          </dd>
        </div>
      ))}
      {total && (
        <div
          className="mt-1 flex items-center justify-between gap-3 pt-2"
          style={{ borderTop: "1px solid var(--border-hairline)" }}
        >
          <dt className="font-semibold">{total.label}</dt>
          <dd>
            <SignedAmount value={total.value} prefix="€" bold className="text-[15px]" />
          </dd>
        </div>
      )}
    </dl>
  );
}
