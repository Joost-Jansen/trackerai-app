"use client";

import { useEffect, useRef } from "react";
import { ChevronDownIcon } from "../icons";

/** Compact settings row. Children stay mounted when closed, so forms and uploads keep their state. */
export default function CollapsibleCard({ title, icon, summary, reveal = false, children, id, className = "" }: {
  title: string;
  icon: React.ReactNode;
  summary?: React.ReactNode;
  /** Open when an operation needs attention; the user can still close it afterwards. */
  reveal?: boolean;
  children: React.ReactNode;
  id?: string;
  className?: string;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (reveal && ref.current) ref.current.open = true;
  }, [reveal]);

  return (
    <details ref={ref} id={id} className={`group rounded border border-border bg-surface ${className}`}>
      <summary className="flex min-h-16 cursor-pointer list-none items-center gap-3 rounded p-4 outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--border-focus)] sm:px-[18px] [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="flex h-9 w-9 flex-none items-center justify-center rounded bg-surface-sunk text-ink-muted">{icon}</span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-[13.5px] font-semibold tracking-[0.01em]">{title}</span>
          {summary && <span className="text-[12px] text-ink-muted">{summary}</span>}
        </span>
        <ChevronDownIcon className="h-4 w-4 flex-none text-ink-muted transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border p-4 sm:p-[18px]">{children}</div>
    </details>
  );
}
