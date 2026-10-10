"use client";

// Settings — the "change password" block from the old Streamlit auth.py, which
// the Streamlit sidebar carried on every page.
//
// Meridian's shape for a setting is an aligned row: title and explanation on the
// left, the control on the right, one hairline below. Here that is a form and not
// a switch, so the control sits below the explanation instead of next to it — the
// shape of the row stays.

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button, Input, Section } from "@/components/ds";
import { tr } from "@/lib/i18n";
import LanguageChoice from "@/components/LanguageChoice";
import SharedCostsChoice from "@/components/money/SharedCostsChoice";
import MonthPeriodsChoice from "@/components/money/MonthPeriodsChoice";
import { useQuery } from "@tanstack/react-query";
import AccountData from "@/components/AccountData";
import EmailCodes from "@/components/EmailCodes";
import TwoStepLogin from "@/components/TwoStepLogin";

/** An aligned settings row: what it is and why, then the control. */
export function SettingRow({
  title,
  body,
  control,
  last = false,
}: {
  title: React.ReactNode;
  body?: React.ReactNode;
  control?: React.ReactNode;
  last?: boolean;
}) {
  return (
    <div
      className="flex flex-col gap-4 py-4 sm:flex-row sm:items-start sm:gap-8"
      style={{ borderBottom: last ? undefined : "1px solid var(--border-subtle)" }}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-[14.5px] font-medium">{title}</span>
        {body && (
          <span className="max-w-[56ch] text-[13px] leading-relaxed text-ink-muted">{body}</span>
        )}
      </div>
      {control && <div className="flex-none pt-0.5">{control}</div>}
    </div>
  );
}

export default function AccountPage() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ is_admin: boolean; totp_enabled?: boolean; two_step?: boolean; email_codes?: boolean; apps?: string[] }>("/api/auth/me") });
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setDone(false);

    // Checked here *and* in the backend: a typo in the confirmation is not worth a
    // round trip, and the message is more useful next to the field.
    if (next !== confirm) {
      setError(tr("The new passwords don't match."));
      return;
    }

    setLoading(true);
    try {
      await api.post("/api/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tr("The password could not be changed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex max-w-[760px] flex-col gap-11">
      <Section label={tr("Language")}>
        <SettingRow
          last
          title={tr("Language of the app")}
          body={tr("Saved with your account, so it follows you to other devices.")}
          control={<LanguageChoice save />}
        />
      </Section>

      <MoneySettings />

      <Section label={tr("Access")}>
        <form onSubmit={handleSubmit} className="flex flex-col">
          {/* A hidden username field tells a password manager which login this
              change belongs to; without it, it cannot offer to update the entry. */}
          <input type="text" name="username" autoComplete="username" className="hidden" readOnly />

          <SettingRow
            title={tr("Change password")}
            body={tr("Your current password, and the new one twice. All other sessions stop working after that. That's intended.")}
          />

          <div className="flex max-w-sm flex-col gap-4 py-5">
            <Input
              id="pw-current"
              name="current-password"
              type="password"
              autoComplete="current-password"
              label={tr("Current password")}
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
            <Input
              id="pw-new"
              name="new-password"
              type="password"
              autoComplete="new-password"
              label={tr("New password")}
              hint={tr("At least 10 characters, not a common password and not your username.")}
              minLength={10}
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <Input
              id="pw-confirm"
              name="confirm-password"
              type="password"
              autoComplete="new-password"
              label={tr("New password again")}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              error={error ?? undefined}
            />

            {done && (
              <p className="text-sm" style={{ color: "var(--text-gain)" }}>{tr("Password changed.")}</p>
            )}

            <div>
              <Button type="submit" variant="primary" disabled={loading}>
                {loading ? tr("Working…") : tr("Change password")}
              </Button>
            </div>
          </div>
        </form>
      </Section>

      <TwoStepLogin isAdmin={!!me.data?.is_admin} />
      <EmailCodes />

      <AccountData twoStep={!!me.data?.two_step} byEmail={!!me.data?.email_codes} apps={me.data?.apps} />
    </div>
  );
}


/** Only for accounts with the money part: the API answers 403 otherwise, and then the section stays away. */
function MoneySettings() {
  const ok = useQuery({
    queryKey: ["shared-costs"],
    queryFn: () => api.get<{ category: string | null }>("/api/spending/shared-costs"),
    retry: false,
  });
  if (!ok.isSuccess) return null;
  return (
    <Section label={tr("Money")}>
      <SettingRow
        title={tr("Where a month starts")}
        body={tr("On the 1st, or on the day your salary comes in. Applies everywhere: monthly totals, averages, budget, net worth per month and debts.")}
      />
      <MonthPeriodsChoice />
      <SettingRow
        last
        title={tr("Your share of shared costs")}
        body={tr("Money that only passes through you for a group, such as a trip you organise, goes in “Niet meetellen”. What you paid out more than you got back is your own share: here you choose as which spending it counts. It then shows on Spending and in Saved on Net worth.")}
        control={<SharedCostsChoice />}
      />
    </Section>
  );
}
