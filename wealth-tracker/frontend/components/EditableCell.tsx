"use client";

import { useEffect, useRef, useState } from "react";

/**
 * A table cell that turns into an input when clicked, and reports the new value
 * on Enter or blur. Escape abandons the edit.
 *
 * Streamlit could not put an editor in a cell, so app.py:657-718 hangs the
 * ticker override off a separate expander: pick the position again from a
 * dropdown, type, press a button. Here the cell you are looking at is the cell
 * you fix. The rebuild plan calls for this as a reusable component because the
 * later tabs edit in place too (Rebalancing's targets).
 *
 * Saving is the caller's business — this only reports. `pending` and `error`
 * come back from the caller, since only it knows whether the ISIN's price
 * re-fetch actually succeeded.
 */
export default function EditableCell({
  value,
  onSave,
  pending = false,
  placeholder,
  title,
  ariaLabel,
}: {
  value: string;
  onSave: (next: string) => void;
  pending?: boolean;
  placeholder?: string;
  title?: string;
  ariaLabel?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  // A re-fetch rewrites the ticker (IQQH.DE -> the resolved symbol), and a
  // failed save leaves the old one; either way the cell should show what is
  // stored now, not what was typed, once editing is over.
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  function commit() {
    setEditing(false);
    const next = draft.trim();
    if (next && next !== value) onSave(next);
    else setDraft(value);
  }

  if (pending) {
    return <span className="italic text-text/50">saving…</span>;
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        title={title ?? "Click to edit"}
        aria-label={ariaLabel}
        className="rounded-xs border border-dashed border-transparent px-1 text-left hover:border-border hover:bg-surface-2"
      >
        {value || <span className="text-text/40">–</span>}
      </button>
    );
  }

  return (
    <input
      ref={inputRef}
      value={draft}
      autoFocus
      placeholder={placeholder}
      aria-label={ariaLabel}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") {
          setDraft(value);
          setEditing(false);
        }
      }}
      className="ds-input !h-8 w-28 !px-2"
    />
  );
}
