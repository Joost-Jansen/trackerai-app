"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@trackerai/ui/ds/Button";
import { useTr } from "@trackerai/ui/i18n";
import { ApiError } from "@trackerai/ui/lib/api";
import type { AccountApi } from "./AgentConnections";

export type AccountView = { id: number; username: string; display_name: string | null; is_admin: boolean; email?: string | null;
  totp_setup_required: boolean; email_verify_required: boolean; totp_enabled: boolean; email_codes: boolean };
type Consent = { client: string; redirect_host: string; app: "health" | "wealth"; resource: string; username: string; write_requested: boolean };

export default function AgentConsent({ api, setup }: { api: AccountApi; setup: (account: AccountView, done: () => void) => ReactNode }) {
  const tr = useTr();
  const [request, setRequest] = useState("");
  const [account, setAccount] = useState<AccountView | null>(null);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [version, setVersion] = useState(0);
  const [failed, setFailed] = useState(false);
  const [write, setWrite] = useState(false);
  const [health, setHealth] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const nonce = new URLSearchParams(window.location.search).get("request") ?? "";
    if (!/^[A-Za-z0-9_-]{43}$/.test(nonce)) { setFailed(true); return; }
    setRequest(nonce);
    let active = true;
    setFailed(false);
    api.get<AccountView>("/api/auth/account").then(async (a) => {
      if (!active) return;
      setAccount(a);
      if (a.totp_setup_required || a.email_verify_required) return;
      const c = await api.get<Consent>(`/api/oauth/consent?request=${encodeURIComponent(nonce)}`);
      if (active) setConsent(c);
    }).catch(e => {
      if (!active) return;
      if (e instanceof ApiError && e.status === 401) {
        window.location.replace(`/login/?next=${encodeURIComponent(`/connect/?request=${nonce}`)}`);
      } else setFailed(true);
    });
    return () => { active = false; };
  }, [api, version]);

  if (account && (account.totp_setup_required || account.email_verify_required)) {
    return setup(account, () => { setAccount(null); setVersion(v => v + 1); });
  }
  async function decide(allow: boolean) {
    setBusy(true);
    try {
      const result = await api.post<{ redirect: string }>("/api/oauth/consent", { request, allow, write: allow && write, health_consent: allow && health });
      // Only the server's validated, registered callback is returned here.
      window.location.assign(result.redirect);
    } catch { setFailed(true); setBusy(false); }
  }
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <div className="flex w-full max-w-[520px] flex-col gap-5">
        <p className="text-sm font-medium tracking-wide">TrackerAI</p>
        <h1 className="font-display text-[30px] font-light leading-tight">{tr("Connect your assistant")}</h1>
        {failed ? <p role="alert">{tr("This connection could not be completed. Start again from your assistant.")}</p> : !consent ? <p>{tr("Loading…")}</p> : (
          <>
            <p className="text-[14px] leading-relaxed">{tr("{0} wants access to your {1} tracker.", consent.client, consent.app === "health" ? tr("Health") : tr("Wealth"))}</p>
            <p className="text-[13px] text-ink-muted">{tr("Signed in as {0}.", consent.username)}</p>
            <p className="text-[13px] text-ink-muted">{tr("After approval, return to {0}. Check that this is the assistant you opened.", consent.redirect_host)}</p>
            <section className="rounded border border-border bg-surface p-4 text-[13px] leading-relaxed">
              <strong>{tr("Read-only")}</strong>
              <p className="mt-1 text-ink-muted">{consent.app === "health" ? tr("Read your activities, recovery, plans and training notes.") : tr("Read your portfolio, balances, spending and budgets.")}</p>
              {consent.write_requested && <label className="mt-4 flex items-start gap-3">
                <input type="checkbox" checked={write} onChange={e => setWrite(e.target.checked)} className="mt-1" />
                <span>{tr("Also allow editing")}<span className="block text-ink-muted">{consent.app === "health" ? tr("Create or change training plans, documents and log entries.") : tr("Label transactions and change budgets and bookkeeping settings.")}</span></span>
              </label>}
            </section>
            {consent.app === "health" && <label className="flex items-start gap-3 text-[13px] leading-relaxed">
              <input type="checkbox" checked={health} onChange={e => setHealth(e.target.checked)} className="mt-1" />
              <span>{tr("I explicitly agree to share my health data with this assistant for this connection.")}</span>
            </label>}
            <p className="text-[13px] text-ink-muted">{tr("This does not grant access to the other tracker, passwords, bank connections or admin tools. You can disconnect it on the Agents page at any time. Connect again after 90 days.")}</p>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" disabled={busy || (consent.app === "health" && !health)} onClick={() => decide(true)}>{tr("Allow access")}</Button>
              <Button disabled={busy} onClick={() => decide(false)}>{tr("Cancel")}</Button>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
