"use client";

// All looked-through companies, as a table.
//
// There are well over fifteen hundred here. As a bar chart that is unreadable —
// the tail is hundreds of items of a few cents, and a bar of 0.003% of the
// largest is not a bar. A table does scale: sorted by value, with the rank, so
// "where does this company stand in my portfolio" is one look instead of
// counting.
//
// A hundred at a time, not everything: putting fifteen hundred rows in the DOM at
// once makes expanding itself slow on a phone, and whoever looks for item 800
// uses the search field at the top.

import { useState } from "react";
import { fmtEu, fmtEuro } from "@/lib/format";
import { tr, trx } from "@/lib/i18n";

export type Holding = { symbol: string; name: string; value: number; sources: string[] };

const PAGE = 100;

export default function HoldingsTable({
  holdings,
  total,
}: {
  holdings: Holding[];
  /**
   * The analysed equity value, not the sum of this list: that covers some 99.6%,
   *  and measured against itself every share would look slightly too large.
   */
  total: number;
}) {
  const [shown, setShown] = useState(PAGE);

  const sorted = [...holdings].sort((a, b) => b.value - a.value);
  const rows = sorted.slice(0, shown);
  const left = sorted.length - rows.length;

  return (
    <div>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>{tr("Company")}</th>
              <th>Ticker</th>
              <th className="num">{tr("Value")}</th>
              <th className="num">{tr("Share")}</th>
              <th>Via</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h, i) => (
              <tr key={`${h.symbol}-${h.name}`}>
                <td className="num text-ink-muted">{i + 1}</td>
                <td>{h.name || h.symbol}</td>
                <td className="num text-ink-muted">{h.symbol}</td>
                <td className="num">{fmtEuro(h.value)}</td>
                <td className="num">{total > 0 ? fmtEu((h.value / total) * 100, { decimals: 2, suffix: "%" }) : "–"}</td>
                <td className="text-ink-muted">{h.sources.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {left > 0 && (
        <div
          className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 pt-2.5"
          style={{ borderTop: "1px solid var(--border-hairline)" }}
        >
          <button type="button" onClick={() => setShown(shown + PAGE)} className="ds-link -my-1 inline-block py-1 text-xs">
            {trx("Show {0} more", Math.min(PAGE, left))}
          </button>
          <span className="num text-[11px] text-ink-muted">{trx("{0} of {1} shown", rows.length, sorted.length)}</span>
          {left > PAGE && (
            <button type="button" onClick={() => setShown(sorted.length)} className="-my-1 py-1 text-[11px] text-ink-muted hover:underline">
              {trx("all ({0})", sorted.length)}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
