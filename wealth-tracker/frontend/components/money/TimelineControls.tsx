"use client";
import { useState } from "react";
import { Button, Input, Tabs } from "@/components/ds";
import { granularityTabs, moveWindow, periodTabs, periodWindow, PERIODS, type DateWindow } from "@/lib/timeline";
import { tr } from "@/lib/i18n";

/** `boundaries`: the salary boundaries when a month runs from salary to salary (lib/month-periods.ts). */
export function useTimeline(first: string, last: string, initial = "1Y", boundaries?: string[] | null) {
  const [period, setPeriod] = useState(initial);
  const [custom, setCustom] = useState<DateWindow | null>(null);
  const window = custom ?? periodWindow(period, first, last, boundaries);
  return {
    window,
    period,
    choose: (p: string) => {
      setPeriod(p);
      setCustom(null);
    },
    change: (w: DateWindow) => {
      setPeriod("Custom");
      setCustom(w);
    },
  };
}
export default function TimelineControls({
  timeline,
  first,
  last,
  granularity,
  onGranularity,
  showPeriods = true,
}: {
  timeline: ReturnType<typeof useTimeline>;
  first: string;
  last: string;
  granularity?: string;
  onGranularity?: (v: string) => void;
  showPeriods?: boolean;
}) {
  const { window, period, choose, change } = timeline;
  const valid = window.from <= window.to && window.from >= first && window.to <= last;
  return (
    <div className="flex flex-col gap-3 pb-4">
      {showPeriods && (
        <Tabs
          items={periodTabs(PERIODS)}
          value={period}
          onChange={choose}
          variant="quiet"
          ariaLabel={tr("Measured over")}
          className="flex-wrap"
        />
      )}
      <div className="flex flex-wrap items-end gap-2">
        <Input
          label={tr("From")}
          type="date"
          value={window.from}
          min={first}
          max={window.to}
          onChange={(e) => {
            if (e.target.value) change({ ...window, from: e.target.value });
          }}
        />
        <Input
          label={tr("Up to and including")}
          type="date"
          value={window.to}
          min={window.from}
          max={last}
          onChange={(e) => {
            if (e.target.value) change({ ...window, to: e.target.value });
          }}
        />
        <div className="flex gap-1 pb-0.5" role="group" aria-label={tr("Zoom and move the timeline")}>
          <Button
            size="sm"
            variant="ghost"
            aria-label={tr("Previous period")}
            title={tr("Previous period")}
            disabled={!valid || window.from <= first}
            onClick={() => change(moveWindow(window, first, last, 1, -1))}
          >
            ←
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={tr("Zoom in")}
            title={tr("Zoom in")}
            disabled={!valid || window.from === window.to}
            onClick={() => change(moveWindow(window, first, last, 0.5))}
          >
            +
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={tr("Zoom out")}
            title={tr("Zoom out")}
            disabled={!valid || (window.from === first && window.to === last)}
            onClick={() => change(moveWindow(window, first, last, 2))}
          >
            −
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={tr("Next period")}
            title={tr("Next period")}
            disabled={!valid || window.to >= last}
            onClick={() => change(moveWindow(window, first, last, 1, 1))}
          >
            →
          </Button>
        </div>
        {onGranularity && (
          <Tabs
            items={granularityTabs()}
            value={granularity}
            onChange={onGranularity}
            variant="segmented"
            ariaLabel={tr("Timeline detail")}
          />
        )}
      </div>
      {!valid && (
        <p role="alert" className="text-sm text-ink-muted">
          {tr("Choose dates within the available period, with the start date before the end date.")}
        </p>
      )}
    </div>
  );
}
