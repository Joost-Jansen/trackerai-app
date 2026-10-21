// Load: the last week (fatigue, 7 days) against what you are used to (fitness, 42 days), with three soft
// bands. Numbers and band come from api/dashboard.py load_indicator; the sentences from T.today.load.

import Card from "@trackerai/ui/components/Card";
import InfoPopover from "@trackerai/ui/components/InfoPopover";
import { useFormat, useT } from "@/lib/i18n";
import type { LoadIndicator } from "@/lib/training";

// The scale of the bar; values outside it sit on the edge.
const MIN = 0.4;
const MAX = 1.8;
const BAND_COLOUR = { low: "var(--zone-1)", build: "var(--zone-2)", high: "var(--zone-4)", unknown: "var(--text-faint)" };

const pos = (v: number) => `${((Math.min(MAX, Math.max(MIN, v)) - MIN) / (MAX - MIN)) * 100}%`;

/** `wide`: the card is alone in its row; then the bar sits next to the explanation instead of below it. */
export default function LoadCard({ load, wide = false, className = "" }: { load: LoadIndicator; wide?: boolean; className?: string }) {
  const t = useT().texts.today.load;
  const f = useFormat();
  /** 1,3 en 0,85 (1.3 and 0.85): no trailing zeros. */
  const num = (v: number, digits = 2) => f.trim(v, digits);
  const { low, high, ramp_high } = load.thresholds;
  const explain =
    load.band === "high" ? (load.reason === "ramp" ? t.highRamp(num(load.ramp ?? 0, 1)) : t.highRatio(num(high))) : t.explain[load.band];
  const segments = [
    { key: "low", from: MIN, to: low },
    { key: "build", from: low, to: high },
    { key: "high", from: high, to: MAX },
  ] as const;
  const known = load.acwr != null;
  return (
    <Card
      title={t.title}
      className={className}
      action={<InfoPopover label={t.info}>{t.method(num(low), num(high), num(ramp_high, 0))}</InfoPopover>}
    >
      <div className={wide && known ? "md:grid md:grid-cols-[minmax(0,1fr)_minmax(0,380px)] md:items-center md:gap-x-8" : ""}>
        <div>
          <div className="flex items-center gap-2.5">
            <span className="inline-block h-3 w-3 rounded-full" style={{ background: BAND_COLOUR[load.band] }} />
            <span className="font-display text-[23px] font-light">{t.band[load.band]}</span>
          </div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-muted">{explain}</p>
          {known && (
            <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-[12px] tabular-nums">
              <div>
                <dt className="text-ink-muted">{t.ratio}</dt>
                <dd className="text-[15px]">{num(load.acwr ?? 0)}×</dd>
              </div>
              <div>
                <dt className="text-ink-muted">{t.ramp}</dt>
                <dd className="text-[15px]">
                  {(load.ramp ?? 0) > 0 ? "+" : ""}
                  {num(load.ramp ?? 0, 1)}
                </dd>
              </div>
            </dl>
          )}
        </div>
        {known && (
          <div className={`mt-4 max-w-[420px] ${wide ? "md:mt-0" : ""}`}>
            <div className="relative h-2.5" role="img" aria-label={`${t.ratio}: ${num(load.acwr ?? 0)}`}>
              <div className="absolute inset-0 flex overflow-hidden rounded-full">
                {segments.map((s) => (
                  <span
                    key={s.key}
                    className="h-full"
                    style={{
                      width: `${((s.to - s.from) / (MAX - MIN)) * 100}%`,
                      background: BAND_COLOUR[s.key],
                      opacity: load.band === s.key ? 0.9 : 0.3,
                    }}
                  />
                ))}
              </div>
              <span
                aria-hidden="true"
                className="absolute top-1/2 h-4 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full border border-surface bg-ink"
                style={{ left: pos(load.acwr ?? 0) }}
              />
            </div>
            <div className="relative mt-1 h-4 text-[10.5px] tabular-nums text-ink-muted">
              <span className="absolute -translate-x-1/2" style={{ left: pos(low) }}>
                {num(low)}
              </span>
              <span className="absolute -translate-x-1/2" style={{ left: pos(high) }}>
                {num(high)}
              </span>
            </div>
            <div className="flex justify-between text-[10.5px] text-ink-muted">
              <span>{t.scale.low}</span>
              <span>{t.scale.build}</span>
              <span>{t.scale.high}</span>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
