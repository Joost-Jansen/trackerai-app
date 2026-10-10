// "3 variants: 38, 42 and 47 km": the length variants of one route. Nothing with one variant.

import { useFormat, useT } from "@/lib/i18n";
import type { RouteLengthVariant } from "@/lib/training";

export default function LengthVariants({ variants, className = "" }: { variants?: RouteLengthVariant[]; className?: string }) {
  const t = useT();
  const f = useFormat();
  if (!variants || variants.length < 2) return null;
  const km = (v: number) => (v >= 20 ? f.num(v) : f.num(v, 1));
  return (
    <span className={`tabular-nums ${className}`} title={`${t.texts.routes.variantsHelp} ${variants.map((v) => `${km(v.distance_km)} km: ${v.runs}×`).join(", ")}`}>
      {t.texts.routes.variants(variants.map((v) => km(v.distance_km)))}
    </span>
  );
}
