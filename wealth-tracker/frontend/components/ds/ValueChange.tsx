// The only allowed way to show gain and loss.
//
// Three things at once, and that is the whole reason this is a component:
//   · an arrow (↑ ↓ –), so the table is also right in greyscale and for a
//     colour-blind reader — colour is never the only signal;
//   · the absolute value, because the sign is already in the arrow;
//   · green for up, red for down, muted for a movement within the threshold. A
//     negligible rise is no green party.
//
// Replaces components/MoveChip.tsx (the coloured pill) and
// components/SignedAmount.tsx. The pill is gone: a coloured surface behind a
// number is exactly the kind of decoration this design does not want.
//
// The formatting comes from lib/format.ts, so everything keeps the same number
// format and stays consistent with what the backend puts in its own labels.

import { fmtEu, fmtEuro, fmtPercent } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { tr } from "@/lib/i18n";

type Size = "sm" | "md" | "lg";

export default function ValueChange({
  value,
  percent = false,
  decimals,
  size = "md",
  showArrow = true,
  /** Movements within this are "flat": muted, not green or red. */
  flatThreshold = 0.005,
  className = "",
}: {
  value: number | null | undefined;
  percent?: boolean;
  decimals?: number;
  size?: Size;
  showArrow?: boolean;
  flatThreshold?: number;
  className?: string;
}) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className={`ds-change ds-change--flat ds-change--${size} ${className}`}>–</span>;
  }

  const tone = Math.abs(value) <= flatThreshold ? "flat" : value > 0 ? "gain" : "loss";
  const arrow = tone === "gain" ? "↑" : tone === "loss" ? "↓" : "–";
  const d = decimals ?? (percent ? 2 : 2);
  const body = percent
    ? fmtPercent(Math.abs(value), { decimals: d })
    : fmtEuro(Math.abs(value), { decimals: d });

  return (
    <span className={`ds-change ds-change--${tone} ds-change--${size} ${className}`}>
      {showArrow && (
        <span className="ds-change__arrow" aria-hidden>
          {arrow}
        </span>
      )}
      <span>{trueMinus(body)}</span>
      {/* What the arrow says, in words, for whoever can't see it. */}
      <span className="sr-only">{tone === "gain" ? tr(" up") : tone === "loss" ? tr(" down") : tr(" unchanged")}</span>
    </span>
  );
}

/**
 * A number that carries its own sign, without an arrow — for a sum that must add
 * up (unrealised + realised + dividend − costs). There the sign is the
 * arithmetic and an arrow would lie about what is there.
 */
export function SignedValue({
  value,
  prefix = "€",
  suffix = "",
  decimals = 2,
  className = "",
}: {
  value: number | null | undefined;
  /** "€" (default) or "" for a bare number. */
  prefix?: string;
  /** "%" for a percentage. */
  suffix?: string;
  decimals?: number;
  className?: string;
}) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className={`num text-ink-muted ${className}`}>–</span>;
  }
  const text = fmtEu(value, { decimals, prefix, suffix, plus: true });
  return (
    <span
      className={`num ${className}`}
      style={{ color: value >= 0 ? "var(--text-gain)" : "var(--text-loss)" }}
    >
      {trueMinus(text)}
    </span>
  );
}
