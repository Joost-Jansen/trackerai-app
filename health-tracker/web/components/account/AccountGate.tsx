"use client";

// What comes before the pages when the shared trackerai account is not ready for health-tracker yet: two-step login
// where the account requires it, then joining health-tracker (with consent for the health data, which the person gives
// themselves, also when an admin gave them the app).

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import EmailCodesCard from "@/components/account/EmailCodesCard";
import TwoStepCard from "@/components/account/TwoStepCard";
import { Button, Checkbox, Input, Logomark } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/i18n";
import { rich } from "@/lib/i18n/rich";
import type { Me } from "@/lib/training";

export function needsGate(me: Me): boolean {
  return !!me.email_verify_required || !!me.totp_setup_required || me.in_app === false || !!me.consent_needed;
}

export default function AccountGate({ me, onReady }: { me: Me; onReady?: () => void }) {
  const t = useT();
  const g = t.account.gate;
  const router = useRouter();
  const qc = useQueryClient();
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ["me"] }); onReady?.(); };

  const logout = (
    <button type="button" className="self-start text-[12.5px] text-ink-muted underline underline-offset-4"
      onClick={async () => { await api.post("/api/logout"); router.replace("/login/"); }}>
      {g.logout}
    </button>
  );

  if (me.email_verify_required) {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <div className="flex w-full max-w-[400px] flex-col gap-5">
          <Logomark height={30} />
          <h1 className="font-display text-[30px] font-light leading-tight tracking-[-0.03em]">{g.emailTitle}</h1>
          <ConfirmEmail email={me.email ?? ""} onDone={refresh} />
          {logout}
        </div>
      </main>
    );
  }

  if (me.totp_setup_required) {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <div className="flex w-full max-w-[520px] flex-col gap-5">
          <Logomark height={30} />
          <h1 className="font-display text-[30px] font-light leading-tight tracking-[-0.03em]">{g.totpTitle}</h1>
          <p className="text-[13px] leading-relaxed text-ink-muted">{g.totpText}</p>
          <TwoStepCard me={me} onEnabled={refresh} />
          <EmailCodesCard me={me} onEnabled={refresh} />
          {logout}
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form
        className="flex w-full max-w-[400px] flex-col gap-5"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          setBusy(true);
          try {
            await api.post("/api/account/apps/health", { consent });
            await refresh();
          } catch (err) {
            setError(errorText(err, t, t.common.failed));
          } finally {
            setBusy(false);
          }
        }}
      >
        <Logomark height={30} />
        <h1 className="font-display text-[30px] font-light leading-tight tracking-[-0.03em]">{me.in_app ? g.consentTitle : g.joinTitle}</h1>
        {!me.in_app && <p className="text-[13px] leading-relaxed text-ink-muted">{g.joinText}</p>}
        <Checkbox
          checked={consent}
          onChange={setConsent}
          className="items-start text-[12.5px] leading-relaxed text-ink-muted"
          label={rich(t.auth.consent, { link: (c) => <Link href="/privacy/" target="_blank" className="underline underline-offset-2">{c}</Link> })}
        />
        {error && <p className="text-[12.5px] text-loss">{error}</p>}
        <Button type="submit" variant="primary" size="lg" block disabled={busy || !consent}>{busy ? t.common.busy : g.join}</Button>
        {logout}
      </form>
    </main>
  );
}

/** After signing up: the code from the welcome mail confirms the address, which is then the two-step login. */
function ConfirmEmail({ email, onDone }: { email: string; onDone: () => void }) {
  const t = useT();
  const g = t.account.gate;
  const [to, setTo] = useState(email);
  const [code, setCode] = useState("");
  const [changing, setChanging] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (f: () => Promise<void>) => {
    setMsg(null);
    setBusy(true);
    try { await f(); } catch (err) { setMsg({ ok: false, text: errorText(err, t, t.common.failed) }); } finally { setBusy(false); }
  };
  const resend = (address?: string) => run(async () => {
    const r = await api.post<{ sent_to: string }>("/api/account/email/resend", address ? { email: address } : {});
    setTo(r.sent_to);
    setChanging(false);
    setMsg({ ok: true, text: g.emailSent(r.sent_to) });
  });

  if (changing) {
    return (
      <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); resend(to); }}>
        <Input type="email" autoComplete="email" label={g.emailAddress} value={to} onChange={(e) => setTo(e.target.value)} autoFocus />
        {msg && <p className={`text-[12.5px] ${msg.ok ? "text-ink-muted" : "text-loss"}`}>{msg.text}</p>}
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={busy || !to}>{g.emailSendHere}</Button>
          <Button type="button" variant="ghost" onClick={() => setChanging(false)}>{t.account.twoStep.cancel}</Button>
        </div>
      </form>
    );
  }
  return (
    <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); run(async () => {
      await api.post("/api/account/email/confirm", { code });
      onDone();
    }); }}>
      <p className="text-[13px] leading-relaxed text-ink-muted">{g.emailText(to)}</p>
      <Input inputMode="numeric" autoComplete="one-time-code" label={t.account.emailCodes.code} value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
      {msg && <p className={`text-[12.5px] ${msg.ok ? "text-ink-muted" : "text-loss"}`}>{msg.text}</p>}
      <Button type="submit" variant="primary" size="lg" block disabled={busy || code.trim().length < 6}>{busy ? t.common.busy : g.emailConfirm}</Button>
      <div className="flex flex-wrap items-center gap-4 text-[12.5px] text-ink-muted">
        <button type="button" className="underline underline-offset-2" onClick={() => resend()}>{g.emailAgain}</button>
        <button type="button" className="underline underline-offset-2" onClick={() => { setMsg(null); setChanging(true); }}>{g.emailWrong}</button>
      </div>
    </form>
  );
}
