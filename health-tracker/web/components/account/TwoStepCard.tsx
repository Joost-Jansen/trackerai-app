"use client";

// Two-step login: one setting of the shared trackerai account, so it holds for every tracker. Used on the account
// page and on the screen that asks for it before anything else when the account requires it.

import { useMemo, useRef, useState } from "react";
import qrcode from "qrcode-generator";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button, Input } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/i18n";
import type { Me } from "@/lib/training";

/** The otpauth URI as a QR code image (a data: URL: no request leaves the browser with the secret). */
function Qr({ text }: { text: string }) {
  const src = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    return qr.createDataURL(4, 4);
  }, [text]);
  return <img src={src} alt="" width={180} height={180} className="rounded bg-white p-1 [image-rendering:pixelated]" />;
}

export default function TwoStepCard({ me, onEnabled }: { me: Me; onEnabled?: () => void }) {
  const t = useT();
  const m = t.account.twoStep;
  const qc = useQueryClient();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [backup, setBackup] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [mode, setMode] = useState<"off" | "codes" | null>(null);
  // One request at a time: a double tap or Enter plus a tap sent the code twice, and the second one failed (turning
  // two-step login on ends the old session) and showed an error after the success.
  const running = useRef(false);
  const [busy, setBusy] = useState(false);
  const once = (f: () => Promise<void>) => async (e: React.FormEvent) => {
    e.preventDefault();
    if (running.current) return;
    running.current = true;
    setBusy(true);
    try {
      await f();
    } finally {
      running.current = false;
      setBusy(false);
    }
  };
  const status = useQuery({ queryKey: ["totp"], queryFn: () => api.get<{ backup_codes_left: number }>("/api/account/totp"), enabled: !!me.totp_enabled });
  const codesLeft = me.totp_enabled ? status.data?.backup_codes_left ?? null : null;
  const fail = (err: unknown) => setMsg({ ok: false, text: errorText(err, t, m.failed) });
  const reset = () => { setCode(""); setPassword(""); setMsg(null); };

  if (backup) {
    return (
      <Card title={m.backupTitle}>
        <p className="mb-3 max-w-prose text-[12.5px] text-ink-muted">{m.backupText}</p>
        <ul className="mb-4 grid max-w-xs grid-cols-2 gap-x-6 gap-y-1 font-mono text-[13px]">
          {backup.map((c) => <li key={c}>{c}</li>)}
        </ul>
        <Button size="sm" variant="primary" onClick={() => { setBackup(null); qc.invalidateQueries({ queryKey: ["me"] }); qc.invalidateQueries({ queryKey: ["totp"] }); onEnabled?.(); }}>{m.done}</Button>
      </Card>
    );
  }

  return (
    <Card title={m.title}>
      <p className="mb-3 max-w-prose text-[12px] text-ink-muted">
        {m.everywhere}{" "}<Link href="/two-step/" className="underline underline-offset-2">{t.auth.twoStepHelp}</Link>
      </p>
      {me.totp_enabled ? (
        <div className="flex max-w-sm flex-col gap-3">
          <p className="text-[12.5px] text-gain">{m.on}</p>
          {me.totp_required && <p className="text-[12.5px] text-ink-muted">{m.required}</p>}
          {codesLeft !== null && <p className="text-[12.5px] text-ink-muted">{m.codesLeft(codesLeft)}</p>}
          {mode === null && (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => { reset(); setMode("off"); }}>{me.totp_required ? m.setUpAgain : m.turnOff}</Button>
              <Button size="sm" variant="ghost" onClick={() => { reset(); setMode("codes"); }}>{m.newCodes}</Button>
            </div>
          )}
          {mode === "off" && (
            <form
              className="flex flex-col gap-3"
              onSubmit={once(async () => {
                try {
                  await api.post("/api/account/totp/disable", { password, code });
                  reset();
                  setMode(null);
                  setMsg({ ok: true, text: m.turnedOff });
                  qc.invalidateQueries({ queryKey: ["me"] });
                } catch (err) {
                  fail(err);
                }
              })}
            >
              <p className="text-[12.5px] text-ink-muted">{me.totp_required ? m.setUpAgainText : m.turnOffText}</p>
              <Input type="password" autoComplete="current-password" label={m.password} value={password} onChange={(e) => setPassword(e.target.value)} />
              <Input inputMode="numeric" autoComplete="one-time-code" label={m.codeOrBackup} value={code} onChange={(e) => setCode(e.target.value)} />
              <div className="flex items-center gap-3">
                <Button type="submit" size="sm" variant="secondary" disabled={busy || !password || !code}>{m.turnOff}</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => { reset(); setMode(null); }}>{m.cancel}</Button>
              </div>
            </form>
          )}
          {mode === "codes" && (
            <form
              className="flex flex-col gap-3"
              onSubmit={once(async () => {
                try {
                  const r = await api.post<{ backup_codes: string[] }>("/api/account/totp/backup-codes", { code });
                  reset();
                  setMode(null);
                  setBackup(r.backup_codes);
                } catch (err) {
                  fail(err);
                }
              })}
            >
              <p className="text-[12.5px] text-ink-muted">{m.newCodesText}</p>
              <Input inputMode="numeric" autoComplete="one-time-code" label={m.code} value={code} onChange={(e) => setCode(e.target.value)} />
              <div className="flex items-center gap-3">
                <Button type="submit" size="sm" variant="primary" disabled={busy || code.trim().length < 6}>{m.makeCodes}</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => { reset(); setMode(null); }}>{m.cancel}</Button>
              </div>
            </form>
          )}
          {msg && <span className={`text-[12.5px] ${msg.ok ? "text-gain" : "text-loss"}`}>{msg.text}</span>}
        </div>
      ) : setup ? (
        <form
          className="flex max-w-sm flex-col gap-3"
          onSubmit={once(async () => {
            try {
              const r = await api.post<{ backup_codes: string[] }>("/api/account/totp/enable", { code });
              reset();
              setSetup(null);
              setBackup(r.backup_codes);
            } catch (err) {
              fail(err);
            }
          })}
        >
          <p className="text-[12.5px] text-ink-muted">{m.scan}</p>
          <Qr text={setup.otpauth_uri} />
          <p className="text-[12px] text-ink-muted">{m.key}: <span className="select-all break-all font-mono text-[var(--text-primary)]">{setup.secret}</span></p>
          <Input inputMode="numeric" autoComplete="one-time-code" label={m.code} hint={m.codeHint} value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
          <div className="flex items-center gap-3">
            <Button type="submit" size="sm" variant="primary" disabled={busy || code.trim().length < 6}>{m.confirm}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => { setSetup(null); reset(); }}>{m.cancel}</Button>
            {msg && <span className={`text-[12.5px] ${msg.ok ? "text-gain" : "text-loss"}`}>{msg.text}</span>}
          </div>
        </form>
      ) : (
        <div className="flex max-w-prose flex-col gap-3">
          <p className="text-[12.5px] text-ink-muted">{me.email_codes ? m.appOff : m.off}</p>
          {me.email_codes ? null : me.totp_required ? <p className="text-[12.5px]">{m.required}</p> : me.is_admin && <p className="text-[12.5px]">{m.adminHint}</p>}
          <div className="flex items-center gap-3">
            <Button size="sm" variant="primary" onClick={async () => {
              reset();
              try {
                setSetup(await api.post<{ secret: string; otpauth_uri: string }>("/api/account/totp/setup"));
              } catch (err) {
                fail(err);
              }
            }}>{m.turnOn}</Button>
            {msg && <span className={`text-[12.5px] ${msg.ok ? "text-gain" : "text-loss"}`}>{msg.text}</span>}
          </div>
        </div>
      )}
    </Card>
  );
}
