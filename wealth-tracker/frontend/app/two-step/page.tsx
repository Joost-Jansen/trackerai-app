"use client";

// Two-step login, explained. Public, outside the (app) group: the login page links here, also before anyone is
// logged in. The text is the shared one (packages/ui), the same in every tracker.

import { useEffect, useState } from "react";
import TwoStepHelp from "@trackerai/ui/account/TwoStepHelp";
import { api } from "@/lib/api";
import { locale, tr } from "@/lib/i18n";
import LanguageChoice from "@/components/LanguageChoice";

export default function TwoStepPage() {
  const [days, setDays] = useState(30);
  useEffect(() => {
    api
      .get<{ session_days?: number }>("/api/auth/registration-status")
      .then((s) => s.session_days && setDays(s.session_days))
      .catch(() => {});
  }, []);

  return (
    <main className="mx-auto flex max-w-prose flex-col gap-8 p-6 py-12">
      <TwoStepHelp locale={locale} days={days} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <a href="/login" className="text-[12.5px] text-ink-muted underline underline-offset-2">
          {tr("Back to log in")}
        </a>
        <LanguageChoice />
      </div>
    </main>
  );
}
