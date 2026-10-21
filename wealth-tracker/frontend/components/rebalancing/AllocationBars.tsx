// The current allocation against your target allocation, one row per category.
//
// Replaces charts.rebalancing_chart — a grouped Plotly bar chart — *and* the
// separate StatusCard tiles that were below it. Those two showed exactly the same
// four numbers (category, current %, target %, deviation in pp): the chart as
// bars, the tiles as text. One row that does both is not only less code, it also
// takes away the question which of the two you should read.
//
// The bar is on a scale of 0–100% of your portfolio, not on the highest value: a
// bucket of 10% must look like 10%, even if the other two are larger. The
// precision is in the numbers next to it, the bar gives the ratio.
//
// The traffic light comes along from the backend (`deviation_status`: green
// within 5pp, orange within 15pp, red beyond that). Deliberately not derived here
// — then the two can drift apart as soon as someone moves those limits.

import { fmtEu, fmtEuro } from "@/lib/format";
import { tr, trx } from "@/lib/i18n";

export type AllocationStatus = "green" | "amber" | "red";

export type AllocationRow = {
  label: string;
  currentPct: number;
  targetPct: number;
  status: AllocationStatus;
  /** Amount in euros, if it is known — otherwise it is left out. */
  currentEur?: number | null;
};

// The traffic light in the app's tokens, no emoji: 🟢🟡🔴 render differently
// per platform and ignore the theme.
const TONE: Record<AllocationStatus, { bar: string; text: string }> = {
  green: { bar: "var(--pos)", text: "text-pos" },
  amber: { bar: "var(--warn)", text: "text-warn" },
  red: { bar: "var(--neg)", text: "text-neg" },
};

function clampPct(v: number): number {
  return Math.min(Math.max(v, 0), 100);
}

export default function AllocationBars({ rows }: { rows: AllocationRow[] }) {
  return (
    <div className="flex flex-col gap-4">
      {rows.map((row) => {
        const deviation = row.currentPct - row.targetPct;
        const tone = TONE[row.status];
        // 0.05pp: below that limit the difference is a rounding artefact and
        // "+0.0 pp" reads as a deviation that is not there.
        const onTarget = Math.abs(deviation) < 0.05;
        return (
          <div key={row.label}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[13px] font-semibold">
                {row.label}
                {row.currentEur != null && (
                  <span className="ml-1.5 num text-[11.5px] font-normal text-ink-muted">{fmtEuro(row.currentEur)}</span>
                )}
              </span>
              <span className="num flex-none text-[15px] font-semibold">{fmtEu(row.currentPct, { decimals: 1, suffix: "%" })}</span>
            </div>

            {/* The bar itself adds nothing for a screen reader: every number
                in it is shown as text above and below it. */}
            <div aria-hidden="true" className="relative mt-1.5 h-2 rounded-full" style={{ background: "var(--surface-inset)" }}>
              <div
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ width: `${clampPct(row.currentPct)}%`, background: tone.bar }}
              />
              {/* The target as a mark across the bar: a second bar next to it
                  (what Plotly did) doubles the height of the row and makes you
                  compare two lengths instead of reading one against a mark. */}
              <div
                className="absolute -top-[3px] h-[14px] w-[2px] rounded-full bg-text/70"
                style={{ left: `calc(${clampPct(row.targetPct)}% - 1px)` }}
              />
            </div>

            <div className="mt-1 flex items-baseline justify-between gap-3 text-[11.5px]">
              {onTarget ? (
                <span className={tone.text}>{tr("on target")}</span>
              ) : (
                <span className={`num ${tone.text}`}>
                  {trx("{0} pp {1} target", fmtEu(deviation, { decimals: 1, plus: true }), deviation > 0 ? "above" : "under")}
                </span>
              )}
              <span className="num flex-none text-ink-muted">{trx("target {0}", fmtEu(row.targetPct, { decimals: 0, suffix: "%" }))}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** The explanation of the traffic light. It used to be only in a `title` attribute,
 *  which a touch screen never shows. */
export function DeviationLegend() {
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-ink-muted">
      {(
        [
          ["green", tr("within 5 pp of your target")],
          ["amber", tr("within 15 pp")],
          ["red", tr("more than 15 pp off")],
        ] as const
      ).map(([status, text]) => (
        <span key={status} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 flex-none rounded-full" style={{ background: TONE[status].bar }} />
          {text}
        </span>
      ))}
    </p>
  );
}
