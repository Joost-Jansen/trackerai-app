// The logo mark: wealth-tracker's wallet (MoneyMark.tsx), in every place the
// site shows its mark.
//
// The mark stands with its foot on the baseline of the text next to it. In a
// flex row `align-items: baseline` does that by itself: the baseline of an svg
// is its bottom edge.

import MoneyMark from "./MoneyMark";

export default function Logomark({
  /** Height in pixels. Set it to the height of the lowercase letters next to it. */
  height,
  className,
}: {
  height: number;
  className?: string;
}) {
  return <MoneyMark height={height} className={className} />;
}
