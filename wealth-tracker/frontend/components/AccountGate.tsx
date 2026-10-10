"use client";

// What comes before the pages when the shared trackerai account is not ready for this tracker yet: two-step login
// where the account requires it, then joining this tracker (an account from another tracker).

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { APP } from "@/lib/app";
import { Button, Input } from "@/components/ds";
import EmailCodes from "@/components/EmailCodes";
import TwoStepLogin from "@/components/TwoStepLogin";
import { tr, trx } from "@/lib/i18n";

export type GateMe = {
  is_admin: boolean; totp_setup_required?: boolean; in_app?: boolean; email?: string | null; email_verify_required?: boolean;
};

export function needsGate(me: GateMe): boolean {
  return !!me.email_verify_required || !!me.totp_setup_required || me.in_app === false;
}

export default function AccountGate({ me, onReady }: { me: GateMe; onReady: () => void }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // An old login of this tracker with the same name: its password brings that data along.
  const [askOld, setAskOld] = useState(false);
  const [oldPassword, setOldPassword] = useState("");

  const logout = (
    <button type="button" className="self-start text-[12.5px] text-ink-muted underline underline-offset-4"
      onClick={async () => { await api.post("/api/auth/logout"); router.replace("/login"); }}>
      {tr("Log out")}
    </button>
  );

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="flex w-full max-w-[560px] flex-col gap-5">
        {me.email_verify_required ? (
          <>
            <h1 className="font-display text-[30px] font-light leading-tight tracking-[-0.03em]">{tr("Confirm your email")}</h1>
            <ConfirmEmail email={me.email ?? ""} onDone={onReady} />
            {logout}
          </>
        ) : me.totp_setup_required ? (
          <>
            <h1 className="font-display text-[30px] font-light leading-tight tracking-[-0.03em]">{tr("Set up two-step login")}</h1>
            <p className="text-[13px] leading-relaxed text-ink-muted">
              {tr("Your account opens more than one tracker (or you are an admin). So besides your password, logging in also needs a code: from an authenticator app, or by email. You set it up once, for all your trackers.")}
            </p>
            <TwoStepLogin isAdmin={me.is_admin} onEnabled={onReady} />
            <EmailCodes onEnabled={onReady} />
          </>
        ) : (
          <>
            <h1 className="font-display text-[30px] font-light leading-tight tracking-[-0.03em]">{trx("Use {0}", APP.name)}</h1>
            <p className="text-[13px] leading-relaxed text-ink-muted">
              {tr("You already have a trackerai account. Use it here too: the same login, and your data in this tracker stays its own.")}
            </p>
            {askOld && (
              <p className="text-[13px] leading-relaxed">{tr("You had a login here with this name: enter its password to bring your data along.")}</p>
            )}
            {askOld && (
              <Input id="old-password" type="password" autoComplete="current-password" label={tr("Password of your login here")}
                value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} />
            )}
            {error && <p className="text-sm" style={{ color: "var(--text-loss)" }}>{error}</p>}
            <div>
              <Button variant="primary" disabled={busy || (askOld && !oldPassword)} onClick={async () => {
                setError(null);
                setBusy(true);
                try {
                  await api.post("/api/auth/join", { money: true, ...(askOld ? { old_password: oldPassword } : {}) });
                  onReady();
                } catch (e) {
                  if (e instanceof ApiError && e.code === "old_login_password") setAskOld(true);
                  else setError(e instanceof ApiError ? e.message : tr("That didn't work. Try again."));
                } finally {
                  setBusy(false);
                }
              }}>{busy ? tr("Working…") : trx("Use {0}", APP.name)}</Button>
            </div>
          </>
        )}
        {logout}
      </div>
    </main>
  );
}

/** After signing up: the code from the welcome mail confirms the address, which is then the two-step login. */
function ConfirmEmail({ email, onDone }: { email: string; onDone: () => void }) {
  const [to, setTo] = useState(email);
  const [code, setCode] = useState("");
  const [changing, setChanging] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (f: () => Promise<void>) => {
    setMsg(null);
    setBusy(true);
    try { await f(); } catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : tr("That didn't work. Try again.") }); } finally { setBusy(false); }
  };
  const resend = (address?: string) => run(async () => {
    const r = await api.post<{ sent_to: string }>("/api/account/email/resend", address ? { email: address } : {});
    setTo(r.sent_to);
    setChanging(false);
    setMsg({ ok: true, text: tr("Sent to {0}.", r.sent_to) });
  });
  const note = msg && <p className="text-[12.5px]" style={{ color: msg.ok ? "var(--text-muted)" : "var(--text-loss)" }}>{msg.text}</p>;

  if (changing) {
    return (
      <form className="flex max-w-sm flex-col gap-4" onSubmit={(e) => { e.preventDefault(); resend(to); }}>
        <Input id="confirm-address" type="email" autoComplete="email" label={tr("Email address")} value={to} onChange={(e) => setTo(e.target.value)} autoFocus />
        {note}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" disabled={busy || !to}>{tr("Send the code here")}</Button>
          <Button type="button" variant="ghost" onClick={() => setChanging(false)}>{tr("Cancel")}</Button>
        </div>
      </form>
    );
  }
  return (
    <form className="flex max-w-sm flex-col gap-4" onSubmit={(e) => { e.preventDefault(); run(async () => {
      await api.post("/api/account/email/confirm", { code });
      onDone();
    }); }}>
      <p className="text-[13px] leading-relaxed text-ink-muted">
        {tr("We sent a code to {0}. Enter it to continue. From then on, logging in mails you a code too: that is your two-step login.", to)}
      </p>
      <Input id="confirm-code" inputMode="numeric" autoComplete="one-time-code" label={tr("Code from the email")} value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
      {note}
      <Button type="submit" variant="primary" size="lg" block disabled={busy || code.trim().length < 6}>{busy ? tr("Working…") : tr("Confirm")}</Button>
      <div className="flex flex-wrap items-center gap-4 text-[12.5px] text-ink-muted">
        <button type="button" className="underline underline-offset-2" onClick={() => resend()}>{tr("Send the code again")}</button>
        <button type="button" className="underline underline-offset-2" onClick={() => { setMsg(null); setChanging(true); }}>{tr("Wrong address?")}</button>
      </div>
    </form>
  );
}
