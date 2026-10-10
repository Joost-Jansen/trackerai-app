"use client";

// Settings → Your data: download everything, stop using this tracker (only its data
// goes), or delete the whole trackerai account, in every tracker. Both ask for the
// password again, and for the two-step code when that is on (packages/accounts).

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button, Input, Section } from "@/components/ds";
import { tr } from "@/lib/i18n";
import { SettingRow } from "@/app/(app)/account/page";
import { MailCodeButton } from "@/components/EmailCodes";

export default function AccountData({ twoStep, byEmail = false, apps = [] }: { twoStep: boolean; byEmail?: boolean; apps?: string[] }) {
  const [open, setOpen] = useState<"delete" | "leave" | false>(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [sure, setSure] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function remove(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (open === "leave") {
        await api.del("/api/account/apps/wealth", { password, totp: twoStep ? code : undefined });
        window.location.href = "/";
      } else {
        await api.del("/api/account", { password, totp: twoStep ? code : undefined });
        window.location.href = "/login";
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tr("The account could not be deleted"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section label={tr("Your data")}>
      <SettingRow
        title={tr("Download your data")}
        body={tr("A zip with everything the app holds for you: every table as CSV and JSON, your account, your feedback and any stored uploads. Secrets such as the bank key are left out.")}
        control={<a className="ds-btn ds-btn--secondary ds-btn--sm" href="/api/account/export" download>{tr("Download")}</a>}
      />
      {apps.length > 1 && (
        <SettingRow
          title={tr("Stop using this tracker")}
          body={tr("Deletes only your data here: portfolio, bank transactions, budgets, tokens, feedback. Bank connections are revoked at Enable Banking. Your account and your other trackers stay.")}
          control={!open && <Button size="sm" variant="ghost" onClick={() => setOpen("leave")}>{tr("Stop using…")}</Button>}
        />
      )}
      <SettingRow
        last={!open}
        title={tr("Delete account")}
        body={tr("Deletes your whole trackerai account, in every tracker you use, with all its data. Here: portfolio, bank transactions, budgets, tokens, feedback. Bank connections are revoked at Enable Banking. This can't be undone.")}
        control={!open && <Button size="sm" variant="ghost" onClick={() => setOpen("delete")}>{tr("Delete account…")}</Button>}
      />
      {open && (
        <form onSubmit={remove} className="flex max-w-sm flex-col gap-4 py-5">
          <Input id="delete-password" type="password" autoComplete="current-password" label={tr("Your password")}
            value={password} onChange={(e) => setPassword(e.target.value)} />
          {twoStep && (
            <Input id="delete-code" inputMode="numeric" autoComplete="one-time-code" label={tr("Code from your app or email")}
              hint={tr("Or one of your backup codes.")} value={code} onChange={(e) => setCode(e.target.value)} />
          )}
          {byEmail && <div><MailCodeButton /></div>}
          <label className="flex items-start gap-2 text-[13px]">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-0.5" />
            <span>{tr("I understand that everything is deleted for good.")}</span>
          </label>
          {error && <p className="text-sm" style={{ color: "var(--text-loss)" }}>{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" variant="danger" disabled={busy || !sure || !password}>
              {busy ? tr("Working…") : open === "leave" ? tr("Delete my data here") : tr("Delete my account")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => { setOpen(false); setError(null); }}>{tr("Cancel")}</Button>
          </div>
        </form>
      )}
    </Section>
  );
}
