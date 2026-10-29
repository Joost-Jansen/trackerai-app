"use client";

// Log in with the shared trackerai account (packages/accounts): the password, then two-step login when the account
// has it (the authenticator app's code, or a code by email), and "stay logged in". Paper ground, the app's name in the
// display face, and otherwise only what needs to be there. An app shows it at /login/ and says where to go after.

import { useEffect, useState, type ReactNode } from "react";
import { Button } from "../ds/Button";
import { Checkbox, Input } from "../ds/Field";
import { useTr } from "../i18n";
import { ApiError } from "../lib/api";

type Api = {
  get: <T>(path: string) => Promise<T>;
  post: <T>(path: string, body?: unknown) => Promise<T>;
};

export default function LoginPage({
  api,
  name,
  tagline,
  onDone,
  logo,
  footer,
  twoStepHref,
}: {
  /** The app's fetch wrapper (createApi): its language goes along with the request. */
  api: Api;
  name: string;
  tagline: string;
  /** Logged in: where to now (the page the visitor came for). */
  onDone: () => void;
  logo?: ReactNode;
  /** Under the form: the language switch, a privacy link. */
  footer?: ReactNode;
  /** A page explaining two-step login, if the app has one. */
  twoStepHref?: string;
}) {
  const tr = useTr();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState<string | null>(null); // null: the password step; a string: the code step
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [remember, setRemember] = useState(true); // "stay logged in" (and: don't ask this device for the code again)
  const [days, setDays] = useState(30);
  // codes by email: where the code went (masked), and whether the account can get one instead of the app's
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [canEmail, setCanEmail] = useState(false);

  useEffect(() => {
    api
      .get<{ session_days?: number }>("/api/auth/registration-status")
      .then((s) => s.session_days && setDays(s.session_days))
      .catch(() => {});
  }, [api]);

  /** The password was right and a code is wanted: the step after it. */
  function codeStep(err: unknown): boolean {
    if (!(err instanceof ApiError)) return false;
    if (err.code === "totp_required") {
      setCode("");
      setCanEmail(!!err.params?.email);
      return true;
    }
    if (err.code === "email_code_sent") {
      setCode("");
      setSentTo(String(err.params?.to ?? ""));
      return true;
    }
    return false;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.post("/api/auth/login", { username, password, remember, ...(code !== null ? { totp: code } : {}) });
      onDone();
    } catch (err) {
      if (!codeStep(err)) setError(err instanceof ApiError && err.message ? err.message : tr("Logging in failed"));
    } finally {
      setLoading(false);
    }
  }

  async function mailCode() {
    setError(null);
    try {
      await api.post("/api/auth/login", { username, password, remember, send_email: true });
    } catch (err) {
      if (!codeStep(err)) setError(err instanceof ApiError && err.message ? err.message : tr("Logging in failed"));
    }
  }

  const link = "text-[12.5px] text-ink-muted underline underline-offset-2";
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={submit} className="flex w-full max-w-[320px] flex-col gap-6">
        <div className="flex flex-col gap-1.5">
          {logo && <div className="mb-3">{logo}</div>}
          <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">{name}</h1>
          <p className="text-[13px] text-ink-muted">{tagline}</p>
        </div>
        {code === null ? (
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
              error={error ?? undefined}
            />
            <Checkbox
              checked={remember}
              onChange={setRemember}
              className="items-start text-[12.5px] leading-relaxed text-ink-muted"
              label={
                <span>
                  <span className="text-ink">{tr("Stay logged in for {0} days", days)}</span>
                  <br />
                  {tr("On your own device. On a shared computer, untick it: you're logged out when the browser closes.")}
                </span>
              }
            />
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <Input
              id="login-code"
              name="totp"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              label={sentTo !== null ? tr("Code from the email") : tr("Code from your authenticator app")}
              hint={sentTo !== null ? tr("We sent it to {0}. It works for 10 minutes.", sentTo) : tr("Or one of your backup codes.")}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              error={error ?? undefined}
              autoFocus
            />
            <div className="flex flex-wrap items-center gap-4">
              <button
                type="button"
                className={link}
                onClick={() => {
                  setCode(null);
                  setError(null);
                  setSentTo(null);
                  setCanEmail(false);
                }}
              >
                {tr("Back")}
              </button>
              {(canEmail || sentTo !== null) && (
                <button type="button" className={link} onClick={mailCode}>
                  {sentTo !== null ? tr("Send a new code") : tr("Email me a code instead")}
                </button>
              )}
              {twoStepHref && (
                <a href={twoStepHref} className={link}>
                  {tr("How does two-step login work?")}
                </a>
              )}
            </div>
          </div>
        )}
        <Button type="submit" variant="primary" size="lg" block disabled={loading || code === ""}>
          {loading ? tr("One moment…") : tr("Log in")}
        </Button>
        {footer}
      </form>
    </main>
  );
}
