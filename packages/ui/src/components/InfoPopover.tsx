"use client";

// A small "i" that explains a figure on click — for the sentence a number
// needs but does not deserve permanent space for.
//
// Click, not hover: the apps are read on a phone as much as on a laptop, and
// a hover tooltip is unreachable with a thumb. Escape and any outside click
// close it, the same two gestures the account menu in the app layout uses.
//
// The panel is positioned against the *viewport*, not against the trigger.
// Anchoring it to the button (absolute + left-0) put it off the right edge of
// a phone whenever the "i" sat past the middle of its line — a max-width can
// cap how wide the panel gets but cannot pull it back on screen. Fixed
// coordinates, clamped to a 16px margin, work wherever the trigger lands.

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { InfoIcon } from "../icons";

const MARGIN = 16;
const MAX_WIDTH = 320;
const GAP = 6; // between the trigger and the panel

export default function InfoPopover({
  label,
  children,
}: {
  /** What the button announces to a screen reader, e.g. "Explanation transaction costs". */
  label: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  const place = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    const width = Math.min(MAX_WIDTH, window.innerWidth - 2 * MARGIN);
    // Prefer to start at the trigger, but never cross either margin.
    const left = Math.min(Math.max(r.left, MARGIN), window.innerWidth - width - MARGIN);
    setPos({ top: r.bottom + GAP, left, width });
  }, []);

  // Lay out before paint, so the panel never flashes at the wrong spot.
  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    // Fixed coordinates go stale the moment anything moves; recompute rather
    // than close, so scrolling a little does not dismiss what you are reading.
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  return (
    <span className="inline-flex align-middle" ref={wrapRef}>
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={label}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        // A 23px hit box pulled back to a 15px footprint by the negative
        // margin: the icon stays the size the design draws it, but a thumb has
        // something to land on.
        className={`-m-1 grid h-[23px] w-[23px] place-items-center rounded-full transition-colors hover:text-brand ${
          open ? "text-brand" : "text-ink-muted"
        }`}
      >
        <InfoIcon className="h-[13px] w-[13px]" />
      </button>
      {open && pos && (
        <span
          id={panelId}
          role="note"
          style={{
            top: pos.top,
            left: pos.left,
            width: pos.width,
            background: "var(--surface-card)",
            // Hairline *and* shadow: this really floats above the page, and that is exactly
            // where this design does allow a shadow.
            boxShadow: "inset 0 0 0 1px var(--border-hairline), var(--shadow-3)",
            // The panel hangs in the DOM *below* its trigger, and that trigger now also sits
            // next to a section header — 11px small caps with 0.11em spacing. Without these
            // three rules a whole explanation inherits that, and then a paragraph shows up
            // IN CAPITALS WITH GAPS BETWEEN THEM. Fixed positioning takes it out of the
            // flow, not out of the inheritance.
            textTransform: "none",
            letterSpacing: "normal",
            fontFamily: "var(--font-sans)",
          }}
          className="fixed z-40 rounded-md p-3 text-left text-xs font-normal leading-relaxed text-ink-muted"
        >
          {children}
        </span>
      )}
    </span>
  );
}
