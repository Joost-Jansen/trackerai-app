// Share of time easy (Z1 + Z2) against the 80/20 rule of thumb: a meter with a mark at 80%.

import { useT } from "@/lib/i18n";
import { EASY_LOW, EASY_TARGET, easyPct, type Zone } from "@/lib/training";

export default function EasyShare({ pct, className = "" }: { pct: Record<Zone, number>; className?: string }) {
  const t = useT().zones;
  const easy = easyPct(pct);
  const ok = easy >= EASY_LOW;
  return (
    <div className={`flex flex-col gap-1.5 ${className}`} title={t.easyMethod}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-[13px]">
        <span>
          <span className="font-medium">{t.easy}</span>{" "}
          <span className={`font-semibold tabular-nums ${ok ? "text-gain" : "text-[var(--warn)]"}`}>{Math.round(easy)}%</span>
        </span>
        <span className="text-[11.5px] text-ink-muted">{t.easyTarget(EASY_TARGET)}</span>
      </div>
      <div className="relative h-2 rounded-full" style={{ background: "var(--surface-inset)" }} role="img" aria-label={t.easyAria(Math.round(easy), EASY_TARGET)}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, easy)}%`, background: ok ? "var(--data-gain)" : "var(--warn)" }} />
        <div className="absolute -top-1 -bottom-1 w-[2px] rounded-full bg-[var(--text-primary)]" style={{ left: `calc(${EASY_TARGET}% - 1px)` }} aria-hidden />
      </div>
    </div>
  );
}
