"use client";

// Bars side by side along an axis you read yourself: months, years, or the
// twelve calendar months. One bar may consist of several pieces
// (received + still expected), stacked.
//
// Divs and not svg, unlike LineChart and ValueChart. Those two stretch one
// viewBox with preserveAspectRatio="none" across the card: fine for a
// line, but it also distorts the rounding of a bar top and the width of a
// gap, and those two carry the meaning here. Flexbox keeps every bar
// equally wide and every gap exactly 2px, on every screen.
//
// The readout line sits above the chart, not as a floating tooltip on it. A
// tooltip that appears next to the last bar falls off the screen on a phone,
// and one that flips back for that jumps. This line always has the same
// height: at rest it shows the summary, with a finger on a bar it shows that
// bar. So the chart does not move when you touch it.

import { useId, useState } from "react";
import { useTr } from "../i18n";

export type BarSegment = {
  /** Unique within the bar; also becomes the legend key. */
  key: string;
  value: number;
  colour: string;
  /** Hatched instead of solid: the piece is an estimate, not a fact. */
  estimate?: boolean;
};

export type BarDatum = {
  key: string;
  /** What is shown under the bar. */
  label: string;
  /** What the readout line shows when this bar is active. Default: `label`. */
  title?: string;
  segments: BarSegment[];
  /** Quiet text after the amount in the readout line, for example "3 payments". */
  note?: string;
};

export type BarLegendItem = { key: string; label: string; colour: string; estimate?: boolean };

/** A hatched fill for an estimate: the same colour, half as present, with
 *  diagonal stripes through it. Even without seeing colour, "this piece is
 *  estimated" stays visible: on a black-and-white print and for anyone who
 *  cannot tell the two tints apart. */
function fill(colour: string, estimate?: boolean): React.CSSProperties {
  if (!estimate) return { background: colour };
  // The underlayer must be a different colour from the stripes, otherwise there
  // is nothing to see: the first version laid the gradient over the same colour,
  // so the transparent parts showed exactly that colour and the hatching
  // vanished into a flat tint. Now the gaps are the card itself.
  return {
    background: `repeating-linear-gradient(135deg, ${colour} 0 4px, transparent 4px 8px), var(--surface)`,
  };
}

function Swatch({ colour, estimate }: { colour: string; estimate?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-2.5 w-2.5 flex-none rounded-[3px]"
      style={fill(colour, estimate)}
    />
  );
}

export default function Bars({
  bars,
  legend,
  format,
  summary,
  labelEvery = 1,
  height = "h-[150px] sm:h-[180px]",
  maxBarWidth = 64,
  ariaLabel,
  emptyLabel,
  onSelect,
}: {
  bars: BarDatum[];
  /** Only needed from two kinds of pieces: with one, the card title already says it. */
  legend?: BarLegendItem[];
  format: (v: number) => string;
  /** What the readout line shows while you are not on any bar. */
  summary: React.ReactNode;
  /** Every how-manyth bar gets a label. With 24 months that is not 24 labels. */
  labelEvery?: number;
  height?: string;
  /** Upper bound on the width of one bar, in pixels. Otherwise six year bars across
   *  a wide screen become blocks of a hundred pixels: that reads as a wall, not
   *  as a series. On a phone nothing reaches this bound. */
  maxBarWidth?: number;
  ariaLabel: string;
  emptyLabel?: string;
  /** A click on a bar, with its `key`: for example to pick that month. */
  onSelect?: (key: string) => void;
}) {
  const tr = useTr();
  emptyLabel ??= tr("Nothing to show yet.");
  const [active, setActive] = useState<number | null>(null);
  const idPrefix = useId();

  if (bars.length === 0) {
    return <p className="py-6 text-center text-sm text-ink-muted">{emptyLabel}</p>;
  }

  const totals = bars.map((b) => b.segments.reduce((sum, s) => sum + s.value, 0));
  // Never scale against 0: then every height becomes NaN. Negative totals (a
  // reversed payout) get no bar but do appear in the readout line: the height
  // cannot tell it, the amount can.
  const peak = Math.max(...totals, Number.EPSILON);
  const shown = active !== null ? bars[active] : null;

  return (
    <div>
      {/* Fixed height by construction: two lines on a phone, one from sm up,
          the same in both states, so the chart below stays put. */}
      <div className="mb-2 flex min-h-[34px] flex-col gap-y-0.5 sm:min-h-[20px] sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-x-2.5">
        {shown ? (
          <>
            <span className="text-[13px] font-semibold">{shown.title ?? shown.label}</span>
            <span className="num text-[13px] font-semibold">
              {format(totals[active!])}
            </span>
            {shown.note && <span className="text-xs text-ink-muted">{shown.note}</span>}
          </>
        ) : (
          <span className="text-[13px] text-ink-muted">{summary}</span>
        )}
      </div>

      {/* role="group" and not role="img": every bar is a button with its own
          amount in the label, and an img around it would hide exactly those
          buttons from a screen reader. The chart here is a list of values,
          not a picture. */}
      <div
        role="group"
        aria-label={ariaLabel}
        className={`flex items-end justify-center gap-[2px] ${height}`}
        onMouseLeave={() => setActive(null)}
      >
        {bars.map((bar, i) => {
          const total = totals[i];
          const isActive = i === active;
          return (
            <button
              key={bar.key}
              type="button"
              // Tabbable: the readout line is the only place with the exact amount,
              // so it must be reachable without a mouse too.
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              onMouseEnter={() => setActive(i)}
              // Point, do not toggle. A tap first gives the button focus
              // (which makes it active) and only then comes the click; that
              // saw "already on" and switched it off again at once. With a mouse
              // you do not notice because hover takes over, but on a
              // phone no bar did anything. Releasing happens on
              // blur or by leaving the chart.
              onClick={() => {
                setActive(i);
                onSelect?.(bar.key);
              }}
              aria-label={`${bar.title ?? bar.label}: ${format(total)}`}
              style={{ maxWidth: maxBarWidth }}
              className="group flex h-full min-w-0 flex-1 flex-col justify-end gap-[2px] rounded-t-[4px] outline-none"
            >
              {/* Draw from top to bottom: the last piece in the list
                  belongs at the bottom, against the baseline. */}
              {[...bar.segments].reverse().map((seg, si) => {
                const share = Math.max(seg.value, 0) / peak;
                if (share <= 0) return null;
                return (
                  <span
                    key={seg.key}
                    aria-hidden="true"
                    className={`block w-full ${si === 0 ? "rounded-t-[4px]" : ""}`}
                    style={{
                      // At least 2px: a payout of 40 cents next to one of
                      // €60 must stay visible as "there was something".
                      height: `max(${(share * 100).toFixed(3)}%, 2px)`,
                      ...fill(seg.colour, seg.estimate),
                      filter: isActive ? "brightness(1.12)" : undefined,
                    }}
                  />
                );
              })}
              {/* An empty month has no bar and so no hit area. This
                  sliver of nothing keeps it pointable and shows that it is
                  empty rather than missing. */}
              {total <= 0 && (
                <span aria-hidden="true" className="block h-[2px] w-full bg-border-strong" />
              )}
            </button>
          );
        })}
      </div>

      {/* whitespace-nowrap and no overflow-hidden: with 24 months a cell is
          about fifteen pixels wide and "mrt" broke into "m rt", two lines
          stacked. The label may stick out over its neighbours: with
          labelEvery those are empty anyway. */}
      <div aria-hidden="true" className="mt-1.5 flex justify-center gap-[2px]">
        {bars.map((bar, i) => (
          <span
            key={`${idPrefix}-${bar.key}`}
            style={{ maxWidth: maxBarWidth }}
            className={`min-w-0 flex-1 whitespace-nowrap text-center text-[11px] leading-tight ${
              i === active ? "font-semibold text-text" : "text-ink-muted"
            }`}
          >
            {i % labelEvery === 0 || i === bars.length - 1 ? bar.label : ""}
          </span>
        ))}
      </div>

      {legend && legend.length > 1 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3.5 gap-y-1 text-[11px] text-ink-muted">
          {legend.map((item) => (
            <span key={item.key} className="inline-flex items-center gap-1.5">
              <Swatch colour={item.colour} estimate={item.estimate} />
              {item.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
