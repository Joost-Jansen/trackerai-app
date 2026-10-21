"use client";

// Logging in and signing up on the front door itself, with the shared trackerai account: one account, and at sign-up
// the trackers to use (health, wealth or both; the other can be added later). The session cookie lives on the parent
// domain, so after this every tracker opens without asking again. The page serving the front door forwards /api/* to
// a tracker's API, and every tracker answers the same account routes (packages/accounts).
//
// The only client JavaScript on the front door: the rest stays a server component.

import { useEffect, useState } from "react";
import { BRANDS, type BrandId, type Locale } from "./brands";
import { COPY } from "./copy";
import { HealthMark, WealthMark } from "./marks";

type Account = {
  username: string;
  display_name: string | null;
  apps: string[];
  email?: string | null;
  email_verify_required?: boolean;
  is_admin?: boolean;
};
type State = { status: "loading" } | { status: "out" } | { status: "in"; account: Account };

const MARK = { health: HealthMark, wealth: WealthMark };
const ORDER: BrandId[] = ["health", "wealth"];

// One state for the nav and the panel: logging in or out in one shows in the other.
let shared: State = { status: "loading" };
const listeners = new Set<(s: State) => void>();
let asked = false;

function publish(s: State) {
  shared = s;
  listeners.forEach((l) => l(s));
}

async function refresh() {
  try {
    const r = await fetch("/api/auth/account", { credentials: "same-origin" });
    publish(r.ok ? { status: "in", account: await r.json() } : { status: "out" });
  } catch {
    publish({ status: "out" });
  }
}

/** The account behind the session cookie: asked once per page, shared by every component. */
function useAccount(): State {
  const [state, setState] = useState<State>(shared);
  useEffect(() => {
    listeners.add(setState);
    setState(shared);
    if (!asked) {
      asked = true;
      refresh();
    }
    return () => {
      listeners.delete(setState);
    };
  }, []);
  return state;
}

async function post(
  path: string,
  body: unknown,
): Promise<{ ok: boolean; code?: string; detail?: string; params?: Record<string, unknown> }> {
  const r = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.ok) return { ok: true };
  const data = await r.json().catch(() => ({}));
  return { ok: false, code: data.code, detail: typeof data.detail === "string" ? data.detail : undefined, params: data.params };
}

/** The nav's last link: "Log in", or the name of whoever is logged in. Both go to the panel below. */
export function NavAccount({ locale }: { locale: Locale }) {
  const c = COPY[locale];
  const state = useAccount();
  const name = state.status === "in" ? state.account.display_name || state.account.username : null;
  return (
    <a href="#login" className="mk-nav-cta">
      {name ?? c.nav.login}
    </a>
  );
}

/** Confirming the address from sign-up: the code from the welcome mail. Then it is the two-step login. */
function ConfirmEmail({ locale, account }: { locale: Locale; account: Account }) {
  const a = COPY[locale].account;
  const [to, setTo] = useState(account.email ?? "");
  const [code, setCode] = useState("");
  const [changing, setChanging] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function resend(address?: string) {
    setMsg(null);
    setBusy(true);
    const r = await fetch("/api/account/email/resend", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(address ? { email: address } : {}),
    }).catch(() => null);
    const data = r ? await r.json().catch(() => ({})) : {};
    if (r?.ok) {
      setTo(data.sent_to);
      setChanging(false);
      setMsg({ ok: true, text: a.sent.replace("{to}", data.sent_to) });
    } else {
      setMsg({ ok: false, text: data.detail ?? a.failed });
    }
    setBusy(false);
  }

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    setBusy(true);
    const r = await post("/api/account/email/confirm", { code }).catch(() => ({ ok: false, detail: undefined }));
    if (r.ok) await refresh();
    else setMsg({ ok: false, text: r.detail ?? a.failed });
    setBusy(false);
  }

  return (
    <div className="mk-account">
      <p className="mk-account-who">{a.confirmTitle}</p>
      {changing ? (
        <form
          className="mk-form"
          onSubmit={(e) => {
            e.preventDefault();
            resend(to);
          }}
        >
          <label className="mk-field">
            <span>{a.email}</span>
            <input name="email" type="email" autoComplete="email" value={to} onChange={(e) => setTo(e.target.value)} autoFocus required />
          </label>
          {msg && (
            <p className={msg.ok ? "mk-small" : "mk-error"} role="alert">
              {msg.text}
            </p>
          )}
          <button type="submit" className="mk-btn mk-btn--accent mk-btn--lg mk-duo-accent" disabled={busy}>
            {a.sendHere}
          </button>
        </form>
      ) : (
        <form className="mk-form" onSubmit={confirm}>
          <p className="mk-small">{a.confirmText.replace("{to}", to)}</p>
          <label className="mk-field">
            <span>{a.emailCode}</span>
            <input
              name="one-time-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
              required
            />
          </label>
          {msg && (
            <p className={msg.ok ? "mk-small" : "mk-error"} role="alert">
              {msg.text}
            </p>
          )}
          <button type="submit" className="mk-btn mk-btn--accent mk-btn--lg mk-duo-accent" disabled={busy}>
            {a.confirm}
          </button>
          <p className="mk-small">
            <button type="button" className="mk-link" onClick={() => resend()}>
              {a.sendAgain}
            </button>
            {" · "}
            <button
              type="button"
              className="mk-link"
              onClick={() => {
                setMsg(null);
                setChanging(true);
              }}
            >
              {a.wrongAddress}
            </button>
          </p>
        </form>
      )}
    </div>
  );
}

/** Signing up: one trackerai account, with the trackers of choice. */
function SignUp({ locale, urls, onLogin }: { locale: Locale; urls: Partial<Record<BrandId, string>>; onLogin: () => void }) {
  const a = COPY[locale].account;
  const [mode, setMode] = useState<"open" | "invite" | "closed" | null>(null);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // An invitation link from the admin page: trackerai.nl/?invite=CODE#signup
  const [invite, setInvite] = useState(() =>
    typeof window === "undefined" ? "" : (new URLSearchParams(window.location.search).get("invite") ?? ""),
  );
  const [apps, setApps] = useState<BrandId[]>([]);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const linked = ORDER.filter((id) => urls[id]);

  useEffect(() => {
    fetch("/api/auth/registration-status", { credentials: "same-origin" })
      .then((r) => r.json())
      .then((s) => setMode(s.mode ?? "closed"))
      .catch(() => setMode("closed"));
  }, []);

  const toggle = (id: BrandId) => setApps((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const r = await post("/api/auth/register", {
        username,
        name,
        email,
        password,
        locale,
        apps,
        consent: apps.includes("health") && consent,
        invite_code: invite,
        app: apps.includes("wealth") ? "money" : "",
      });
      if (r.ok) await refresh();
      else setError(r.detail ?? a.failed);
    } catch {
      setError(a.failed);
    } finally {
      setBusy(false);
    }
  }

  if (mode === null) return <div className="mk-account" aria-busy="true" />;
  const back = (
    <p className="mk-small">
      <button type="button" className="mk-link" onClick={onLogin}>
        {a.haveAccount}
      </button>
    </p>
  );
  if (mode === "closed")
    return (
      <div className="mk-account">
        <p className="mk-small">{a.closed}</p>
        {back}
      </div>
    );

  return (
    <div className="mk-account">
      <p className="mk-account-who">{a.signup}</p>
      <form className="mk-form" onSubmit={submit}>
        <label className="mk-field">
          <span>{a.name}</span>
          <input name="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className="mk-field">
          <span>{a.username}</span>
          <input name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label className="mk-field">
          <span>{a.email}</span>
          <input name="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <small>{a.emailNote}</small>
        </label>
        <label className="mk-field">
          <span>{a.password}</span>
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {mode === "invite" && (
          <label className="mk-field">
            <span>{a.invite}</span>
            <input name="invite" value={invite} onChange={(e) => setInvite(e.target.value)} required />
          </label>
        )}
        <fieldset className="mk-field">
          <span>{a.choose}</span>
          {linked.map((id) => (
            <label key={id} className={`mk-check ${BRANDS[id].className}`}>
              <input type="checkbox" checked={apps.includes(id)} onChange={() => toggle(id)} />
              <span>{BRANDS[id].name}</span>
            </label>
          ))}
          <small>{a.chooseHint}</small>
        </fieldset>
        {apps.includes("health") && (
          <label className="mk-check mk-check--top">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>
              {a.consentBefore}
              <a href={`${urls.health}/privacy`} target="_blank" rel="noreferrer">
                {a.consentLink}
              </a>
              {a.consentAfter}
            </span>
          </label>
        )}
        {error && (
          <p className="mk-error" role="alert">
            {error}
          </p>
        )}
        <button
          type="submit"
          className="mk-btn mk-btn--accent mk-btn--lg mk-duo-accent"
          disabled={busy || apps.length === 0 || (apps.includes("health") && !consent)}
        >
          {busy ? a.working : a.create}
        </button>
      </form>
      {back}
    </div>
  );
}

/** The login form (or signing up), or, once logged in, a way into each tracker. */
export function AccountPanel({ locale, urls, days = 30 }: { locale: Locale; urls: Partial<Record<BrandId, string>>; days?: number }) {
  const c = COPY[locale];
  const a = c.account;
  const state = useAccount();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null); // codes by email: where the code went (masked)
  const [canEmail, setCanEmail] = useState(false);
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [signingUp, setSigningUp] = useState(false);
  // "Create an account" anywhere on the page links to #signup.
  useEffect(() => {
    const follow = () => {
      if (window.location.hash === "#signup") setSigningUp(true);
    };
    follow();
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  const linked = ORDER.filter((id) => urls[id]);
  const help = urls.health ?? urls.wealth;

  async function login(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const r = await post("/api/auth/login", { username, password, remember, ...(needsCode ? { totp: code } : {}) });
      if (r.ok) {
        await refresh();
        setPassword("");
        setCode("");
        setNeedsCode(false);
        setSentTo(null);
        setCanEmail(false);
      } else if (r.code === "totp_required") {
        setNeedsCode(true);
        setCanEmail(!!r.params?.email);
      } else if (r.code === "email_code_sent") {
        setNeedsCode(true);
        setSentTo(String(r.params?.to ?? ""));
      } else {
        setError(r.detail ?? a.failed);
      }
    } catch {
      setError(a.failed);
    } finally {
      setBusy(false);
    }
  }

  async function mailCode() {
    setError(null);
    const r = await post("/api/auth/login", { username, password, remember, send_email: true }).catch(() => ({ ok: false }) as const);
    if (!r.ok && "code" in r && r.code === "email_code_sent") setSentTo(String(r.params?.to ?? ""));
    else setError(("detail" in r && r.detail) || a.failed);
  }

  async function logout() {
    setError(null);
    const r = await post("/api/auth/logout", {}).catch(() => ({ ok: false, detail: undefined }));
    if (r.ok) publish({ status: "out" });
    else setError(r.detail ?? a.failed);
  }

  if (state.status === "loading") return <div className="mk-account" aria-busy="true" />;

  if (state.status === "in" && state.account.email_verify_required) return <ConfirmEmail locale={locale} account={state.account} />;

  if (state.status === "in") {
    const acc = state.account;
    return (
      <div className="mk-account">
        <p className="mk-account-who">{a.loggedIn.replace("{name}", acc.display_name || acc.username)}</p>
        <div className="mk-actions mk-actions--center">
          {linked.map((id) => {
            const Mark = MARK[id];
            const uses = acc.apps.includes(id);
            const label = (uses ? c.open : a.start).replace("{name}", BRANDS[id].name);
            return (
              <a
                key={id}
                href={`${urls[id]}/`}
                className={`mk-btn mk-btn--lg ${uses ? "mk-btn--accent" : "mk-btn--ghost"} ${BRANDS[id].className}`}
              >
                <Mark size={18} /> {label}
              </a>
            );
          })}
        </div>
        {error && (
          <p className="mk-error" role="alert">
            {error}
          </p>
        )}
        <p className="mk-small">
          {acc.is_admin && (
            <>
              <a href="/admin">{a.admin}</a>
              {" · "}
            </>
          )}
          <button type="button" className="mk-link" onClick={logout}>
            {a.logout}
          </button>
        </p>
      </div>
    );
  }

  if (signingUp) return <SignUp locale={locale} urls={urls} onLogin={() => setSigningUp(false)} />;

  return (
    <div className="mk-account">
      <form className="mk-form" onSubmit={login}>
        <label className="mk-field">
          <span>{a.username}</span>
          <input name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label className="mk-field">
          <span>{a.password}</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {needsCode && (
          <label className="mk-field">
            <span>{sentTo !== null ? a.emailCode : a.code}</span>
            <input
              name="one-time-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
              required
            />
            <small>
              {sentTo !== null ? a.emailHint.replace("{to}", sentTo) : a.codeHint}
              {(canEmail || sentTo !== null) && (
                <>
                  {" "}
                  <button type="button" className="mk-link" onClick={mailCode}>
                    {sentTo !== null ? a.emailAgain : a.emailInstead}
                  </button>
                </>
              )}
              {help && (
                <>
                  {" "}
                  <a href={`${help}/two-step`}>{a.twoStep}</a>
                </>
              )}
            </small>
          </label>
        )}
        <label className="mk-check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>{a.remember.replace("{days}", String(days))}</span>
        </label>
        {error && (
          <p className="mk-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="mk-btn mk-btn--accent mk-btn--lg mk-duo-accent" disabled={busy}>
          {busy ? a.working : a.submit}
        </button>
      </form>
      {linked.length > 0 && (
        <p className="mk-small">
          {a.noAccount}{" "}
          <button
            type="button"
            className="mk-link"
            onClick={() => {
              setError(null);
              setSigningUp(true);
            }}
          >
            {a.create}
          </button>
        </p>
      )}
    </div>
  );
}
