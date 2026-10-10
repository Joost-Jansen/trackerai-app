"use client";

// Settings → Two-step login (TOTP), a setting of the shared trackerai account: it holds for every tracker. Required
// for admins and for anyone using more than one tracker (`required`): then it can't be turned off.
// Turning on: the server makes a secret (shown as a QR code and as text), the user
// confirms with a code from their authenticator app and gets ten backup codes,
// once. Turning off asks for the password and a code; when it is required, the same form is "set up again" (a new
// phone): the gate then asks for the new setup. A new set of backup codes asks for a code. Backend: packages/accounts.

import { useRef, useState } from "react";
import qrcode from "qrcode-generator";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { APP } from "@/lib/app";
import { Button, Input, Section } from "@/components/ds";
import { tr } from "@/lib/i18n";
import { SettingRow } from "@/app/(app)/account/page";

type Status = { enabled: boolean; required?: boolean; backup_codes_left: number; email_codes?: boolean };

/** A QR code as SVG rectangles: no HTML injection and nothing for the CSP to block. */
function Qr({ text }: { text: string }) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const cells: React.ReactNode[] = [];
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) cells.push(<rect key={`${r}-${c}`} x={c} y={r} width={1} height={1} />);
  return (
    <svg viewBox={`-2 -2 ${n + 4} ${n + 4}`} width={180} height={180} role="img" aria-label={tr("QR code for your authenticator app")}
      style={{ background: "#fff", borderRadius: 6 }} shapeRendering="crispEdges" fill="#000">
      {cells}
    </svg>
  );
}

export default function TwoStepLogin({ isAdmin, onEnabled }: { isAdmin: boolean; onEnabled?: () => void }) {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["totp"], queryFn: () => api.get<Status>("/api/account/totp") });
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [backup, setBackup] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  // The open form under the row: turning off (or setting up again), or making new backup codes.
  const [mode, setMode] = useState<"off" | "codes" | null>(null);
  const turningOff = mode === "off";
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fail = (e: unknown) => setError(e instanceof ApiError ? e.message : tr("That didn't work. Try again."));
  // One request at a time. `busy` disables the buttons only on the next render, so a double tap or Enter plus a tap
  // could send a code twice; the second then fails (turning two-step login on ends the old session) and shows an
  // error after a success. The ref blocks it at once.
  const running = useRef(false);
  const run = async (f: () => Promise<void>) => {
    if (running.current) return;
    running.current = true;
    setError(null);
    setBusy(true);
    try { await f(); } catch (e) { fail(e); } finally { running.current = false; setBusy(false); }
  };

  const start = () => run(async () => {
    setSetup(await api.post("/api/account/totp/setup", { issuer: APP.name }));
    setCode("");
  });
  const confirm = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      const r = await api.post<{ backup_codes: string[] }>("/api/account/totp/enable", { code });
      setBackup(r.backup_codes);
      setSetup(null);
      setCode("");
      qc.invalidateQueries({ queryKey: ["totp"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    });
  };
  const off = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.post("/api/account/totp/disable", { password, code });
      setMode(null);
      setPassword("");
      setCode("");
      qc.invalidateQueries({ queryKey: ["totp"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    });
  };
  const newCodes = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      const r = await api.post<{ backup_codes: string[] }>("/api/account/totp/backup-codes", { code });
      setMode(null);
      setCode("");
      setBackup(r.backup_codes);
      qc.invalidateQueries({ queryKey: ["totp"] });
    });
  };
  const cancel = () => { setMode(null); setPassword(""); setCode(""); setError(null); };

  const on = status.data?.enabled ?? false;
  const required = status.data?.required ?? false;
  return (
    <Section label={tr("Two-step login")}>
      <SettingRow
        last={!setup && !backup && !mode}
        title={on ? tr("Two-step login is on") : tr("Two-step login is off")}
        body={<>
          {on
            ? tr("Logging in asks for a code from your authenticator app after your password. Backup codes left: {0}.", status.data?.backup_codes_left ?? 0)
            : status.data?.email_codes
              ? tr("The authenticator app is off; your codes come by email. You can add the app too.")
              : required
              ? tr("Required for your account: you use more than one tracker or you are an admin, so one password opens more than this tracker.")
              : isAdmin
                ? tr("Strongly recommended for an admin: with only a password, whoever guesses or steals it can manage every account.")
                : tr("After your password, logging in also asks for a code from an authenticator app on your phone (such as 1Password, Google Authenticator or Aegis).")}
          {" "}{tr("One setting for all your trackers.")}{" "}
          <a href="/two-step" className="ds-link">{tr("How does two-step login work?")}</a>
        </>}
        control={!setup && !mode && (on
          ? <div className="flex flex-wrap justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => { setMode("codes"); setBackup(null); }}>{tr("New backup codes…")}</Button>
              <Button size="sm" variant="ghost" onClick={() => { setMode("off"); setBackup(null); }}>
                {required ? tr("Set up again (new phone)…") : tr("Turn off…")}
              </Button>
            </div>
          : <Button size="sm" variant="secondary" disabled={busy} onClick={start}>{tr("Turn on")}</Button>)}
      />

      {setup && (
        <form onSubmit={confirm} className="flex flex-col gap-4 py-5">
          <p className="max-w-[56ch] text-[13px] text-ink-muted">{tr("Scan this code with your authenticator app, or type the key in by hand. Then enter the six-digit code it shows.")}</p>
          <div className="flex flex-wrap items-start gap-6">
            <Qr text={setup.otpauth_uri} />
            <div className="flex max-w-xs flex-col gap-3">
              <span className="text-[12px] font-medium text-ink-muted">{tr("Key")}</span>
              <code className="break-all rounded-md px-3 py-2 font-mono text-[12px]" style={{ background: "var(--surface-sunken)" }}>{setup.secret}</code>
              <Input id="totp-code" inputMode="numeric" autoComplete="one-time-code" label={tr("Code from your authenticator app")}
                value={code} onChange={(e) => setCode(e.target.value)} error={error ?? undefined} />
              <div className="flex gap-2">
                <Button type="submit" variant="primary" disabled={busy || code.trim().length < 6}>{tr("Turn on")}</Button>
                <Button type="button" variant="ghost" onClick={() => { setSetup(null); setError(null); }}>{tr("Cancel")}</Button>
              </div>
            </div>
          </div>
        </form>
      )}

      {backup && (
        <div className="flex flex-col gap-3 py-5">
          <p className="max-w-[56ch] text-[13px]">{tr("Keep these backup codes somewhere safe, for when your phone is not at hand: each one works once. They are shown only now.")}</p>
          <code className="grid max-w-sm grid-cols-2 gap-x-6 gap-y-1 rounded-md px-3 py-2 font-mono text-[13px]" style={{ background: "var(--surface-sunken)" }}>
            {backup.map((c) => <span key={c}>{c}</span>)}
          </code>
          <div><Button size="sm" variant="ghost" onClick={() => { setBackup(null); onEnabled?.(); }}>{tr("Done")}</Button></div>
        </div>
      )}

      {mode === "codes" && (
        <form onSubmit={newCodes} className="flex max-w-sm flex-col gap-4 py-5">
          <p className="text-[13px] text-ink-muted">{tr("A new set of ten backup codes. The old ones stop working.")}</p>
          <Input id="totp-codes-code" inputMode="numeric" autoComplete="one-time-code" label={tr("Code from your authenticator app")}
            value={code} onChange={(e) => setCode(e.target.value)} error={error ?? undefined} />
          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={busy || code.trim().length < 6}>{tr("Make new codes")}</Button>
            <Button type="button" variant="ghost" onClick={cancel}>{tr("Cancel")}</Button>
          </div>
        </form>
      )}

      {turningOff && (
        <form onSubmit={off} className="flex max-w-sm flex-col gap-4 py-5">
          {required && <p className="text-[13px] text-ink-muted">{tr("For a new phone: this turns two-step login off, and you set it up again straight away with the new phone. Without your old phone, use a backup code.")}</p>}
          <Input id="totp-off-password" type="password" autoComplete="current-password" label={tr("Your password")}
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <Input id="totp-off-code" inputMode="numeric" autoComplete="one-time-code" label={tr("Code from your authenticator app")}
            hint={tr("Or one of your backup codes.")} value={code} onChange={(e) => setCode(e.target.value)} error={error ?? undefined} />
          <div className="flex gap-2">
            <Button type="submit" variant="danger" disabled={busy || !password || !code}>{required ? tr("Set up again") : tr("Turn off")}</Button>
            <Button type="button" variant="ghost" onClick={cancel}>{tr("Cancel")}</Button>
          </div>
        </form>
      )}
      {error && !setup && !mode && <p className="text-sm" style={{ color: "var(--text-loss)" }}>{error}</p>}
    </Section>
  );
}
