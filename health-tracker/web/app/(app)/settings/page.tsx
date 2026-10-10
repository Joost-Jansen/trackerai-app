"use client";

// Account: your name as the site and coaching agents call you, your password, two-step login and the language of
// the site.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import LanguageSwitch from "@/components/LanguageSwitch";
import EmailCodesCard, { MailCodeButton } from "@/components/account/EmailCodesCard";
import TwoStepCard from "@/components/account/TwoStepCard";
import { Button, Input } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/i18n";
import type { Me } from "@/lib/training";

function NameCard({ me }: { me: Me }) {
  const t = useT();
  const qc = useQueryClient();
  const [name, setName] = useState(me.display_name ?? "");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Card title={t.account.name}>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api.patch("/api/account", { display_name: name });
            setMsg(t.common.saved);
            qc.invalidateQueries({ queryKey: ["me"] });
          } catch (err) {
            setMsg(errorText(err, t, t.common.saveFailed));
          }
        }}
      >
        <Input label={t.account.displayName} value={name} onChange={(e) => setName(e.target.value)} placeholder={me.username} className="w-64" />
        <Button type="submit" size="sm" variant="primary">{t.common.save}</Button>
        {msg && <span className="text-[12.5px] text-ink-muted">{msg}</span>}
      </form>
      <p className="mt-3 text-[12px] text-ink-muted">{t.account.username}: <span className="font-mono">{me.username}</span>{me.is_admin ? ` · ${t.account.admin}` : ""}</p>
    </Card>
  );
}

function LanguageCard() {
  const t = useT();
  return (
    <Card title={t.language.label}>
      <LanguageSwitch save />
      <p className="mt-3 max-w-prose text-[12px] text-ink-muted">{t.language.hint}</p>
    </Card>
  );
}

function PasswordCard() {
  const t = useT();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <Card title={t.account.passwordTitle}>
      <form
        className="flex max-w-sm flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (next !== repeat) return setMsg({ ok: false, text: t.account.mismatch });
          try {
            await api.post("/api/account/password", { current, new: next });
            setMsg({ ok: true, text: `${t.account.changed} ${t.account.otherSessions}` });
            setCurrent("");
            setNext("");
            setRepeat("");
          } catch (err) {
            setMsg({ ok: false, text: errorText(err, t, t.account.changeFailed) });
          }
        }}
      >
        <Input type="password" autoComplete="current-password" label={t.account.current} value={current} onChange={(e) => setCurrent(e.target.value)} />
        <Input type="password" autoComplete="new-password" label={t.account.new} hint={t.account.newHint} value={next} onChange={(e) => setNext(e.target.value)} />
        <Input type="password" autoComplete="new-password" label={t.account.repeat} value={repeat} onChange={(e) => setRepeat(e.target.value)} />
        <div className="flex items-center gap-3">
          <Button type="submit" size="sm" variant="primary" disabled={!current || !next}>{t.account.change}</Button>
          {msg && <span className={`text-[12.5px] ${msg.ok ? "text-gain" : "text-loss"}`}>{msg.text}</span>}
        </div>
      </form>
    </Card>
  );
}

function AppsCard({ me }: { me: Me }) {
  const t = useT();
  const m = t.account.apps;
  return (
    <Card title={m.title}>
      <p className="mb-3 max-w-prose text-[12.5px] text-ink-muted">{m.text}</p>
      <ul className="flex flex-col gap-1 text-[13px]">
        {(["health", "wealth"] as const).filter((a) => me.apps?.includes(a)).map((a) => (
          <li key={a}>{m[a]} <span className="text-ink-muted">· {m.inUse}</span></li>
        ))}
      </ul>
    </Card>
  );
}

function LeaveForm({ me }: { me: Me }) {
  const t = useT();
  const m = t.account.data;
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <form
      className="mt-6 flex max-w-sm flex-col gap-3 border-t border-border pt-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!confirm(m.leaveConfirm)) return;
        try {
          await api.del("/api/account/apps/health", { password, ...(me.two_step ? { totp: code } : {}) });
          alert(m.left);
          window.location.href = "/dashboard/";
        } catch (err) {
          setMsg(errorText(err, t, m.failed));
        }
      }}
    >
      <h3 className="text-[13.5px] font-semibold">{m.leaveTitle}</h3>
      <p className="text-[12.5px] text-ink-muted">{m.leaveText}</p>
      <Input type="password" autoComplete="current-password" label={m.deletePassword} value={password} onChange={(e) => setPassword(e.target.value)} />
      {me.two_step && <Input inputMode="numeric" autoComplete="one-time-code" label={m.deleteCode} value={code} onChange={(e) => setCode(e.target.value)} />}
      {me.email_codes && <MailCodeButton />}
      <div className="flex items-center gap-3">
        <Button type="submit" size="sm" variant="secondary" disabled={!password || (!!me.two_step && !code)}>{m.leave}</Button>
        {msg && <span className="text-[12.5px] text-loss">{msg}</span>}
      </div>
    </form>
  );
}

function DataCard({ me }: { me: Me }) {
  const t = useT();
  const m = t.account.data;
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Card title={m.title}>
      <div className="flex max-w-prose flex-col gap-3">
        <p className="text-[12.5px] text-ink-muted">{m.exportText}</p>
        {/* a plain link: the browser downloads the zip itself, however large */}
        <a href="/api/account/export" download className="self-start rounded border border-border px-3 py-1.5 text-[12.5px] hover:bg-[var(--surface-sunken)]">
          {m.export}
        </a>
      </div>
      <form
        className="mt-6 flex max-w-sm flex-col gap-3 border-t border-border pt-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!confirm(m.deleteConfirm)) return;
          try {
            await api.del("/api/account", { password, ...(me.two_step ? { totp: code } : {}) });
            alert(m.deleted);
            window.location.href = "/login/";
          } catch (err) {
            setMsg(errorText(err, t, m.failed));
          }
        }}
      >
        <h3 className="text-[13.5px] font-semibold">{m.deleteTitle}</h3>
        <p className="text-[12.5px] text-ink-muted">{m.deleteText}</p>
        <Input type="password" autoComplete="current-password" label={m.deletePassword} value={password} onChange={(e) => setPassword(e.target.value)} />
        {me.two_step && <Input inputMode="numeric" autoComplete="one-time-code" label={m.deleteCode} value={code} onChange={(e) => setCode(e.target.value)} />}
      {me.email_codes && <MailCodeButton />}
        <div className="flex items-center gap-3">
          <Button type="submit" size="sm" variant="danger" disabled={!password || (!!me.two_step && !code)}>{m.delete}</Button>
          {msg && <span className="text-[12.5px] text-loss">{msg}</span>}
        </div>
      </form>
      {(me.apps?.length ?? 0) > 1 && <LeaveForm me={me} />}
    </Card>
  );
}

export default function AccountPage() {
  const t = useT();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  if (!me.data) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <div className="flex flex-col gap-4">
        <NameCard me={me.data} />
        <LanguageCard />
        <DataCard me={me.data} />
      </div>
      <div className="flex flex-col gap-4">
        <PasswordCard />
        <TwoStepCard me={me.data} />
        <EmailCodesCard me={me.data} />
        <AppsCard me={me.data} />
      </div>
    </div>
  );
}
