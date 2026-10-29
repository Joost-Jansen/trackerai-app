"use client";

// A page's own title in the top bar (the layout gives the slots): a way back, the title, a line under it, and the
// page's own buttons at the right.

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { ChevronLeftIcon } from "@trackerai/ui/icons";
import { TOPBAR_ACTIONS, TOPBAR_TITLE } from "@/lib/nav";

export default function TopbarTitle({
  title,
  meta,
  chips,
  back,
  backLabel,
  actions,
}: {
  title: string;
  meta?: string;
  chips?: React.ReactNode;
  back: string;
  backLabel: string;
  actions?: React.ReactNode;
}) {
  const [slots, setSlots] = useState<{ title: HTMLElement | null; actions: HTMLElement | null }>({ title: null, actions: null });
  useEffect(() => setSlots({ title: document.getElementById(TOPBAR_TITLE), actions: document.getElementById(TOPBAR_ACTIONS) }), []);
  return (
    <>
      {slots.title &&
        createPortal(
          <div className="flex min-w-0 items-center gap-1">
            <Link href={back} aria-label={backLabel} title={backLabel} className="ds-btn ds-btn--ghost ds-btn--sm -ml-1 !px-1.5">
              <ChevronLeftIcon className="h-4 w-4" />
            </Link>
            <div className="min-w-0">
              <h1 className="ds-topbar__title truncate !leading-tight">{title}</h1>
              {(meta || chips) && (
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
                  {meta && <span className="min-w-0 max-w-full truncate">{meta}</span>}
                  {chips}
                </div>
              )}
            </div>
          </div>,
          slots.title,
        )}
      {slots.actions && actions && createPortal(<div className="flex items-center gap-1.5">{actions}</div>, slots.actions)}
    </>
  );
}
