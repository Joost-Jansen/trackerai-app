"use client";

// One series over time with a dotted trend line (least squares) and in the head: the last value, the
// change according to the trend and the peak, all three over the visible window. `lowerIsBetter` for
// pace and resting HR: then the peak is the minimum, faster is higher in the chart and a drop is green.
//
// Draws with TimeChart: a real time axis, pointing with a crosshair, panning and zooming, and optionally a
// moving average. With `window` it follows the page's shared window (Trends); without it, it shows the
// whole series and zooms only locally (Routes).

import ChartHeadline from "@trackerai/ui/charts/ChartHeadline";
import TimeChart, { type ChartMarker, type MaOption } from "@/components/charts/TimeChart";
import { useLocale, useT } from "@/lib/i18n";
import { dayNumber, fmtDate, linearTrend, type DateWindow, type DayPoint } from "@/lib/timeline";

export type TrendPoint = DayPoint;
export { linearTrend };

export default function TrendChart({
  label,
  points,
  format,
  lowerIsBetter = false,
  colour = "var(--chart-1)",
  height = 180,
  unit = "",
  empty,
  window,
  domain,
  onWindow,
  onReset,
  maOptions,
  maDefault = 0,
  storageKey,
  clock = false,
  markers,
  onPick,
}: {
  label: string;
  points: TrendPoint[];
  format: (v: number) => string;
  lowerIsBetter?: boolean;
  colour?: string;
  height?: number;
  unit?: string;
  empty?: string;
  window?: DateWindow;
  domain?: DateWindow;
  onWindow?: (w: DateWindow) => void;
  onReset?: () => void;
  maOptions?: MaOption[];
  maDefault?: number;
  storageKey?: string;
  /** Values are seconds: axis on round clock values. */
  clock?: boolean;
  /** Vertical markers (diamonds), for example runs that do not count. */
  markers?: ChartMarker[];
  /** A click or Enter on a day (TimeChart onPick). */
  onPick?: (day: string) => void;
}) {
  const tc = useT().charts;
  const { locale } = useLocale();
  if (points.length < 2) return <p className="py-6 text-center text-sm text-ink-muted">{empty ?? tc.tooLittle}</p>;

  const inView = window ? points.filter((p) => p.d >= window.from && p.d <= window.to) : points;
  const sign = lowerIsBetter ? -1 : 1;
  const headline = (() => {
    if (inView.length === 0) return null;
    const trend = linearTrend(inView);
    const last = inView[inView.length - 1];
    const peak = inView.reduce((b, p) => (sign * p.v > sign * b.v ? p : b), inView[0]);
    const change = trend.length ? trend[1].v - trend[0].v : 0;
    const better = sign * change > 0;
    const flat = Math.abs(change) < 1e-9 || format(Math.abs(change)) === format(0);
    const weeks = trend.length ? Math.round((dayNumber(trend[1].d) - dayNumber(trend[0].d)) / 7) : 0;
    return {
      big: `${format(last.v)}${unit}`,
      primary: flat ? tc.same : tc.trend(`${change > 0 ? "+" : "−"}${format(Math.abs(change))}${unit}`, weeks),
      tone: flat ? "text-ink-muted" : better ? "text-gain" : "text-loss",
      secondary: tc.peakOn(lowerIsBetter, `${format(peak.v)}${unit}`, fmtDate(peak.d, true, locale)),
    };
  })();

  return (
    <div>
      {headline ? (
        <ChartHeadline big={headline.big} primary={headline.primary} primaryTone={headline.tone} secondary={headline.secondary} />
      ) : (
        <ChartHeadline big="–" primary={tc.noMeasure} secondary={tc.lastOn(`${format(points[points.length - 1].v)}${unit}`, fmtDate(points[points.length - 1].d, true, locale))} />
      )}
      <TimeChart
        ariaLabel={label}
        height={height}
        invert={lowerIsBetter}
        format={format}
        unit={unit}
        window={window}
        domain={domain}
        onWindow={onWindow}
        onReset={onReset}
        maOptions={maOptions}
        maDefault={maDefault}
        storageKey={storageKey}
        legend={false}
        clock={clock}
        markers={markers}
        onPick={onPick}
        series={[{ key: "v", label, colour, points, ma: true, trend: true, peak: lowerIsBetter ? "min" : "max", width: 2 }]}
      />
    </div>
  );
}
