"use client";

// "Show all 12 sectors" — the detail a card does have but does not show.
//
// Every chart on this page cuts off: the distribution bar rolls everything below
// the top five into "Other", the bars stop at fifteen or twenty. That is the
// right first look and the wrong end point, because the data is there. This is
// the button in between: closed by default, and the text says how much is behind
// it instead of "more".

import { useId, useState } from "react";
import { ChevronDownIcon } from "@trackerai/ui/icons";
import { tr } from "@/lib/i18n";

export default function Disclosure({
  label,
  labelOpen = tr("Hide details"),
  children,
}: {
  /**
   * What is on the button when closed. Name the number: "Show all 12 sectors"
   *  tells the reader whether clicking is worth it, "More" does not.
   */
  label: string;
  labelOpen?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <div className="mt-3 pt-2.5" style={{ borderTop: "1px solid var(--border-hairline)" }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={panelId}
        className="-my-1 inline-flex items-center gap-1.5 py-1 text-xs font-medium text-ink-muted hover:text-text"
      >
        {open ? labelOpen : label}
        <ChevronDownIcon className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div id={panelId} className="mt-3">
          {children}
        </div>
      )}
    </div>
  );
}
