"use client";

// Bank connection — your bank directly, instead of uploading exports.
//
// Everyone brings their own Enable Banking application: in the free mode an
// application can only reach the accounts of whoever registered it. Setting it
// up is therefore a step-by-step plan, with the addresses of *this* installation
// to copy — none of it is fixed in the code; it follows from where the app runs.
// Once set up, this screen is about your banks: which are connected, with which
// accounts, and until when.
//
// The private key goes one way: in. It is stored encrypted and no screen or
// endpoint returns it.

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonthYear } from "@/lib/format";
import { Button, Checkbox, Input, Section, Select, Tag } from "@/components/ds";
import type { ConnectionStatus, FetchReport, Consent } from "@/lib/money";
import { locale, tr, trx } from "@/lib/i18n";

// The countries of the European Economic Area: where PSD2 applies. Which banks
// there are per country the page asks Enable Banking itself; no bank is listed here.
const COUNTRIES: [string, string][] = [
  ["NL", tr("Netherlands")], ["BE", tr("Belgium")], ["DE", tr("Germany")], ["FR", tr("France")], ["LU", tr("Luxembourg")],
  ["AT", tr("Austria")], ["BG", tr("Bulgaria")], ["CY", "Cyprus"], ["CZ", tr("Czechia")], ["DK", tr("Denmark")],
  ["EE", tr("Estonia")], ["ES", tr("Spain")], ["FI", "Finland"], ["GR", tr("Greece")], ["HR", tr("Croatia")],
  ["HU", tr("Hungary")], ["IE", tr("Ireland")], ["IS", tr("Iceland")], ["IT", tr("Italy")], ["LI", "Liechtenstein"],
  ["LT", tr("Lithuania")], ["LV", tr("Latvia")], ["MT", "Malta"], ["NO", tr("Norway")], ["PL", tr("Poland")],
  ["PT", "Portugal"], ["RO", tr("Romania")], ["SE", tr("Sweden")], ["SI", tr("Slovenia")], ["SK", tr("Slovakia")],
];

const BACK_PATH = "/api/connections/enablebanking/callback";

// ---------------------------------------------------------------------------
// Several banks in a row
//
// Every bank wants to hear consent itself, in its own app: that cannot be done
// for two banks at once. Whoever picks more goes through them one after the
// other; the rest waits in this tab's session until you are back from the
// previous one.
// ---------------------------------------------------------------------------

type BankChoice = { name: string; country: string };

const QUEUE = "bank-queue";

function readQueue(): BankChoice[] {
  try {
    return JSON.parse(sessionStorage.getItem(QUEUE) ?? "[]");
  } catch {
    return [];
  }
}

function applyQueue(row: BankChoice[]) {
  try {
    if (row.length) sessionStorage.setItem(QUEUE, JSON.stringify(row));
    else sessionStorage.removeItem(QUEUE);
  } catch {
    // Geen opslag (privévenster): dan één bank per keer.
  }
}

const keyOf = (b: BankChoice) => `${b.country}|${b.name}`;

/** To the bank; after consent it sends the browser back to this page. */
function useToBank(origin: string) {
  return useMutation({
    mutationFn: (b: BankChoice) =>
      api.post<{ url: string }>("/api/connections/enablebanking/start", { bank: b.name, country: b.country, origin }),
    onSuccess: (d) => { window.location.href = d.url; },
    onError: () => applyQueue([]),
  });
}

function iban(value: string | null) {
  return value ? value.replace(/(.{4})/g, "$1 ").trim() : null;
}

// From this many days before the end a consent asks for attention.
const ALMOST_EXPIRED_DAYS = 14;

function daysUntil(iso: string) {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

/** "valid until 12 Mar 2027 · 179 days left" — red when it is about to expire. */
function Validity({ t }: { t: Consent }) {
  if (!t.valid_until || t.status === "waiting" || t.status === "error") return null;
  const date = fmtDayMonthYear(t.valid_until.slice(0, 10));
  const days = daysUntil(t.valid_until);
  if (t.status === "expired" || days <= 0) {
    return <span style={{ color: "var(--text-loss)" }}>{trx("Expired on {0}", date)}</span>;
  }
  const almost = days <= ALMOST_EXPIRED_DAYS;
  return (
    <span style={almost ? { color: "var(--text-loss)" } : undefined}>{trx("Valid until {0} · {1} {2} left{3}", <b className="num">{date}</b>, days, days === 1 ? tr("day") : tr("days"), almost && tr(" (renew in time)"))}</span>
  );
}

// ---------------------------------------------------------------------------

function Copy({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Input label={label} value={value} readOnly className="min-w-[16rem] flex-1 font-mono text-[12px]"
        onFocus={(e) => e.target.select()} />
      <Button size="sm" variant="ghost" onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}>
        {copied ? tr("Copied") : tr("Copy")}
      </Button>
    </div>
  );
}

function Step({ number, title, children }: { number: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 py-3" style={{ borderTop: "1px solid var(--rule)" }}>
      <span className="num flex h-6 w-6 flex-none items-center justify-center rounded-full text-xs font-semibold"
        style={{ background: "var(--surface-inset)" }}>{number}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-2 text-[13px] leading-relaxed">
        <p className="font-semibold">{title}</p>
        {children}
      </div>
    </li>
  );
}

function KeyForm({ appId, onDone }: { appId: string | null; onDone: () => void }) {
  const [id, setId] = useState(appId ?? "");
  const [file, setFile] = useState<File | null>(null);
  const store = useMutation({
    mutationFn: async () => {
      const body = new FormData();
      body.append("app_id", id.trim());
      body.append("key", file!);
      // Not api.put: that sets Content-Type to JSON and then the file is lost.
      const res = await fetch("/api/connections/enablebanking", { method: "PUT", credentials: "include", body, headers: { "X-Locale": locale } });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new ApiError(res.status, json.detail || res.statusText);
      return json as ConnectionStatus;
    },
    onSuccess: () => {
      setFile(null);
      onDone();
    },
  });

  return (
    <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); store.mutate(); }}>
      <Input label="App-ID" placeholder={tr("e.g. 5bec30d8-…")} hint={tr("The name of the .pem file, without .pem")}
        value={id} onChange={(e) => setId(e.target.value)} className="font-mono text-[12px]" />
      <label className="flex flex-col gap-1 text-xs text-ink-muted">{trx("Private key (.pem){0}", <input type="file" accept=".pem,application/x-pem-file,application/x-x509-ca-cert,text/plain,application/octet-stream"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-[13px] text-text" />)}</label>
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={!id.trim() || !file || store.isPending}>
          {store.isPending ? tr("Working…") : appId ? tr("Replace") : tr("Save")}
        </Button>
        {store.isError && (
          <span className="text-xs" style={{ color: "var(--text-loss)" }}>{(store.error as ApiError).message}</span>
        )}
      </div>
    </form>
  );
}

/** Tick one or more banks, also from different countries. */
function PickBanks({ origin, linked }: { origin: string; linked: Map<string, Consent> }) {
  const [country, setCountry] = useState("NL");
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState<BankChoice[]>([]);
  const banks = useQuery({
    queryKey: ["connections", "banks", country],
    queryFn: () => api.get<{ banks: { name: string; country: string }[] }>(`/api/connections/enablebanking/banks?country=${country}`),
  });
  const toBank = useToBank(origin);

  const visible = (banks.data?.banks ?? []).filter((b) => b.name.toLowerCase().includes(search.trim().toLowerCase()));
  const isChosen = (b: BankChoice) => chosen.some((g) => keyOf(g) === keyOf(b));
  const toggle = (b: BankChoice, on: boolean) =>
    setChosen((now) => (on ? [...now, b] : now.filter((g) => keyOf(g) !== keyOf(b))));

  const begin = () => {
    const [first, ...rest] = chosen;
    applyQueue(rest);
    toBank.mutate(first);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <Select label={tr("Country")} value={country} onChange={(e) => { setCountry(e.target.value); setSearch(""); }}>
          {COUNTRIES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
        </Select>
        <Input label={tr("Search")} placeholder={tr("e.g. ING or bunq")} value={search} onChange={(e) => setSearch(e.target.value)}
          className="min-w-[12rem] flex-1" />
      </div>

      <ul className="flex max-h-72 flex-col overflow-y-auto rounded-md" style={{ border: "1px solid var(--rule)" }}>
        {banks.isLoading && <li className="p-3 text-xs text-ink-muted">{tr("Loading banks…")}</li>}
        {banks.data && visible.length === 0 && <li className="p-3 text-xs text-ink-muted">{tr("No bank found.")}</li>}
        {visible.map((b) => {
          const choice = { name: b.name, country };
          const t = linked.get(keyOf(choice));
          return (
            <li key={b.name} className="flex items-center justify-between gap-2 px-3 py-2"
              style={{ borderTop: "1px solid var(--rule)" }}>
              <Checkbox label={b.name} checked={isChosen(choice)} onChange={(on) => toggle(choice, on)} />
              {t && (
                <Tag tone="gain">{trx("connected{0}", t.valid_until && <>{" "}{trx("until {0}", fmtDayMonthYear(t.valid_until.slice(0, 10)))}</>)}</Tag>
              )}
            </li>
          );
        })}
      </ul>

      {chosen.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-ink-muted">{tr("Chosen:")}</span>
          {chosen.map((g, i) => (
            <button key={keyOf(g)} type="button" onClick={() => toggle(g, false)} title={tr("Remove")}>
              <Tag outline>{i + 1}. {g.name}{g.country !== "NL" && ` (${g.country})`} ×</Tag>
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={!chosen.length || !origin || toBank.isPending} onClick={begin}>
          {toBank.isPending ? tr("To your bank…")
            : chosen.length > 1 ? tr("Connect {0} banks", chosen.length) : tr("Give consent")}
        </Button>
        {chosen.length > 1 && (
          <span className="text-xs text-ink-muted">{trx("You'll go through them one after another: first {0}, after your approval on to {1} automatically.", chosen[0].name, chosen[1].name)}</span>
        )}
      </div>
      {(banks.isError || toBank.isError) && (
        <p className="text-xs" style={{ color: "var(--text-loss)" }}>
          {((banks.error ?? toBank.error) as ApiError).message}
        </p>
      )}
    </div>
  );
}

const STATUS: Record<Consent["status"], { label: string; tone: "gain" | "loss" | "neutral" }> = {
  active: { label: "linked", tone: "gain" },
  waiting: { label: tr("waiting for your approval"), tone: "neutral" },
  expired: { label: "expired", tone: "loss" },
  error: { label: "failed", tone: "loss" },
};

function BankCard({ t, origin, onDone }: { t: Consent; origin: string; onDone: () => void }) {
  const revoke = useMutation({
    mutationFn: () => api.del(`/api/connections/enablebanking/consents/${t.id}`),
    onSuccess: onDone,
  });
  const toBank = useToBank(origin);
  const { label, tone } = STATUS[t.status];
  const again = t.status !== "active";

  return (
    <li className="flex flex-col gap-2 py-4" style={{ borderTop: "1px solid var(--rule)" }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[15px] font-semibold">
          {t.bank} <Tag tone={tone}>{label}</Tag>
        </span>
        <span className="flex gap-1">
          <Button size="sm" variant={again ? "primary" : "ghost"} disabled={!origin || toBank.isPending}
            onClick={() => toBank.mutate({ name: t.bank, country: t.country })}>
            {toBank.isPending ? tr("To your bank…") : again ? tr("Connect again") : tr("Renew")}
          </Button>
          <Button size="sm" variant="ghost" disabled={revoke.isPending} onClick={() => {
            if (window.confirm(tr("Revoke consent at {0}? Your accounts and transactions stay.", t.bank))) revoke.mutate();
          }}>{tr("Revoke")}</Button>
        </span>
      </div>

      {t.accounts.length > 0 ? (
        <ul className="flex flex-col gap-0.5 text-[13px]">
          {t.accounts.map((r) => (
            <li key={r.id} className="flex flex-wrap gap-x-3">
              <span>{r.name}</span>
              {r.iban && <span className="num text-ink-muted">{iban(r.iban)}</span>}
            </li>
          ))}
        </ul>
      ) : t.status === "active" && (
        <p className="text-xs text-ink-muted">{tr("The bank returned no accounts. Connect again and tick your accounts.")}</p>
      )}

      <p className="text-[13px]"><Validity t={t} /></p>
      <p className="text-xs text-ink-muted">
        {t.status === "waiting"
          ? <>{trx("Started {0}; not back from your bank yet.", fmtDayMonthYear(t.created_at.slice(0, 10)))}</>
          : t.last_fetched && <>{trx("Last fetched {0}", fmtDayMonthYear(t.last_fetched.slice(0, 10)))}</>}
      </p>
      {t.error && <p className="text-xs" style={{ color: "var(--text-loss)" }}>{t.error}</p>}
      {toBank.isError && <p className="text-xs" style={{ color: "var(--text-loss)" }}>{(toBank.error as ApiError).message}</p>}
    </li>
  );
}

/** Back from one bank while another one is waiting: on after a few seconds. */
function FollowUp({ row, origin, onStop }: { row: BankChoice[]; origin: string; onStop: () => void }) {
  const [tally, setTally] = useState(4);
  const toBank = useToBank(origin);
  const started = useRef(false);
  const [following, ...rest] = row;

  useEffect(() => {
    if (tally > 0) {
      const t = setTimeout(() => setTally((n) => n - 1), 1000);
      return () => clearTimeout(t);
    }
    if (!started.current) {
      started.current = true;
      applyQueue(rest);
      toBank.mutate(following);
    }
  }, [tally]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md p-3 text-sm"
      style={{ background: "var(--surface-inset)" }}>
      <span>{trx("Next: {0}{1}{2}", <b>{following.name}</b>, rest.length > 0 && <span className="text-ink-muted">{" "}{trx("(then {0} more)", rest.map((b) => b.name).join(", "))}</span>, toBank.isError ? <span className="block text-xs" style={{ color: "var(--text-loss)" }}>{(toBank.error as ApiError).message}</span>
          : <span className="text-ink-muted"> – {tally > 0 ? tr("in {0} s", tally) : tr("to your bank…")}</span>)}</span>
      <span className="flex gap-1">
        <Button size="sm" variant="primary" disabled={toBank.isPending} onClick={() => setTally(0)}>{tr("Go now")}</Button>
        <Button size="sm" variant="ghost" onClick={() => { applyQueue([]); onStop(); }}>{tr("Stop")}</Button>
      </span>
    </div>
  );
}

export default function ConnectPage() {
  const qc = useQueryClient();
  const [origin, setOrigin] = useState("");
  const [message, setMessage] = useState<{ good: boolean; text: string } | null>(null);
  const [queue, setQueue] = useState<BankChoice[]>([]);

  useEffect(() => {
    setOrigin(window.location.origin);
    // Back from the bank: the backend puts the result in the address bar.
    const p = new URLSearchParams(window.location.search);
    const bank = p.get("bank") || tr("Your bank");
    if (p.get("connected")) {
      const next = Number(p.get("added") ?? 0);
      setMessage({ good: true, text: tr("{0} is connected. Fetched {1} new {2}.", bank, next, next === 1 ? tr("transaction") : tr("transactions")) });
    } else if (p.get("error")) {
      setMessage({ good: false, text: `${bank}: ${p.get("error")}` });
    }
    // Only carry on with the next bank if we really just came back from the previous
    // one; an old queue on a normal open is forgotten.
    if (p.get("connected") || p.get("error")) setQueue(readQueue());
    else applyQueue([]);
    if (p.toString()) window.history.replaceState(null, "", window.location.pathname);
  }, []);

  const status = useQuery({ queryKey: ["connections"], queryFn: () => api.get<ConnectionStatus>("/api/connections") });
  const refresh = () => { qc.invalidateQueries(); };
  const retrieve = useMutation({
    mutationFn: () => api.post<FetchReport>("/api/connections/enablebanking/fetch"),
    onSuccess: refresh,
  });
  const everything = useMutation({ mutationFn: () => api.del("/api/connections/enablebanking"), onSuccess: refresh });

  const s = status.data;
  const consents = s?.consents ?? [];
  const active = consents.filter((t) => t.status === "active");
  const linked = new Map(active.map((t) => [keyOf({ name: t.bank, country: t.country }), t] as const));
  const countAccounts = active.reduce((n, t) => n + t.accounts.length, 0);

  const steps = (
    <ol className="flex flex-col">
      <Step number={1} title={tr("Create a free account at Enable Banking")}>
        <p>{trx("At {0}, and log in. Via your name at the top right you get to the Control Panel.", <a href="https://enablebanking.com" target="_blank" rel="noreferrer" className="underline underline-offset-4">enablebanking.com</a>)}</p>
      </Step>
      <Step number={2} title={tr("Register an application")}>
        <p>{trx("In the Control Panel: {0} → new application. Fill in:", <b>API applications</b>)}</p>
        <ul className="list-disc pl-5">
          <li>{trx("{0} Sandbox only works with test banks.", <b>Environment: Production.</b>)}</li>
          <li>{trx("{0} “Generate in the browser (using SubtleCrypto) and export private key”.", <b>{tr("Key:")}</b>)}</li>
          <li>{trx("{0} something recognisable: your bank shows that name when you give consent.", <b>Application name:</b>)}</li>
        </ul>
        {origin && (
          <div className="flex flex-col gap-2 pt-1">
            <Copy label="Redirect URL" value={`${origin}${BACK_PATH}`} />
            <Copy label="Privacy URL" value={`${origin}/privacy`} />
            <Copy label="Terms URL" value={`${origin}/terms`} />
          </div>
        )}
        <p>{trx("Click {0}. Your browser downloads a {1} file: your private key. The name of that file, without .pem, is your {2}. Keep the file safe and share it with no one.", <b>Register</b>, <b>.pem</b>, <b>{tr("app ID")}</b>)}</p>
      </Step>
      <Step number={3} title={tr("Activate with your own accounts")}>
        <p>{trx("Your new application is “Inactive”. Click {0}, choose your bank and approve in your bank app. Do that for {1} you want to connect here: your application can only reach banks you added there. After that it is “Restricted” and “Active”. That's how it should be.", <b>Activate by linking accounts</b>, <b>{tr("every bank")}</b>)}</p>
      </Step>
      <Step number={4} title={tr("Put your app ID and key in the app")}>
        <p>{trx("The key is stored encrypted and is never returned by any screen.{0}", s?.configured && <>{" "}{trx("Set up for app ID {0}.", <code className="num">{s.app_id}</code>)}</>)}</p>
        <KeyForm key={s?.app_id ?? "empty"} appId={s?.app_id ?? null} onDone={refresh} />
      </Step>
      {!s?.configured && (
        <Step number={5} title={tr("Choose your banks and give consent")}>
          <p className="text-ink-muted">{tr("Possible once you've done step 4.")}</p>
        </Step>
      )}
    </ol>
  );

  return (
    <div className="flex flex-col gap-8">
      {message && (
        <p className="rounded-md p-3 text-sm" style={{ background: "var(--surface-inset)", color: message.good ? "var(--text-gain)" : "var(--text-loss)" }}>
          {message.text}
        </p>
      )}
      {queue.length > 0 && origin && <FollowUp row={queue} origin={origin} onStop={() => setQueue([])} />}

      {s?.configured && (
        <>
          <Section
            label={tr("Your banks")}
            meta={consents.length > 0 && (
              <span className="num">{trx("{0} connected · {1} {2}", active.length, countAccounts, countAccounts === 1 ? tr("account") : tr("accounts"))}</span>
            )}
            action={active.length > 0 && (
              <Button size="sm" variant="secondary" disabled={retrieve.isPending} onClick={() => retrieve.mutate()}>
                {retrieve.isPending ? tr("Fetching…") : tr("Fetch now")}
              </Button>
            )}
          >
            {retrieve.data && (
              <p className="py-2 text-xs text-ink-muted">{trx("{0} · balance of {1} {2} updated{3}", <b className="num" style={{ color: "var(--text-gain)" }}>{trx("{0} new", retrieve.data.added)}</b>, retrieve.data.balances, retrieve.data.balances === 1 ? tr("account") : tr("accounts"), retrieve.data.errors.map((f) => <span key={f} className="block" style={{ color: "var(--text-loss)" }}>{f}</span>))}</p>
            )}
            {consents.length > 0 ? (
              <ul className="flex flex-col">
                {consents.map((t) => <BankCard key={t.id} t={t} origin={origin} onDone={refresh} />)}
              </ul>
            ) : (
              <p className="py-3 text-[13px] text-ink-muted">{tr("No bank connected yet. Choose one or more banks below.")}</p>
            )}
          </Section>

          <Section
            label={tr("Add banks")}
            info={
              <>{tr("Tick one or more banks. Each bank asks for approval in its own app, so you go through them one after another and briefly come back here in between. After each bank we fetch your transactions and balance right away. What you already uploaded with an export stays and doesn't come in twice. Consent lasts about 180 days at most; after that you click “Connect again”.")}</>
            }
          >
            <PickBanks origin={origin} linked={linked} />
          </Section>
        </>
      )}

      <Section
        label={s?.configured ? tr("Settings") : tr("Connect your bank")}
        info={
          <>{tr("Via Enable Banking, a licensed provider under the European payment services directive (PSD2). The connection can only read: balance and transactions, never pay. In the free mode you register your own application, which can only reach your accounts.")}</>
        }
      >
        {s?.configured ? (
          <details>
            <summary className="cursor-pointer py-2 text-[13px]">{trx("Set up with app ID {0}: step-by-step plan, replace key", <code className="num">{s.app_id}</code>)}</summary>
            {steps}
            <div className="pt-3">
              <Button size="sm" variant="ghost" disabled={everything.isPending} onClick={() => {
                if (window.confirm(tr("Delete your key and all consents? Your accounts and transactions stay."))) everything.mutate();
              }}>{tr("Delete key and connections")}</Button>
            </div>
          </details>
        ) : steps}
      </Section>
    </div>
  );
}
