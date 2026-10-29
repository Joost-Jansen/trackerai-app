"use client";

// Log in with the trackerai account (the shared login page, packages/ui), then back to the page you came for.

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import LoginPage from "@trackerai/ui/account/LoginPage";
import Logomark from "@/components/Logomark";
import { api } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";

function Login() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const t = useT();
  const { locale, setLocale } = useLocale();
  // only a page of this site: never a link elsewhere
  const target = next && next.startsWith("/") && !next.startsWith("//") ? next : "/library/";
  return (
    <LoginPage
      api={api}
      name="tabstealth"
      tagline={t.auth.tagline}
      logo={<Logomark height={30} />}
      onDone={() => router.replace(target)}
      footer={
        <button
          type="button"
          className="self-start text-[12.5px] text-ink-muted underline underline-offset-2"
          onClick={() => setLocale(locale === "nl" ? "en" : "nl")}
        >
          {t.common.language}
        </button>
      }
    />
  );
}

export default function LoginRoute() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
