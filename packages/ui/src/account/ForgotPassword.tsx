"use client";

// A forgotten password, for every app's login page (packages/accounts: /api/auth/password/forgot and /reset). Two
// steps: a username or email address, which mails a code to that account's confirmed address; then the code and a new
// password. The page always answers the same, whether or not the account exists. Afterwards every device is logged
// out and the login page asks for the new password (and for the two-step code, where the account has it).
//
// The login page shows `ForgotPasswordLink` only when /api/auth/registration-status (or the app's own config) says
// `password_reset: true`, and swaps itself for <ForgotPassword> while it is open.

import { useState, type ReactNode } from "react";
import { Button } from "../ds/Button";
import { Input } from "../ds/Field";
import { useTr } from "../i18n";
import { ApiError } from "../lib/api";

type Api = { post: <T>(path: string, body?: unknown) => Promise<T> };

const LINK = "text-[12.5px] text-ink-muted underline underline-offset-2";

/** "Forgot password?" under the login form. */
export function ForgotPasswordLink({ onClick, className = "" }: { onClick: () => void; className?: string }) {
  const tr = useTr();
  return (
    <button type="button" className={`${LINK} self-start ${className}`} onClick={onClick}>
      {tr("Forgot password?")}
    </button>
  );
}

export default function ForgotPassword({
  api,
  header,
  footer,
  initialLogin = "",
  onBack,
}: {
  /** The app's fetch wrapper (createApi). */
  api: Api;
  /** Above the form: the app's logo, name and tagline, as on its login page. */
  header?: ReactNode;
  /** Under the form: the language switch, a privacy link. */
  footer?: ReactNode;
  /** What was typed as the username on the login page. */
  initialLogin?: string;
  /** Back to the login form; `login` is what was entered here, to fill in the username there. */
  onBack: (login?: string) => void;
}) {
  const tr = useTr();
  const [step, setStep] = useState<"ask" | "reset" | "done">("ask");
  const [login, setLogin] = useState(initialLogin);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // The shared texts, not the server's: every app's server answers in a language of its own.
  function message(err: unknown): string {
    const p = err instanceof ApiError ? (err.params ?? {}) : {};
    switch (err instanceof ApiError ? err.code : undefined) {
      case "reset_code_invalid":
        return tr("That code is not correct or no longer works. Ask for a new one.");
      case "password_too_short":
        return tr("Choose a password of at least {0} characters.", p.min ?? 10);
      case "password_too_long":
        return tr("Choose a password of at most {0} characters.", p.max ?? 200);
      case "password_too_common":
        return tr("This password is one of the most common ones; choose another.");
      case "password_is_username":
        return tr("Your password can't be your username.");
      case "too_many_attempts":
        return tr("Too many attempts. Try again in a quarter of an hour.");
    }
    return err instanceof ApiError && err.message ? err.message : tr("That did not work. Try again.");
  }

  async function sendCode(): Promise<boolean> {
    setError(null);
    setLoading(true);
    try {
      await api.post("/api/auth/password/forgot", { login: login.trim() });
      return true;
    } catch (err) {
      setError(message(err));
      return false;
    } finally {
      setLoading(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (step === "done") return onBack(login.trim());
    if (step === "ask") {
      if (await sendCode()) {
        setNote(null);
        setStep("reset");
      }
      return;
    }
    setError(null);
    setLoading(true);
    try {
      await api.post("/api/auth/password/reset", { login: login.trim(), code: code.trim(), new_password: password });
      setPassword("");
      setStep("done");
    } catch (err) {
      setError(message(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={submit} className="flex w-full max-w-[320px] flex-col gap-6">
        {header}
        {step === "ask" && (
          <div className="flex flex-col gap-4">
            <p className="text-[13px] leading-relaxed text-ink-muted">
              {tr("Forgot your password? Enter your username or email address: we email a code to that account's confirmed address.")}
            </p>
            <Input
              id="forgot-login"
              name="username"
              type="text"
              autoComplete="username"
              label={tr("Username or email address")}
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              error={error ?? undefined}
              autoFocus
            />
          </div>
        )}
        {step === "reset" && (
          <div className="flex flex-col gap-4">
            <p className="text-[13px] leading-relaxed text-ink-muted" role="status">
              {note ?? tr("If an account with that name or address has a confirmed email, a code is on its way. It works for 10 minutes.")}
            </p>
            {/* the login once more, for a password manager to save the new password with */}
            <input type="text" name="username" autoComplete="username" value={login} readOnly hidden />
            <Input
              id="forgot-code"
              name="one-time-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              label={tr("Code from the email")}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
            />
            <Input
              id="forgot-password"
              name="new-password"
              type="password"
              autoComplete="new-password"
              label={tr("New password")}
              hint={tr("At least 10 characters.")}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={error ?? undefined}
            />
            <button
              type="button"
              className={`${LINK} self-start`}
              onClick={async () => {
                if (await sendCode())
                  setNote(tr("A new code is on its way, if the account has a confirmed email. Only the newest one works."));
              }}
            >
              {tr("Send a new code")}
            </button>
          </div>
        )}
        {step === "done" && (
          <p className="text-[13px] leading-relaxed" role="status">
            {tr("Your password is changed, and every device is logged out. Log in with your new password.")}
          </p>
        )}
        <Button
          type="submit"
          variant="primary"
          size="lg"
          block
          disabled={loading || (step === "ask" && !login.trim()) || (step === "reset" && (!code.trim() || !password))}
        >
          {loading
            ? tr("One moment…")
            : step === "ask"
              ? tr("Send code")
              : step === "reset"
                ? tr("Set new password")
                : tr("Back to log in")}
        </Button>
        {step !== "done" && (
          <button type="button" className={`${LINK} self-start`} onClick={() => onBack(login.trim())}>
            {tr("Back to log in")}
          </button>
        )}
        {footer}
      </form>
    </main>
  );
}
