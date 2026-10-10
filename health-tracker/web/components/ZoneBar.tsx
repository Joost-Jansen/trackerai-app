// One horizontal bar per sport: the time per heart-rate zone side by side, with % and hours below.

import { useFormat, useT } from "@/lib/i18n";
import { ZONE_COLOUR, ZONES, easyPct, zoneRanges, type ZoneShare } from "@/lib/training";

export default function ZoneBar({ sport, share, bounds }: { sport: string; share: ZoneShare; bounds?: number[] }) {
  const t = useT();
  const f = useFormat();
  const ranges = bounds ? zoneRanges(bounds) : null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="font-medium">{t.sport(sport)}</span>
        <span className="text-ink-muted tabular-nums">
          {t.zones.easyShort} {Math.round(easyPct(share.pct))}% · {f.hours(share.total_s)}
        </span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }} role="img"
        aria-label={ZONES.map((z) => `${z} ${Math.round(share.pct[z])}%`).join(", ")}>
        {ZONES.map((z) => share.pct[z] > 0 && (
          <div key={z} style={{ width: `${share.pct[z]}%`, background: ZONE_COLOUR[z] }} title={`${z}: ${Math.round(share.pct[z])}%`} />
        ))}
      </div>
      <div className="grid grid-cols-5 gap-1 text-[11.5px] tabular-nums">
        {ZONES.map((z) => (
          <div key={z} className="flex flex-col">
            <span className="flex items-center gap-1 text-ink-muted">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: ZONE_COLOUR[z] }} />
              {z}
            </span>
            <span className="font-medium">{Math.round(share.pct[z])}%</span>
            <span className="text-ink-muted">{f.duration(share.seconds[z])}</span>
            {ranges && <span className="text-[10.5px] text-ink-muted">{ranges[z]}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
