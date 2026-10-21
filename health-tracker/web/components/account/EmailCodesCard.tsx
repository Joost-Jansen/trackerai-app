"use client";

// Two-step login by email: instead of (or next to) the authenticator app, logging in mails a code. One setting of the
// shared trackerai account. Shown only when the server can send mail (SMTP_*), or while it is on.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button, Input } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/i18n";
import type { Me } from "@/lib/training";

type Status = { enabled: boolean; email_codes?: boolean; email?: string | null; email_available?: boolean };

export default function EmailCodesCard({ me, onEnabled }: { me: Me; onEnabled?: () => void }) {
  const t = useT();
  const m = t.account.emailCodes;
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
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, t, m.failed) });
    } finally {
      setBusy(false);
    }
  };
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["me"] });
    qc.invalidateQueries({ queryKey: ["totp"] });
  };
  const mailCode = () =>
    run(async () => {
      const r = await api.post<{ sent_to: string }>("/api/account/email/code");
      setMsg({ ok: true, text: m.sent(r.sent_to) });
    });
  const cancel = (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      onClick={() => {
        reset();
        setMode(null);
      }}
    >
      {t.account.twoStep.cancel}
    </Button>
  );

  return (
    <Card title={m.title}>
      {s.email_codes ? (
        <div className="flex max-w-sm flex-col gap-3">
          <p className="text-[12.5px] text-gain">{m.on(s.email ?? "")}</p>
          {mode === null && (
            <div>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  reset();
                  setMode("off");
                }}
              >
                {m.turnOff}…
              </Button>
            </div>
          )}
          {mode === "off" && (
            <form
              className="flex flex-col gap-3"
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
              <p className="text-[12.5px] text-ink-muted">{m.turnOffText}</p>
              <Input
                type="password"
                autoComplete="current-password"
                label={t.account.twoStep.password}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <Input
                inputMode="numeric"
                autoComplete="one-time-code"
                label={m.code}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" size="sm" variant="secondary" disabled={busy || !password || !code}>
                  {m.turnOff}
                </Button>
                <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={mailCode}>
                  {m.mailCode}
                </Button>
                {cancel}
              </div>
            </form>
          )}
        </div>
      ) : (
        <div className="flex max-w-sm flex-col gap-3">
          <p className="max-w-prose text-[12.5px] text-ink-muted">{m.off}</p>
          {mode === null && (
            <div>
              <Button
                size="sm"
                variant={me.totp_enabled ? "secondary" : "primary"}
                onClick={() => {
                  reset();
                  setMode("on");
                }}
              >
                {m.turnOn}…
              </Button>
            </div>
          )}
          {mode === "on" && (
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                run(async () => {
                  await api.post("/api/account/email", { email, password, ...(me.totp_enabled ? { code } : {}) });
                  setCode("");
                  setPassword("");
                  setMode("confirm");
                });
              }}
            >
              <Input type="email" autoComplete="email" label={m.email} value={email} onChange={(e) => setEmail(e.target.value)} />
              <Input
                type="password"
                autoComplete="current-password"
                label={t.account.twoStep.password}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {me.totp_enabled && (
                <Input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  label={t.account.twoStep.codeOrBackup}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              )}
              <div className="flex items-center gap-3">
                <Button type="submit" size="sm" variant="primary" disabled={busy || !email || !password || (!!me.totp_enabled && !code)}>
                  {m.send}
                </Button>
                {cancel}
              </div>
            </form>
          )}
          {mode === "confirm" && (
            <form
              className="flex flex-col gap-3"
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
                inputMode="numeric"
                autoComplete="one-time-code"
                label={m.code}
                hint={m.confirmHint(email)}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoFocus
              />
              <div className="flex items-center gap-3">
                <Button type="submit" size="sm" variant="primary" disabled={busy || code.trim().length < 6}>
                  {m.confirm}
                </Button>
                {cancel}
              </div>
            </form>
          )}
        </div>
      )}
      {msg && <p className={`mt-3 text-[12.5px] ${msg.ok ? "text-ink-muted" : "text-loss"}`}>{msg.text}</p>}
    </Card>
  );
}

/** For a step that asks for a code (deleting, leaving): mails one, for accounts with codes by email. */
export function MailCodeButton() {
  const t = useT();
  const m = t.account.emailCodes;
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={async () => {
          try {
            const r = await api.post<{ sent_to: string }>("/api/account/email/code");
            setMsg(m.sent(r.sent_to));
          } catch (err) {
            setMsg(errorText(err, t, m.failed));
          }
        }}
      >
        {m.mailCode}
      </Button>
      {msg && <span className="text-[12.5px] text-ink-muted">{msg}</span>}
    </div>
  );
}
