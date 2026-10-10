// Target zone as a coloured label in the zone colours (--zone-1..5). A range (Z2-Z3) gets a gradient from the
// first to the last zone.

import { useT } from "@/lib/i18n";

const zoneVar = (n: number) => `var(--zone-${n})`;

export function zoneNumbers(zone: string | null | undefined): number[] {
  const n = (zone ?? "").match(/[1-5]/g)?.map(Number) ?? [];
  if (!n.length) return [];
  const lo = Math.min(...n), hi = Math.max(...n);
  return Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
}

export default function ZoneChip({ zone, className = "" }: { zone?: string | null; className?: string }) {
  const t = useT();
  const nums = zoneNumbers(zone);
  if (!nums.length) return null;
  const lo = nums[0], hi = nums[nums.length - 1];
  const bg = lo === hi
    ? `color-mix(in srgb, ${zoneVar(lo)} 30%, transparent)`
    : `linear-gradient(90deg, color-mix(in srgb, ${zoneVar(lo)} 34%, transparent), color-mix(in srgb, ${zoneVar(hi)} 34%, transparent))`;
  return (
    <span
      className={`inline-flex h-[22px] flex-none items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-[11px] font-semibold tabular-nums ${className}`}
      style={{ background: bg, boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${zoneVar(hi)} 45%, transparent)` }}
      title={t.plan.zoneTitle(lo === hi ? `Z${lo}` : `Z${lo}-Z${hi}`)}
    >
      <span className="flex gap-[2px]" aria-hidden>
        {[lo, hi].filter((z, i) => i === 0 || z !== lo).map((z) => (
          <span key={z} className="inline-block h-[7px] w-[7px] rounded-full" style={{ background: zoneVar(z) }} />
        ))}
      </span>
      {lo === hi ? `Z${lo}` : `Z${lo}–${hi}`}
    </span>
  );
}
