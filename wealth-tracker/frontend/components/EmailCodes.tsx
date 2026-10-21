"use client";

// Settings → Codes by email: two-step login by a code that logging in mails, instead of (or next to) the
// authenticator app. A setting of the shared trackerai account. Shown only when the server can send mail (SMTP_*),
// or while it is on. Backend: packages/accounts.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Button, Input, Section } from "@/components/ds";
import { tr } from "@/lib/i18n";
import { SettingRow } from "@/app/(app)/account/page";

type Status = { enabled: boolean; email_codes?: boolean; email?: string | null; email_available?: boolean };

export default function EmailCodes({ onEnabled }: { onEnabled?: () => void }) {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["totp"], queryFn: () => api.get<Status>("/api/account/totp") });
  const [mode, setMode] = useState<"on" | "confirm" | "off" | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const s = status.data;
  if (!s || (!s.email_codes && !s.email_available)) return null;
  const app = s.enabled;

  const reset = () => {
    setPassword("");
    setCode("");
    setMsg(null);
  };
  const run = async (f: () => Promise<void>) => {
    setMsg(null);
    setBusy(true);
    try {
      await f();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? e.message : tr("That didn't work. Try again.") });
    } finally {
      setBusy(false);
    }
  };
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["totp"] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
  const cancel = (
    <Button
      type="button"
      variant="ghost"
      onClick={() => {
        reset();
        setMode(null);
      }}
    >
      {tr("Cancel")}
    </Button>
  );

  return (
    <Section label={tr("Codes by email")}>
      <SettingRow
        last={!mode}
        title={s.email_codes ? tr("Codes by email are on") : tr("Codes by email are off")}
        body={
          s.email_codes
            ? tr("Logging in mails a code to {0}.", s.email ?? "")
            : tr(
                "Instead of the app, or next to it: at login we email you a code. Simple, but anyone who can read your mail can then log in with your password, so keep that mailbox safe too.",
              )
        }
        control={
          !mode &&
          (s.email_codes ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                reset();
                setMode("off");
              }}
            >
              {tr("Turn off…")}
            </Button>
          ) : (
            <Button
              size="sm"
              variant={app ? "ghost" : "secondary"}
              onClick={() => {
                reset();
                setMode("on");
              }}
            >
              {tr("Turn on…")}
            </Button>
          ))
        }
      />
      {mode === "on" && (
        <form
          className="flex max-w-sm flex-col gap-4 py-5"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              await api.post("/api/account/email", { email, password, ...(app ? { code } : {}) });
              setPassword("");
              setCode("");
              setMode("confirm");
            });
          }}
        >
          <Input
            id="email-address"
            type="email"
            autoComplete="email"
            label={tr("Email address")}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            id="email-password"
            type="password"
            autoComplete="current-password"
            label={tr("Your password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {app && (
            <Input
              id="email-app-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              label={tr("Code from your authenticator app")}
              hint={tr("Or one of your backup codes.")}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          )}
          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={busy || !email || !password || (app && !code)}>
              {tr("Send a code")}
            </Button>
            {cancel}
          </div>
        </form>
      )}
      {mode === "confirm" && (
        <form
          className="flex max-w-sm flex-col gap-4 py-5"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              await api.post("/api/account/email/confirm", { code });
              reset();
              setMode(null);
              refresh();
              onEnabled?.();
            });
          }}
        >
          <Input
            id="email-confirm-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            label={tr("Code from the email")}
            hint={tr("We sent it to {0}. It works for 10 minutes.", email)}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoFocus
          />
          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={busy || code.trim().length < 6}>
              {tr("Confirm")}
            </Button>
            {cancel}
          </div>
        </form>
      )}
      {mode === "off" && (
        <form
          className="flex max-w-sm flex-col gap-4 py-5"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              await api.post("/api/account/email/disable", { password, code });
              reset();
              setMode(null);
              refresh();
            });
          }}
        >
          <p className="text-[13px] text-ink-muted">
            {tr("To turn it off, enter your password and a code: from the email, your app or a backup code.")}
          </p>
          <Input
            id="email-off-password"
            type="password"
            autoComplete="current-password"
            label={tr("Your password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Input
            id="email-off-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            label={tr("Code")}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="danger" disabled={busy || !password || !code}>
              {tr("Turn off")}
            </Button>
            <MailCodeButton />
            {cancel}
          </div>
        </form>
      )}
      {msg && (
        <p className="text-sm" style={{ color: msg.ok ? undefined : "var(--text-loss)" }}>
          {msg.text}
        </p>
      )}
    </Section>
  );
}

/** For a step that asks for a code (deleting, leaving, turning off): mails one, for accounts with codes by email. */
export function MailCodeButton() {
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="ghost"
        onClick={async () => {
          try {
            const r = await api.post<{ sent_to: string }>("/api/account/email/code");
            setMsg(tr("Sent to {0}.", r.sent_to));
          } catch (e) {
            setMsg(e instanceof ApiError ? e.message : tr("That didn't work. Try again."));
          }
        }}
      >
        {tr("Email me a code")}
      </Button>
      {msg && <span className="text-[12.5px] text-ink-muted">{msg}</span>}
    </span>
  );
}
