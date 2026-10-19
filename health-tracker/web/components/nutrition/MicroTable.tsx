// Vitamins and minerals of the day: the amount eaten against the Dutch norm (ADH, or AI where too little is known
// for an ADH) for the men's or women's norms chosen in the Nutrition settings. Iron, vitamin D, calcium and magnesium
// first: they matter most for endurance athletes. Closed by default; no colours for "too little", only the numbers.

import Link from "next/link";
import CollapsibleCard from "@trackerai/ui/components/CollapsibleCard";
import { InfoIcon } from "@trackerai/ui/icons";
import { useFormat, useLocale, useT } from "@/lib/i18n";
import type { NutritionDay } from "@/lib/nutrition";

const UNIT: Record<string, string> = { mg: "mg", ug: "µg", g: "g" };

export default function MicroTable({ micros }: { micros: NutritionDay["micros"] }) {
  const tt = useT();
  const t = tt.nutrition.micros;
  const f = useFormat();
  const { locale } = useLocale();
  const unit = (key: string) => UNIT[key.split("_").pop() ?? ""] ?? "";
  return (
    <CollapsibleCard title={t.title} icon={<InfoIcon width={15} height={15} />} summary={micros.group ? t.forGroup[micros.group] : t.chooseShort}>
      <table className="w-full text-[12.5px] tabular-nums">
        <thead>
          <tr className="text-left text-ink-muted">
            <th className="py-1 pr-3 font-normal">{t.nutrient}</th>
            <th className="py-1 pr-3 text-right font-normal">{t.eaten}</th>
            <th className="py-1 pr-3 text-right font-normal">{t.norm}</th>
            <th className="py-1 text-right font-normal">%</th>
          </tr>
        </thead>
        <tbody>
          {micros.rows.map((r) => (
            <tr key={r.key} className="border-t border-border">
              <td className="py-1 pr-3">{tt.nutrition.nutrients[r.key]}{r.kind === "AI" && <span className="ml-1 text-[11px] text-ink-muted">(AI)</span>}</td>
              <td className="py-1 pr-3 text-right">{r.amount == null ? "–" : `${f.trim(r.amount, 1)} ${unit(r.key)}`}{r.missing > 0 && <span className="text-ink-muted"> *</span>}</td>
              <td className="py-1 pr-3 text-right text-ink-muted">{r.reference == null ? "–" : `${f.trim(r.reference, 1)} ${unit(r.key)}`}</td>
              <td className="py-1 text-right">{r.pct == null ? "–" : `${r.pct}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex flex-col gap-1 text-[11.5px] text-ink-muted">
        {!micros.group && <p>{t.choose} <Link href="/settings/zones/#nutrition" className="underline underline-offset-4">{t.toSettings}</Link></p>}
        {micros.rows.some((r) => r.missing > 0) && <p>{t.missing}</p>}
        <p>{t.aiNote}</p>
        <p><a href={micros.source.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">{locale === "en" ? micros.source.en : micros.source.nl}</a></p>
      </div>
    </CollapsibleCard>
  );
}
