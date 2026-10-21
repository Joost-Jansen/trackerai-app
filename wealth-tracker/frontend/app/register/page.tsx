"use client";

// Creating an account yourself. Registration has three modes (open / by
// invitation / closed); the page asks the server which one applies, so the code
// field only appears when a code is really needed, and the page refuses neatly
// when sign-up is off.
//
// The invite link from the admin screen points here with ?invite=…, so in that
// mode the code is prefilled and the recipient only chooses a username and a
// password — but it stays editable, because the link arrives just as often as a
// pasted code in a message.

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { APP } from "@/lib/app";
import { Button, Input } from "@/components/ds";
import { locale, tr, trx } from "@/lib/i18n";

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"open" | "invite" | "closed" | null>(null);
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState(params.get("invite") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api
      .get<{ mode: "open" | "invite" | "closed" }>("/api/auth/registration-status")
      .then((s) => setMode(s.mode))
      .catch(() => setMode("closed"));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // Registering logs you in straight away — the server sets the session cookie.
      await api.post("/api/auth/register", { username, name, email, locale, password, invite_code: inviteCode, app: "money" });
      router.push(APP.home);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tr("The account could not be created"));
    } finally {
      setLoading(false);
    }
  }

  if (mode === null) return <main className="min-h-screen" />;

  if (mode === "closed") {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <div className="flex w-full max-w-[320px] flex-col gap-3">
          <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">{tr("Registration closed")}</h1>
          <p className="text-sm leading-relaxed text-ink-muted">{tr("New sign-ups are switched off right now.")}</p>
          <p className="text-[13px]">
            <a href="/login" className="ds-link">
              {tr("Back to log in")}
            </a>
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="flex w-full max-w-[320px] flex-col gap-6">
        <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">{tr("Create account")}</h1>

        <div className="flex flex-col gap-4">
          <Input
            id="reg-name"
            name="name"
            type="text"
            autoComplete="name"
            label={tr("Your name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <Input
            id="reg-username"
            name="username"
            type="text"
            autoComplete="username"
            label={tr("Username")}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <Input
            id="reg-email"
            name="email"
            type="email"
            autoComplete="email"
            label={tr("Email address")}
            hint={tr("We send a code to confirm it; it also becomes your two-step login.")}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <Input
            id="reg-password"
            name="password"
            type="password"
            autoComplete="new-password"
            label={tr("Password")}
            hint={tr("At least 10 characters, not a common password and not your username.")}
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {mode === "invite" && (
            <Input
              id="reg-invite"
              name="invite"
              type="text"
              label="Uitnodigingscode"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
            />
          )}
          {error && (
            <p className="text-[13px]" style={{ color: "var(--text-loss)" }}>
              {error}
            </p>
          )}
        </div>

        <Button type="submit" variant="primary" size="lg" block disabled={loading}>
          {loading ? tr("Working…") : tr("Create account")}
        </Button>

        <p className="text-center text-[13px] text-ink-muted">
          {trx(
            "Already have an account? {0}",
            <a href="/login" className="ds-link">
              {tr("Log in")}
            </a>,
          )}
        </p>
      </form>
    </main>
  );
}

export default function RegisterPage() {
  // useSearchParams needs a Suspense boundary, otherwise the whole route drops out
  // of static rendering at build time.
  return (
    <Suspense fallback={<main className="min-h-screen" />}>
      <RegisterForm />
    </Suspense>
  );
}
