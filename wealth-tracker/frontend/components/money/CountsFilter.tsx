"use client";

// Filtering on where transactions count on Net worth: Saved, Bank & cash, money of
// others, the net-zero ones and what doesn't count at all. One or more at a time;
// none chosen is everything. See lib/counts-as.ts.

import { COUNTS_AS, type CountsAs } from "@/lib/counts-as";
import { tr } from "@/lib/i18n";

export default function CountsFilter({ value, onChange }: {
  value: CountsAs[]; onChange: (value: CountsAs[]) => void;
}) {
  const chosen = new Set(value);
  const toggle = (code: CountsAs) =>
    onChange(COUNTS_AS.map((k) => k.code).filter((c) => (c === code ? !chosen.has(c) : chosen.has(c))));

  const pill = (key: string, label: string, title: string | undefined, active: boolean, onClick: () => void) => (
    <button key={key} type="button" aria-pressed={active} onClick={onClick} title={title}
      className="rounded-full border px-3 py-1.5 text-xs transition-colors"
      style={{ borderColor: active ? "var(--text-primary)" : "var(--rule)", background: active ? "var(--surface-inset)" : "transparent", fontWeight: active ? 600 : 400 }}>
      {label}
    </button>
  );

  return (
    <div className="flex flex-wrap items-center gap-2 pb-5" role="group" aria-label={tr("Filter on where it counts")}>
      <span className="mr-1 text-xs text-ink-muted">{tr("Counts as")}</span>
      {pill("all", tr("Any"), undefined, value.length === 0, () => onChange([]))}
      {COUNTS_AS.map((k) => pill(k.code, k.label(), k.hint(), chosen.has(k.code), () => toggle(k.code)))}
    </div>
  );
}

/** The label of one choice, for a chip in the filter bar. */
export const countsLabel = (code: CountsAs) => COUNTS_AS.find((k) => k.code === code)?.label() ?? code;
