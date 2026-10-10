// The wealth-tracker mark: a wallet, with a coin as the clasp.
//
// A sign, like health-tracker's heartbeat line: the same line style (stroke 2.4 on 32 wide, round caps and joins) and
// the same build with one accent.
//
//   the wallet  `currentColor`, so the same colour as the text next to it
//   the coin    `--logo-accent`, by default the theme's terracotta
//
// scripts/build-money-logo.mjs reads the shape from here and makes the app icons from it.

export const MONEY_VIEWBOX = "0 0 32 24";
export const MONEY_PATH = "M6 8.5h18a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V6.5a3 3 0 0 1 3-3h13";
export const MONEY_COIN = { cx: 22.5, cy: 15.5, r: 2.6 };

export default function MoneyMark({ height, className }: { height: number; className?: string }) {
  return (
    <svg
      viewBox={MONEY_VIEWBOX}
      height={height}
      width={Math.round(((height * 32) / 24) * 100) / 100}
      className={className}
      aria-hidden
      focusable="false"
    >
      <path d={MONEY_PATH} fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
      <circle {...MONEY_COIN} fill="var(--logo-accent, var(--brand-500))" />
    </svg>
  );
}
