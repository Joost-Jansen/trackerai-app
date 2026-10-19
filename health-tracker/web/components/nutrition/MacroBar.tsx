// One macro against its target: grams on the left, g/kg and the target range on the right, a bar with the range as
// a soft band behind it. Below the range is plain, within it gets a small check, far above shows the number in the
// same colour: no warning red (Voeding is bookkeeping, not a diet).

import { CheckIcon } from "@trackerai/ui/icons";
import { useFormat, useT } from "@/lib/i18n";

export default function MacroBar({ label, grams, range, perKg, perKgRange, colour }: {
  label: string;
  grams: number;
  /** Target in grams; null without a body weight. */
  range: [number, number] | null;
  perKg: number | null;
  perKgRange: [number, number];
  colour: string;
}) {
  const t = useT().nutrition;
  const f = useFormat();
  const top = Math.max(range ? range[1] * 1.15 : 0, grams * 1.05, 1);
  const within = range != null && grams >= range[0] && grams <= range[1];
  const pct = (v: number) => `${Math.min(100, (v / top) * 100)}%`;
  const aria = range ? t.rangeAria(label, f.num(grams), f.num(range[0]), f.num(range[1])) : t.noRangeAria(label, f.num(grams));
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
        <span className="flex items-baseline gap-2">
          <span className="text-ink-muted">{label}</span>
          <span className="font-display text-[20px] font-light leading-none tabular-nums">{f.num(grams)} g</span>
          {within && <CheckIcon width={13} height={13} className="self-center text-[var(--moss-500)]" aria-label={t.inRange} />}
        </span>
        <span className="tabular-nums text-ink-muted">
          {perKg != null && <span className="text-[var(--text-primary)]">{t.perKg(f.num(perKg, 1))}</span>}
          {" "}{t.ofRange(f.trim(perKgRange[0], 1), f.trim(perKgRange[1], 1))}
        </span>
      </div>
      <div role="img" aria-label={aria} className="relative h-2 overflow-hidden rounded-full bg-[var(--surface-inset)]">
        {range && (
          <span className="absolute inset-y-0 bg-[var(--target-band)] ring-1 ring-inset ring-[var(--border-strong,var(--border))]"
            style={{ left: pct(range[0]), width: `calc(${pct(range[1])} - ${pct(range[0])})` }} />
        )}
        <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: pct(grams), background: colour, opacity: 0.85 }} />
      </div>
    </div>
  );
}
