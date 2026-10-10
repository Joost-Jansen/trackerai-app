"use client";

// Privacy statement. Public, outside the (app) group: Garmin, Wahoo and anyone deciding whether to sign up must be
// able to read it without an account. No person's name or address in the code: the same code runs for whoever hosts
// an installation, so the controller's name and contact come from the server (PRIVACY_CONTROLLER, PRIVACY_CONTACT via
// /api/auth/config) and the text otherwise speaks of "the administrator". Texts in lib/i18n (privacy).

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import LanguageSwitch from "@/components/LanguageSwitch";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Privacy = { controller: string | null; contact: string | null; version: string };

export default function PrivacyPage() {
  const t = useT();
  const p = t.privacy;
  const config = useQuery({ queryKey: ["auth-config"], queryFn: () => api.get<{ privacy?: Privacy }>("/api/auth/config") });
  const who = config.data?.privacy;
  return (
    <main className="mx-auto flex min-h-screen max-w-[680px] flex-col gap-8 p-6 py-12">
      <div className="flex flex-col gap-1.5">
        <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">{p.title}</h1>
        <p className="text-[13px] text-ink-muted">{p.updated}</p>
      </div>
      <p className="text-[14px] leading-relaxed">{p.intro}</p>
      <section className="flex flex-col gap-2">
        <h2 className="font-display text-[19px] font-normal tracking-[-0.01em]">{p.controllerTitle}</h2>
        <p className="text-[14px] leading-relaxed">{p.controller(who?.controller ?? null, who?.contact ?? null)}</p>
      </section>
      {p.sections.map((s) => (
        <section key={s.title} className="flex flex-col gap-2">
          <h2 className="font-display text-[19px] font-normal tracking-[-0.01em]">{s.title}</h2>
          {s.text && <p className="text-[14px] leading-relaxed">{s.text}</p>}
          {s.items.length > 0 && (
            <ul className="flex list-disc flex-col gap-1.5 pl-5 text-[14px] leading-relaxed">
              {s.items.map((i) => <li key={i}>{i}</li>)}
            </ul>
          )}
        </section>
      ))}
      <div className="flex flex-wrap items-center gap-4 text-[13px] text-ink-muted">
        <Link href="/login/" className="underline underline-offset-4">{p.login}</Link>
        <LanguageSwitch />
      </div>
    </main>
  );
}
