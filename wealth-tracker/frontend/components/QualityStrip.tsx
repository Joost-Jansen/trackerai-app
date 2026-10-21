import { fmtEu } from "@/lib/format";
import { tr } from "@/lib/i18n";

/**
 * The "Data quality:" chip row above each Allocation chart set
 * (app.py:892-933 and app.py:992-1031).
 *
 * The two strips grade the same four levels but word them differently — the
 * diversification one says "Estimated (Yahoo/justetf)" where the exposure one
 * says "Approximate (Yahoo top-10)", because they are estimated from different
 * things. So the labels are the caller's, and the buckets and percentages come
 * from the backend, which computes them with app.py's own ranking.
 */

export type QualityBucket = {
  kind: string;
  pct: number;
  tickers: string[];
};

type Labels = Record<string, { icon: string; text: string; colour: string; suffix?: string }>;

export const DIVERSIFICATION_LABELS: Labels = {
  exact: {
    icon: "✓",
    text: tr("Exact holdings from the issuer"),
    colour: "text-gain",
    suffix: tr("of the analysed value"),
  },
  proxy: { icon: "◐", text: tr("Index proxy (nearly exact)"), colour: "text-proxy" },
  est: { icon: "≈", text: tr("Estimate (Yahoo/justETF)"), colour: "text-approx" },
  none: { icon: "✕", text: tr("Only derived from the name"), colour: "text-loss" },
};

export const EXPOSURE_LABELS: Labels = {
  exact: {
    icon: "✓",
    text: tr("Exact holdings from the issuer"),
    colour: "text-gain",
    suffix: tr("of the analysed value"),
  },
  proxy: { icon: "◐", text: tr("Index proxy (nearly exact)"), colour: "text-proxy" },
  approx: { icon: "≈", text: tr("Approximation (Yahoo top 10)"), colour: "text-approx" },
  none: { icon: "✕", text: tr("No holdings data"), colour: "text-loss" },
};

export default function QualityStrip({ buckets, labels }: { buckets: QualityBucket[]; labels: Labels }) {
  if (!buckets.length) return null;

  // No more "Data quality:" prefix: both places are now in a card that already says
  // so in its title, and it read as a label for the first chip.
  return (
    <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
      {buckets.map((bucket) => {
        const label = labels[bucket.kind];
        if (!label) return null;
        return (
          <span
            key={bucket.kind}
            // These chips carry a ticker list, so one of them can be far wider
            // than a phone; nowrap made that overflow the page instead of
            // wrapping inside the chip.
            className="rounded-full px-3 py-1 sm:whitespace-nowrap"
            style={{ background: "var(--surface-sunken)" }}
          >
            <b className={label.colour}>
              {label.icon} {label.text}
              {/* app.py prints these with :.0f — a whole percent, not 96,4. The
                  "no data" chip carries no percentage at all. */}
              {bucket.kind !== "none" && ` · ${fmtEu(bucket.pct, { decimals: 0 })}%`}
            </b>
            {label.suffix && <span className="text-text/50"> {label.suffix}</span>}
            {!label.suffix && bucket.tickers.length > 0 && <span className="text-text/50"> – {bucket.tickers.join(", ")}</span>}
          </span>
        );
      })}
    </div>
  );
}
