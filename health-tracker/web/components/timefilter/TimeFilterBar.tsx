"use client";

// The time bar of Trends: always in view
// (sticks under the top bar), the periods on the left, on the right "Aanpassen" (adjust) with a
// panel for a custom from-to, pan and zoom buttons and an overview of the
// whole history to drag the window in.
//
// The panel only opens with a click or tap on "Aanpassen" (not on hover, which
// made it slide over the charts unexpectedly) and closes with the same
// button, a click next to it or Escape.

import { useEffect, useId, useRef, useState } from "react";
import { Button, Input, Tabs } from "@/components/ds";
import RangeBrush from "@/components/timefilter/RangeBrush";
import type { TimeRange } from "@/components/timefilter/useTimeRange";
import { PERIODS, fmtWindow, moveWindow, windowDays, type DayPoint } from "@/lib/timeline";
import { useLocale, useT } from "@/lib/i18n";


/** Height of the fixed top bar (`.ds-topbar` in app/ds.css: height 60px). The time bar sticks below it. */
export const TOPBAR_HEIGHT = 60;

export default function TimeFilterBar({
  range,
  first,
  last,
  overview,
  label,
  extra,
}: {
  range: TimeRange;
  first: string;
  last: string;
  /** Silhouette in the overview, for example fitness per day. */
  overview?: DayPoint[];
  label?: string;
  /** A page's own filter, on the right next to "Adjust" in the same style (Trends: the sport). */
  extra?: React.ReactNode;
}) {
  const T = useT().texts;
  const { locale } = useLocale();
  const TF = T.trends.timeFilter;
  const periodLabel = (p: string) => T.trends.periods[p] ?? p;
  const PERIOD_TABS = PERIODS.map((id) => ({ id, label: periodLabel(id) }));
  label ??= TF.group;
  const [open, setOpen] = useState(false);
  const [stuck, setStuck] = useState(false);
  const panelId = useId();
  const bar = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const { window: w, period, custom, choose, change, reset } = range;
  const valid = w.from <= w.to && w.from >= first && w.to <= last;

  // A hairline under the bar as soon as it sticks; before that it sits plainly in the page.
  useEffect(() => {
    let frame = 0;
    const check = () => {
      frame = 0;
      const top = bar.current?.getBoundingClientRect().top;
      setStuck(top !== undefined && top <= TOPBAR_HEIGHT + 0.5 && window.scrollY > 0);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(check);
    };
    check();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (e: PointerEvent) => {
      if (e.target instanceof Node && !bar.current?.contains(e.target)) setOpen(false);
    };
    const closeOnEscape = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const days = windowDays(w);
  const current = custom ? (
    <button
      type="button"
      onClick={reset}
      title={TF.backTo(periodLabel(range.preset))}
      aria-label={TF.removeCustom(fmtWindow(w, locale), periodLabel(range.preset))}
      className="inline-flex max-w-full shrink-0 items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-1 text-xs transition-colors hover:bg-surface"
    >
      <span className="truncate tabular-nums">{fmtWindow(w, locale)}</span>
      <span aria-hidden className="shrink-0 text-ink-muted">×</span>
    </button>
  ) : (
    <span className="shrink-0 whitespace-nowrap text-xs tabular-nums text-ink-muted">{fmtWindow(w, locale)}</span>
  );

  return (
    <div
      ref={bar}
      className="sticky z-20 -mx-4 min-w-0 px-4 sm:-mx-6 sm:px-6 lg:-mx-page lg:px-page"
      style={{
        top: TOPBAR_HEIGHT,
        background: "var(--surface-page)",
        borderBottom: `1px solid ${stuck ? "var(--border-hairline)" : "transparent"}`,
        transition: "border-color 160ms ease",
      }}
      onBlur={(e) => {
        if (e.relatedTarget && !e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <div className="relative">
        <div className="flex min-w-0 items-center justify-between gap-3">
          <div className="no-scrollbar flex min-w-0 items-center gap-2 overflow-x-auto py-2.5">
            <Tabs items={PERIOD_TABS} value={period} onChange={choose} variant="quiet" ariaLabel={label} className="shrink-0 whitespace-nowrap" />
            <span className="mx-1 hidden h-5 shrink-0 border-l border-border sm:block" aria-hidden />
            <span className="hidden sm:contents">{current}</span>
          </div>
          <span className="flex shrink-0 items-center gap-1">
          {extra && <span className="hidden sm:contents">{extra}</span>}
          <button
            ref={button}
            type="button"
            aria-controls={panelId}
            aria-expanded={open}
            data-open={open}
            onClick={() => setOpen((v) => !v)}
            className="shrink-0 rounded-md px-3 py-2 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 data-[open=true]:bg-surface-2 data-[open=true]:text-ink"
          >
            {TF.adjust} <span aria-hidden>{open ? "▴" : "▾"}</span>
          </button>
          </span>
        </div>

        {/* On a phone the window does not fit next to the periods: a line of its own below. */}
        <div className="-mt-1 flex items-center justify-between gap-2 pb-2 sm:hidden">
          {current}
          {extra}
        </div>

        <div
          id={panelId}
          inert={!open}
          data-open={open}
          role="region"
          aria-label={TF.panel}
          className="absolute right-0 top-full w-full max-w-[720px] overflow-y-auto rounded-b-md p-4 transition-[opacity,transform,visibility] duration-150 ease-out motion-reduce:transition-none"
          style={{
            maxHeight: "min(70vh, 560px)",
            background: "var(--surface-card)",
            border: "1px solid var(--border-hairline)",
            boxShadow: "0 18px 36px rgba(0, 0, 0, .16)",
            opacity: open ? 1 : 0,
            transform: open ? "translateY(0)" : "translateY(-8px)",
            visibility: open ? "visible" : "hidden",
            pointerEvents: open ? "auto" : "none",
          }}
        >
          <div className="mb-3 flex items-center justify-between gap-3 border-b border-border pb-2">
            <span className="text-xs font-semibold uppercase tracking-wide">{TF.period}</span>
            <span className="flex items-center gap-3">
              <span className="text-xs tabular-nums text-ink-muted">{TF.days(days)}</span>
              <button type="button" onClick={() => setOpen(false)} aria-label={TF.close} title={TF.close} className="rounded px-1.5 text-sm leading-none text-ink-muted hover:bg-surface-2 hover:text-ink">
                ×
              </button>
            </span>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Input
              label={TF.from}
              type="date"
              value={w.from}
              min={first}
              max={w.to}
              onChange={(e) => {
                if (e.target.value) change({ ...w, from: e.target.value });
              }}
            />
            <Input
              label={TF.to}
              type="date"
              value={w.to}
              min={w.from}
              max={last}
              onChange={(e) => {
                if (e.target.value) change({ ...w, to: e.target.value });
              }}
            />
            <div className="flex gap-1 pb-0.5" role="group" aria-label={TF.moveGroup}>
              <Button size="sm" variant="ghost" aria-label={TF.previous} title={TF.previous} disabled={!valid || w.from <= first} onClick={() => change(moveWindow(w, first, last, 1, -1))}>
                ←
              </Button>
              <Button size="sm" variant="ghost" aria-label={TF.zoomIn} title={TF.zoomIn} disabled={!valid || days <= 7} onClick={() => change(moveWindow(w, first, last, 0.5))}>
                +
              </Button>
              <Button size="sm" variant="ghost" aria-label={TF.zoomOut} title={TF.zoomOut} disabled={!valid || (w.from === first && w.to === last)} onClick={() => change(moveWindow(w, first, last, 2))}>
                −
              </Button>
              <Button size="sm" variant="ghost" aria-label={TF.next} title={TF.next} disabled={!valid || w.to >= last} onClick={() => change(moveWindow(w, first, last, 1, 1))}>
                →
              </Button>
            </div>
          </div>
          <div className="mt-4">
            <RangeBrush first={first} last={last} window={w} onChange={change} points={overview} />
          </div>
          <p className="mt-3 text-[11.5px] leading-relaxed text-ink-muted">
            {TF.help}
          </p>
        </div>
      </div>
    </div>
  );
}
