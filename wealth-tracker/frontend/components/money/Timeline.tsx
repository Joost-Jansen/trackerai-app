"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Tabs } from "@/components/ds";
import { periodTabs, PERIODS } from "@/lib/timeline";
import { tr } from "@/lib/i18n";

export type TimelineChip = { label: string; onRemove?: () => void };

/** One fixed control for period and additional filters on analysis tabs. */
export default function Timeline({ period, onPeriod, chips = [], count = 0, label = "Filters", children }: {
  period: string;
  onPeriod: (period: string) => void;
  chips?: TimelineChip[];
  count?: number;
  label?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const pointer = useRef<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !bar.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  return <div ref={bar} className="time-filterbar sticky top-[60px] z-20 min-w-0"
    onPointerEnter={(event) => { if (event.pointerType === "mouse") setOpen(true); }}
    onPointerLeave={(event) => { if (event.pointerType === "mouse") setOpen(false); }}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}
    onKeyDown={(event) => {
      if (event.key === "Enter" || event.key === " ") pointer.current = null;
      if (event.key === "Escape") { setOpen(false); button.current?.focus(); }
    }}>
    <div className="flex min-w-0 items-center justify-between gap-3" style={{ borderBottom: "1px solid var(--rule)" }}>
      <div className="flex min-w-0 items-center gap-2 overflow-x-auto no-scrollbar py-2">
        <Tabs items={periodTabs(PERIODS)} value={period} onChange={onPeriod} variant="quiet"
          ariaLabel={tr("Period")} className="shrink-0 whitespace-nowrap" />
        {chips.length > 0 && <span className="mx-1 h-5 shrink-0 border-l" style={{ borderColor: "var(--rule)" }} aria-hidden />}
        {chips.map((chip, index) => chip.onRemove ? (
          <button key={`${chip.label}-${index}`} type="button" onClick={chip.onRemove}
            title={tr("Remove filter {0}", chip.label)} aria-label={tr("Remove filter {0}", chip.label)}
            className="time-filterbar__chip max-w-48 shrink-0 rounded-full border px-2.5 py-1 text-xs">
            <span className="truncate">{chip.label}</span><span aria-hidden className="shrink-0">×</span>
          </button>
        ) : <span key={`${chip.label}-${index}`} className="time-filterbar__chip max-w-48 shrink-0 rounded-full border px-2.5 py-1 text-xs">{chip.label}</span>)}
      </div>
      <button ref={button} type="button" aria-controls={panelId} aria-expanded={open}
        onPointerDown={(event) => { pointer.current = event.pointerType; }}
        onClick={() => setOpen((value) => pointer.current === "mouse" ? true : !value)}
        className="time-filterbar__button shrink-0 rounded-md px-3 py-2 text-xs font-medium text-ink-muted focus-visible:outline-2 focus-visible:outline-offset-2"
        data-open={open}>
        {label}{count > 0 ? ` · ${count}` : ""} <span aria-hidden>{open ? "▴" : "▾"}</span>
      </button>
    </div>
    <div id={panelId} inert={!open} data-open={open} className="time-filterbar__panel" role="region" aria-label={label}>
      <div className="mb-3 border-b pb-2 text-xs font-semibold uppercase tracking-wide" style={{ borderColor: "var(--rule)" }}>{label}</div>
      {children}
    </div>
  </div>;
}
