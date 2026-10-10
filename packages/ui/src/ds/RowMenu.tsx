"use client";

// "⋯" at the end of a table row: the actions for that row in a small menu, so a row with four actions still fits
// on one line. Closes on a click outside, on Escape, on scroll and after a choice. A `danger` item is shown in the
// loss colour. The menu is placed fixed next to the button, so a table that scrolls sideways cannot clip it.

import { useEffect, useRef, useState } from "react";

export type RowMenuItem = { label: string; onSelect: () => void; danger?: boolean };

export default function RowMenu({ label, items }: { label: string; items: RowMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState<{ top?: number; bottom?: number; right: number }>({ top: 0, right: 0 });
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const close = () => setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const height = items.length * 36 + 8;
          const right = window.innerWidth - r.right;
          // Open upwards when the row is too close to the bottom of the screen.
          setAt(r.bottom + 4 + height > window.innerHeight && r.top - 4 - height > 0 ? { bottom: window.innerHeight - r.top + 4, right } : { top: r.bottom + 4, right });
          setOpen((v) => !v);
        }}
        className="grid h-8 w-8 place-items-center rounded text-[18px] leading-none text-ink-muted hover:bg-[var(--surface-sunken)] hover:text-ink"
      >
        ⋯
      </button>
      {open && (
        <div
          role="menu"
          className="fixed z-40 min-w-48 overflow-hidden rounded-md py-1 text-left"
          style={{ top: at.top, bottom: at.bottom, right: at.right, background: "var(--surface-card, var(--surface))", boxShadow: "inset 0 0 0 1px var(--border-hairline), 0 8px 24px rgba(0,0,0,0.12)" }}
        >
          {items.map((i) => (
            <button
              key={i.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                i.onSelect();
              }}
              className="block w-full whitespace-nowrap px-3 py-2 text-left text-[13px] hover:bg-[var(--surface-sunken)]"
              style={i.danger ? { color: "var(--text-loss, var(--neg))" } : undefined}
            >
              {i.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
