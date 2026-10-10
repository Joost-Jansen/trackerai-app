/**
 * The header of a chart card: one large number, one coloured line, one quiet one.
 *
 * A component and not three branches on the spot, because the *shape* must be the
 * same in all three states — at rest, with one finger on the line, and with two.
 * It was not: at rest "return …" and "deposits …" fell on two lines, while one
 * finger gave one shorter line — so the chart jumped up as soon as you touched
 * it and down again as soon as you put the second finger down. Below sm the
 * three pieces are now three lines by construction, not by the chance of what
 * fits; from sm it is one line on the shared baseline.
 *
 * Lived in the dashboard page, where it was written; the price card on a
 * position page reads out in exactly the same way and needs the same fixed
 * height.
 */

export default function ChartHeadline({
  big,
  primary,
  primaryTone = "text-ink-muted",
  secondary,
}: {
  big: React.ReactNode;
  primary: React.ReactNode;
  /** Tailwind colour class; different per state, which does not affect the height. */
  primaryTone?: string;
  secondary: React.ReactNode;
}) {
  return (
    // 21px in the display face: this is a supporting number, and in this design
    // those are at 21 or less — the screen's hero number is elsewhere.
    <div className="mb-2 flex flex-col gap-y-0.5 sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-3 sm:gap-y-1">
      <span className="num font-display text-[21px] leading-tight tracking-[-0.02em]">{big}</span>
      <span className="flex flex-col gap-y-0.5 sm:contents">
        <span className={`num text-[13.5px] ${primaryTone}`}>{primary}</span>
        <span className="num text-xs text-ink-muted">{secondary}</span>
      </span>
    </div>
  );
}
