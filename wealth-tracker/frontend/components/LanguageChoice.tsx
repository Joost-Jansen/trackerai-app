"use client";

// The language switch: on Settings (stored with the account) and on the login page (this device only). Each
// language is named in itself, so someone who cannot read the current one still finds theirs.

import { Tabs } from "@/components/ds";
import { locale, tr } from "@/lib/i18n";
import { setLocale } from "@/lib/i18n/provider";

export default function LanguageChoice({ save = false }: { save?: boolean }) {
  return (
    <Tabs
      variant="segmented"
      ariaLabel={tr("Language")}
      items={[{ id: "nl", label: "Nederlands" }, { id: "en", label: "English" }]}
      value={locale}
      onChange={(l) => setLocale(l === "en" ? "en" : "nl", { save })}
    />
  );
}
