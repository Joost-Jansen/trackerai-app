// Ready for today? The verdict from last night and the form. The API gives codes and numbers
// (api/readiness.py); the sentences come from T.today.readiness.

import Card from "@trackerai/ui/components/Card";
import { useT } from "@/lib/i18n";
import type { Readiness } from "@/lib/training";

const VERDICT_COLOUR: Record<Readiness["verdict"], string> = {
  ready: "var(--zone-2)",
  easy: "var(--zone-3)",
  recover: "var(--zone-5)",
  unknown: "var(--zone-1)",
};
const LEVEL_COLOUR = { ok: "var(--zone-2)", attention: "var(--zone-3)", warn: "var(--zone-5)" };

export default function ReadinessCard({ r, className = "" }: { r: Readiness; className?: string }) {
  const { dashboard: m, texts: T } = useT();
  const t = T.today.readiness;
  const advice = r.verdict === "unknown" ? t.unknown(r.signals.map((s) => t.label[s.key])) : t.advice[r.verdict];
  const text = r.no_night ? `${advice} ${t.noNight}` : advice;
  // without night data there is little to say: compact, so the card does not look bigger than what it knows
  const compact = !r.date;
  return (
    <Card title={t.title} className={className} more={r.date ? m.dayDetail : undefined} moreHref={r.date ? `/dashboard/body/?day=${r.date}` : undefined}>
      <div className="flex items-center gap-2.5">
        <span className={`inline-block rounded-full ${compact ? "h-2 w-2" : "h-3 w-3"}`} style={{ background: VERDICT_COLOUR[r.verdict] }} />
        <span className={compact ? "text-[15px] font-medium" : "font-display text-[23px] font-light"}>{t.verdict[r.verdict]}</span>
      </div>
      <p className={`mt-1 leading-relaxed text-ink-muted ${compact ? "text-[12px]" : "text-[12.5px]"}`}>{text}</p>
      {r.illness_hint && (
        <p className="mt-2 flex items-start gap-2 text-[12.5px] leading-relaxed">
          <span aria-hidden="true" className="mt-[6px] inline-block h-2 w-2 flex-none rounded-full" style={{ background: LEVEL_COLOUR.attention }} />
          {t.illness}
        </p>
      )}
      {compact ? (
        <dl className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[12px] tabular-nums">
          {r.signals.map((s) => (
            <div key={s.key} className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: LEVEL_COLOUR[s.level] }} />
              <dt className="text-ink-muted">{t.label[s.key]}</dt>
              <dd>{t.value(s.key, s.value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[12px] tabular-nums">
          {r.signals.map((s) => {
            const note = t.note(s.note.code, s.note.params);
            return (
              <div key={s.key}>
                <dt className="flex items-center gap-1.5 text-ink-muted"><span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: LEVEL_COLOUR[s.level] }} />{t.label[s.key]}</dt>
                <dd><span className="text-[15px]">{t.value(s.key, s.value)}</span> {note && <span className="text-[11px] text-ink-muted">{note}</span>}</dd>
              </div>
            );
          })}
        </dl>
      )}
      <p className={`text-[11px] text-ink-muted ${compact ? "mt-2.5" : "mt-3"}`}>{T.readinessBasis} {T.noMedicalAdvice}</p>
    </Card>
  );
}
