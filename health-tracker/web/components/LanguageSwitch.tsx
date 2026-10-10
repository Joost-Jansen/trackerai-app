"use client";

// Nederlands / English. On the login and registration pages only for this device; under Settings also stored
// with your account (`save`), so another device gets the same language.

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Tabs } from "@/components/ds";
import { LOCALES, errorText, useLocale, useT, type Locale } from "@/lib/i18n";

export default function LanguageSwitch({ save = false, className = "" }: { save?: boolean; className?: string }) {
  const t = useT();
  const qc = useQueryClient();
  const { locale, setLocale } = useLocale();
  const [error, setError] = useState<string | null>(null);
  return (
    <span className={`inline-flex flex-wrap items-center gap-2 ${className}`}>
      <Tabs
        variant="segmented"
        ariaLabel={t.language.label}
        items={LOCALES.map((l) => ({ id: l, label: t.language.names[l] }))}
        value={locale}
        onChange={async (id) => {
          setError(null);
          try {
            await setLocale(id as Locale, { save });
            if (save) qc.invalidateQueries({ queryKey: ["me"] });
          } catch (e) {
            setError(errorText(e, t, t.common.saveFailed));
          }
        }}
      />
      {error && <span className="text-[12.5px] text-loss">{error}</span>}
    </span>
  );
}
