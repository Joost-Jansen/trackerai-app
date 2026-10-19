// The amount of one item: a number field, a slider and, when you have a usual portion, chips for ½ to 2 of it. An
// estimated amount (from a photo, later) shows "≈" muted with a dotted underline until you touch it.

import { useEffect, useState } from "react";
import { useFormat, useT } from "@/lib/i18n";
import type { Unit } from "@/lib/nutrition";

const CHIPS = [0.5, 1, 1.5, 2];

export default function GramField({ value, unit, portion, estimated = false, label, onChange }: {
  value: number;
  unit: Unit;
  portion?: number | null;
  estimated?: boolean;
  label: string;
  onChange: (grams: number) => void;
}) {
  const t = useT().nutrition.editor;
  const f = useFormat();
  const max = Math.max(500, Math.ceil((value * 2) / 50) * 50, portion ? Math.ceil((portion * 2.5) / 50) * 50 : 0);
  // to 0.1 g like the server stores it, so "2,5" g of oil can be typed (the slider moves in whole steps)
  const set = (v: number) => onChange(Math.max(0.1, Math.min(5000, Math.round(v * 10) / 10)));
  // The field keeps what you type (also an empty box halfway); a valid number goes through at once.
  const [text, setText] = useState(f.input(value));
  useEffect(() => {
    if (f.parse(text) !== value) setText(f.input(value));
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <input
          type="range"
          aria-label={label}
          min={0}
          max={max}
          step={5}
          value={Math.min(value, max)}
          onChange={(e) => set(Number(e.target.value))}
          onKeyDown={(e) => {
            if (e.shiftKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
              e.preventDefault();
              set(value + (e.key === "ArrowRight" ? 1 : -1));
            }
          }}
          className="min-w-0 flex-1 accent-[var(--surface-brand)]"
        />
        <span className="flex items-center gap-1">
          {estimated && <span className="text-[12px] text-ink-muted">≈</span>}
          <input
            type="text"
            inputMode="decimal"
            aria-label={t.amount(unit)}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              const v = f.parse(e.target.value);
              if (v != null && Number.isFinite(v) && v > 0) set(v);
            }}
            onBlur={() => setText(f.input(value))}
            className={`ds-input h-8 w-[4.5rem] text-right tabular-nums ${estimated ? "text-ink-muted underline decoration-dotted underline-offset-4" : ""}`}
          />
          <span className="text-[12px] text-ink-muted">{unit}</span>
          {estimated && <span className="text-[11px] text-ink-muted">({t.estimated})</span>}
        </span>
      </div>
      {portion ? (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t.portion}>
          <span className="text-[11.5px] text-ink-muted">{t.portion} {f.num(portion)} {unit}:</span>
          {CHIPS.map((c) => {
            const grams = Math.round(portion * c);
            return (
              <button key={c} type="button" onClick={() => set(grams)}
                className={`rounded-full border px-2 py-0.5 text-[11.5px] tabular-nums ${grams === Math.round(value) ? "border-[var(--surface-brand)] text-brand" : "border-border text-ink-muted"}`}>
                {t.portionChip(f.trim(c, 1))}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
