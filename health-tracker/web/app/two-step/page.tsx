"use client";

// Two-step login, explained. Public, outside the (app) group: the login page links here, before anyone is logged in.
// The text is shared with wealth-tracker (@trackerai/ui account/TwoStepHelp): one setting of one account.

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import TwoStepHelp from "@trackerai/ui/account/TwoStepHelp";
import LanguageSwitch from "@/components/LanguageSwitch";
import { api } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";

export default function TwoStepPage() {
  const t = useT();
  const { locale } = useLocale();
  const config = useQuery({ queryKey: ["auth-config"], queryFn: () => api.get<{ session_days?: number }>("/api/auth/config") });
  return (
    <main className="mx-auto flex min-h-screen max-w-[680px] flex-col gap-8 p-6 py-12">
      <TwoStepHelp locale={locale} days={config.data?.session_days ?? 30} />
      <div className="flex flex-wrap items-center gap-4">
        <Link href="/login/" className="text-[12.5px] text-ink-muted underline underline-offset-2">{t.auth.login}</Link>
        <LanguageSwitch />
      </div>
    </main>
  );
}
