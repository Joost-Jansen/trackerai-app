"use client";

// Create an account. Only possible when the admin has opened registration or you have an invite link;
// on an empty install the first user becomes admin.

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button, Checkbox, Input, Logomark } from "@/components/ds";
import type { RegistrationMode } from "@/lib/training";
import LanguageSwitch from "@/components/LanguageSwitch";
import { errorText, useLocale, useT } from "@/lib/i18n";
import { rich } from "@/lib/i18n/rich";

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const t = useT();
  const { locale } = useLocale();
  const config = useQuery({
    queryKey: ["auth-config"],
    queryFn: () => api.get<{ registration: RegistrationMode; first_user: boolean }>("/api/auth/config"),
  });
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState(params.get("invite") ?? "");
  const [consent, setConsent] = useState(false); // explicit and unticked by default: health data needs it (GDPR art. 9)
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!config.data) return null;
  const mode = config.data.registration;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.post("/api/register", {
        username,
        password,
        email,
        display_name: displayName || undefined,
        invite: invite || undefined,
        locale,
        consent,
      });
      router.push("/settings/connections/");
    } catch (err) {
      setError(errorText(err, t, t.auth.registerFailed));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex w-full max-w-[340px] flex-col gap-6">
      <div className="flex flex-col gap-1.5">
        <Logomark height={34} className="mb-3" />
        <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">{t.auth.createAccount}</h1>
        <p className="text-[13px] text-ink-muted">
          {config.data.first_user ? t.auth.firstUser : mode === "closed" ? t.auth.closed : t.auth.afterwards}
        </p>
      </div>
      {mode !== "closed" && (
        <>
          <div className="flex flex-col gap-4">
            <Input
              label={t.auth.username}
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              hint={t.auth.usernameHint}
              autoFocus
            />
            <Input label={t.auth.displayName} autoComplete="name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            <Input
              label={t.auth.email}
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              hint={t.auth.emailHint}
            />
            <Input
              label={t.auth.password}
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              hint={t.auth.passwordHint}
            />
            {mode === "invite" && !config.data.first_user && (
              <Input label={t.auth.invite} value={invite} onChange={(e) => setInvite(e.target.value)} />
            )}
            <Checkbox
              checked={consent}
              onChange={setConsent}
              className="items-start text-[12.5px] leading-relaxed text-ink-muted"
              label={rich(t.auth.consent, {
                link: (c) => (
                  <Link href="/privacy/" target="_blank" className="underline underline-offset-2">
                    {c}
                  </Link>
                ),
              })}
            />
            {error && <p className="text-[12.5px] text-loss">{error}</p>}
          </div>
          <Button type="submit" variant="primary" size="lg" block disabled={loading || !username || !email || !password || !consent}>
            {loading ? t.common.busy : t.auth.createAccount}
          </Button>
        </>
      )}
      <p className="text-[12.5px] text-ink-muted">
        {t.auth.haveAccount}{" "}
        <Link href="/login/" className="underline underline-offset-2">
          {t.auth.login}
        </Link>
      </p>
      <div className="flex flex-wrap items-center gap-4">
        <LanguageSwitch />
        <Link href="/privacy/" className="text-[12.5px] text-ink-muted underline underline-offset-2">
          {t.auth.privacy}
        </Link>
      </div>
    </form>
  );
}

export default function RegisterPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <Suspense fallback={null}>
        <RegisterForm />
      </Suspense>
    </main>
  );
}
