"use client";

import { loginReturn } from "@trackerai/ui/lib/oauthReturn";

// Log in. The first screen anyone sees of this app, so it carries the whole
// identity in miniature: paper ground, the wordmark in the display face, and
// otherwise only what has to be there.
//
// No card around it — the border added nothing the space did not already do.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { APP } from "@/lib/app";
import { Button, Checkbox, Input, Logomark } from "@/components/ds";
import { tr, trx } from "@/lib/i18n";
import LanguageChoice from "@/components/LanguageChoice";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // Two-step login: asked for once the server says this account needs it.
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState("");
  // Codes by email: where the code went (masked), and whether the account can get one instead of the app's.
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [canEmail, setCanEmail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Only offer to create an account when that is really possible: the
  // registration page handles "closed" neatly, but a dead-end link on the very
  // first screen a visitor sees is not a good start. Hidden until the server
  // confirms it is open or by invitation.
  const [canRegister, setCanRegister] = useState(false);
  // "Stay logged in": on by default; off on a shared computer (a browser session). The length comes from the server.
  const [remember, setRemember] = useState(true);
  const [days, setDays] = useState(30);

  useEffect(() => {
    api
      .get<{ mode: "open" | "invite" | "closed"; session_days?: number }>("/api/auth/registration-status")
      .then((s) => {
        setCanRegister(s.mode !== "closed");
        if (s.session_days) setDays(s.session_days);
      })
      .catch(() => setCanRegister(false));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.post("/api/auth/login", { username, password, remember, ...(needsCode ? { totp: code } : {}) });
      router.push(loginReturn(APP.home));
    } catch (err) {
      if (err instanceof ApiError && err.code === "totp_required") {
        setNeedsCode(true);
        setCanEmail(!!err.params?.email);
        setError(null);
        return;
      }
      if (err instanceof ApiError && err.code === "email_code_sent") {
        setNeedsCode(true);
        setSentTo(String(err.params?.to ?? ""));
        setError(null);
        return;
      }
      setError(err instanceof ApiError ? err.message : tr("Logging in failed"));
    } finally {
      setLoading(false);
    }
  }

  async function mailCode() {
    setError(null);
    try {
      await api.post("/api/auth/login", { username, password, remember, send_email: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_code_sent") {
        setSentTo(String(err.params?.to ?? ""));
        return;
      }
      setError(err instanceof ApiError ? err.message : tr("Logging in failed"));
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="flex w-full max-w-[320px] flex-col gap-6">
        {/* The brand above the name, not next to it: this is the only screen where the brand itself
            may be something for a moment instead of a label on a menu. Below it the name, and only
            then where you are. */}
        <div className="flex flex-col gap-1.5">
          <Logomark height={38} className="mb-3" />
          <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">{APP.name}</h1>
          <p className="text-[13px] text-ink-muted">{tr("Log in to see your net worth, spending and portfolio.")}</p>
        </div>

        {/* id/name/type/autoComplete are what a password manager matches on; without those four
            this form was invisible to autofill. */}
        <div className="flex flex-col gap-4">
          <Input
            id="login-username"
            name="username"
            type="text"
            autoComplete="username"
            label={tr("Username")}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
          <Input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            label={tr("Password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={needsCode ? undefined : (error ?? undefined)}
          />
          {needsCode && (
            <Input
              id="login-code"
              name="one-time-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              label={sentTo !== null ? tr("Code from the email") : tr("Code from your authenticator app")}
              hint={sentTo !== null ? tr("We sent it to {0}. It works for 10 minutes.", sentTo) : tr("Or one of your backup codes.")}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              error={error ?? undefined}
              autoFocus
            />
          )}
          <Checkbox
            checked={remember}
            onChange={setRemember}
            className="items-start text-[12.5px] leading-relaxed text-ink-muted"
            label={
              <span>
                {tr("Stay logged in for {0} days", days)}
                <br />
                {tr("On your own device. On a shared computer, untick it: you're logged out when the browser closes.")}
              </span>
            }
          />
          {needsCode && (
            <div className="flex flex-wrap items-center gap-4">
              {(canEmail || sentTo !== null) && (
                <button type="button" className="text-[12.5px] text-ink-muted underline underline-offset-2" onClick={mailCode}>
                  {sentTo !== null ? tr("Send a new code") : tr("Email me a code instead")}
                </button>
              )}
              <a href="/two-step" className="text-[12.5px] text-ink-muted underline underline-offset-2">
                {tr("How does two-step login work?")}
              </a>
            </div>
          )}
        </div>

        <Button type="submit" variant="primary" size="lg" block disabled={loading}>
          {loading ? tr("Working…") : tr("Log in")}
        </Button>

        {canRegister && (
          <p className="text-center text-[13px] text-ink-muted">
            {trx(
              "No account yet? {0}",
              <a href="/register" className="ds-link">
                {tr("Create one")}
              </a>,
            )}
          </p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[12.5px] text-ink-muted">
            <a href="/privacy" className="underline underline-offset-2">
              Privacy
            </a>
            {" · "}
            <a href="/terms" className="underline underline-offset-2">
              {tr("Terms")}
            </a>
          </p>
          <LanguageChoice />
        </div>
      </form>
    </main>
  );
}
