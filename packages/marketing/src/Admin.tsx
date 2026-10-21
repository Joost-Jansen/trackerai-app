"use client";

// The admin page of the trackers, in tabs (the tab is kept in the URL hash). What belongs to the shared account: the
// accounts and which trackers they use, two-step login, sign-up and invitations, and what admins did. And from each
// tracker: its beta features and disk use per account, its feedback, and a weekly figure for the charts.
//
// One page, two places. On trackerai.nl/admin it manages every tracker, through /api/hub/{app}/... (trackerai-api,
// app/hub.py). Inside a tracker (its own admin page, so a single self-hosted tracker has one too) it
// manages only that tracker, through the tracker's own /api. `trackers` says which trackers and where their API is;
// everything that lists trackers shows only those. The account part, /api/trackerai/admin/* (packages/accounts), is
// answered the same by every tracker. A tracker that is not connected or does not answer gets a quiet note.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BRANDS, type BrandId, type Locale } from "./brands";
import { ADMIN_COPY, type FeedbackStatus } from "./adminCopy";
import { AccountPanel } from "./Account";
import { HealthMark, TrackerAIMark, WealthMark } from "./marks";
import { lastWeeks, weekIndex, WeekChart } from "./AdminChart";

type Account = {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
  email_verified: boolean;
  is_admin: boolean;
  apps: string[];
  app_admin: string[];
  totp_enabled: boolean;
  email_codes: boolean;
  suspended: boolean;
  created_at: string | null;
  last_login_at: string | null;
};
type Invite = {
  code: string;
  created_at: string | null;
  expires_at: string | null;
  used_by: number | null;
  used_at: string | null;
  apps: string[] | null;
};
type Audit = { id: number; at: string | null; actor: string; action: string; target: string | null; detail: string | null };
type Registration = {
  registration: "open" | "invite" | "closed";
  invites: Invite[];
  audit: Audit[];
  settings: { require_totp: string; email: boolean; session_days: number };
};
type Me = { id: number; username: string; is_admin: boolean };
/** Page visits per day, app and account (packages/accounts): per week, and who was active. */
type Usage = {
  weeks: string[];
  apps: Partial<Record<BrandId, { visits: number[]; users: number[] }>>;
  active_7: number;
  active_30: number;
  last_seen: Record<string, string>;
};

type Text = { en: string; nl: string };
type TrackerAccount = { account_id: number; betas: string[]; count: number; last_at: string | null; disk_bytes?: number | null };
type Tracker = {
  app: BrandId;
  betas: { id: string; name: Text }[];
  measure: Text;
  accounts: TrackerAccount[];
  disk_bytes_total?: number | null;
  /** Key figures a tracker wants to show of itself (health-tracker: how its photo analysis does), as tiles. */
  facts?: { label: Text; value: string; note?: Text | null }[];
};
type Feedback = {
  id: number;
  app: BrandId;
  kind: "bug" | "idea";
  message: string;
  page: string | null;
  context: {
    browser?: string;
    screen?: string;
    language?: string;
    theme?: string;
    version?: string | null;
    errors?: { message: string; where?: string }[];
  } | null;
  status: FeedbackStatus;
  reply: string | null;
  created_at: string;
  updated_at: string | null;
  account_id: number | null;
  username: string | null;
  has_screenshot: boolean;
};
/** What one tracker answered: its data, not connected here (503 not_configured), or an error. */
type Hub<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "off" } | { state: "error"; text: string };
type PerApp<T> = Partial<Record<BrandId, Hub<T>>>;
type Bases = Partial<Record<BrandId, string>>;
type Save = (f: Feedback, change: { status: FeedbackStatus; reply: string }) => Promise<void>;
type SetBeta = (app: BrandId, accountId: number, feature: string, enabled: boolean) => Promise<void>;
type Act = (f: () => Promise<unknown>, done?: string) => Promise<void>;

export type AdminProps = {
  locale: Locale;
  /** The trackers this page manages, each with the base of its API: `{ health: "/api/hub/health", wealth: "/api/hub/wealth" }`
   *  on trackerai.nl, `{ wealth: "/api" }` inside wealth-tracker. */
  trackers: Bases;
  /** Inside a tracker: no trackerai.nl top bar (the app's own layout is around it), invitations point at the app's
   *  register page, and with `frontDoor` a quiet link to the page for all trackers. */
  inApp?: boolean;
  /** The front door's address (e.g. https://trackerai.nl), when this installation has one. */
  frontDoor?: string | null;
  /** Inside a tracker: the address of its register page, for invitation links. Default "/register". */
  registerPath?: string;
  /** Where each tracker lives, for the login panel on the front door. */
  urls?: Partial<Record<BrandId, string>>;
};

const API = "/api/trackerai/admin";
const ORDER: BrandId[] = ["health", "wealth"];
const MARK = { health: HealthMark, wealth: WealthMark };
const COLOR: Record<BrandId, string> = { health: "var(--ad-health)", wealth: "var(--ad-wealth)" };
const DAY = 86_400_000;
const TABS = ["overview", "accounts", "feedback", "signup", "activity"] as const;
type Tab = (typeof TABS)[number];
const STATUSES: FeedbackStatus[] = ["new", "planned", "fixed", "wontfix"];
const isOpen = (f: Feedback) => f.status === "new" || f.status === "planned";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `${r.status}`);
  return data as T;
}

async function hubLoad<T>(url: string, pick: (data: unknown) => T): Promise<Hub<T>> {
  try {
    return { state: "ok", data: pick(await call<unknown>("GET", url)) };
  } catch (e) {
    const text = (e as Error).message;
    return text === "not_configured" ? { state: "off" } : { state: "error", text };
  }
}

const parse = (value: string) =>
  new Date(
    /^\d{4}-\d\d-\d\d$/.test(value) ? `${value}T00:00:00Z` : value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`,
  );
const intl = (locale: Locale) => (locale === "nl" ? "nl-NL" : "en-GB");

function when(value: string | null, locale: Locale): string {
  if (!value) return "—";
  return parse(value).toLocaleDateString(intl(locale), { day: "numeric", month: "short", year: "numeric" });
}

function whenTime(value: string, locale: Locale): string {
  return parse(value).toLocaleString(intl(locale), { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function since(value: string | null, days: number): boolean {
  if (!value) return false;
  return Date.now() - parse(value).getTime() < days * DAY;
}

/** 0 B, 840 KB, 12 MB, 1.4 GB. */
function bytes(n: number, locale: Locale): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  const digits = i > 0 && v < 10 ? 1 : 0;
  return `${v.toLocaleString(intl(locale), { maximumFractionDigits: digits })} ${units[i]}`;
}

export default function Admin({
  locale,
  trackers: bases,
  inApp = false,
  frontDoor = null,
  registerPath = "/register",
  urls = {},
}: AdminProps) {
  const c = ADMIN_COPY[locale];
  // The trackers this page manages, in the usual order. A stable key, so the loaders below don't rerun on every render.
  const appsKey = new URLSearchParams(ORDER.flatMap((id) => (bases[id] ? [[id, bases[id]!.replace(/\/+$/, "")]] : []))).toString();
  const apps = useMemo(() => ORDER.filter((id) => new URLSearchParams(appsKey).has(id)), [appsKey]);
  const base = useCallback((app: BrandId) => new URLSearchParams(appsKey).get(app) ?? `/api/hub/${app}`, [appsKey]);
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [list, setList] = useState<Account[] | null>(null);
  const [reg, setReg] = useState<Registration | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [trackers, setTrackers] = useState<PerApp<Tracker>>({});
  const [feedback, setFeedback] = useState<PerApp<Feedback[]>>({});

  // The tab lives in the hash (#feedback), so a reload or a shared link opens the same one.
  useEffect(() => {
    const read = () => {
      const h = window.location.hash.slice(1);
      setTab((TABS as readonly string[]).includes(h) ? (h as Tab) : "overview");
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  const choose = (t: Tab) => {
    setTab(t);
    history.replaceState(history.state, "", t === "overview" ? window.location.pathname + window.location.search : `#${t}`);
  };

  const load = useCallback(async () => {
    try {
      const [a, r] = await Promise.all([call<Account[]>("GET", `${API}/accounts`), call<Registration>("GET", `${API}/registration`)]);
      setList(a);
      setReg(r);
      // Before the accounts counted visits there is nothing to show: the page does without.
      setUsage(await call<Usage>("GET", `${API}/usage`).catch(() => null));
    } catch (e) {
      setNotice({ ok: false, text: (e as Error).message });
    }
  }, []);

  const loadHub = useCallback(async () => {
    await Promise.all(
      apps.map(async (app) => {
        const [t, f] = await Promise.all([
          hubLoad<Tracker>(`${base(app)}/admin/tracker`, (d) => d as Tracker),
          // A list, or { feedback: [...] } as wealth-tracker answered before: both are fine.
          hubLoad<Feedback[]>(`${base(app)}/admin/feedback`, (d) =>
            ((Array.isArray(d) ? d : ((d as { feedback?: Feedback[] }).feedback ?? [])) as Feedback[]).map((x) => ({ ...x, app })),
          ),
        ]);
        setTrackers((now) => ({ ...now, [app]: t }));
        setFeedback((now) => ({ ...now, [app]: f }));
      }),
    );
  }, [apps, base]);

  useEffect(() => {
    call<Me>("GET", "/api/auth/account")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (me?.is_admin) {
      load();
      loadHub();
    }
  }, [me, load, loadHub]);

  /** Runs an action, says how it went, and reloads. */
  const act = useCallback<Act>(
    async (f, done) => {
      setNotice(null);
      try {
        await f();
        if (done) setNotice({ ok: true, text: done });
        await load();
      } catch (e) {
        setNotice({ ok: false, text: (e as Error).message });
      }
    },
    [load],
  );

  /** After a batch: one summary, and everything reloaded (counts, betas and trackers may have changed). */
  const finished = useCallback(
    async (text: string, ok: boolean) => {
      setNotice({ ok, text });
      await Promise.all([load(), loadHub()]);
    },
    [load, loadHub],
  );

  const setBeta = useCallback<SetBeta>(
    async (app, accountId, feature, enabled) => {
      const entry = await call<TrackerAccount>("PATCH", `${base(app)}/admin/tracker/betas/${accountId}`, { feature, enabled });
      setTrackers((now) => {
        const t = now[app];
        if (t?.state !== "ok") return now;
        const accounts = t.data.accounts.map((x) => (x.account_id === accountId ? { ...x, ...entry } : x));
        return { ...now, [app]: { state: "ok", data: { ...t.data, accounts } } };
      });
    },
    [base],
  );

  const saveFeedback = useCallback<Save>(
    async (f, change) => {
      const r = await call<Partial<Feedback> | null>("PATCH", `${base(f.app)}/admin/feedback/${f.id}`, change);
      setFeedback((now) => {
        const h = now[f.app];
        if (h?.state !== "ok") return now;
        const data = h.data.map((x) => (x.id === f.id ? { ...x, ...change, ...(r && r.id === f.id ? r : {}), app: f.app } : x));
        return { ...now, [f.app]: { state: "ok", data } };
      });
    },
    [base],
  );

  const allFeedback = useMemo(
    () =>
      apps
        .flatMap((app) => {
          const h = feedback[app];
          return h?.state === "ok" ? h.data : [];
        })
        .sort((a, b) => parse(b.created_at).getTime() - parse(a.created_at).getTime()),
    [apps, feedback],
  );
  const openCount = allFeedback.filter(isOpen).length;
  const shot = useCallback((f: Feedback) => `${base(f.app)}/feedback/${f.id}/screenshot`, [base]);

  let body: React.ReactNode;
  if (me === undefined) body = <p className="mk-ad-muted">{c.loading}</p>;
  else if (me === null) {
    body = inApp ? (
      <p className="mk-ad-muted">{c.loginFirst}</p>
    ) : (
      <div className="mk-ad-login">
        <p>{c.loginFirst}</p>
        <AccountPanel locale={locale} urls={urls} />
      </div>
    );
  } else if (!me.is_admin) body = <p className="mk-ad-muted">{c.adminsOnly}</p>;
  else if (!list || !reg) body = <p className="mk-ad-muted">{notice?.text ?? c.loading}</p>;
  else
    body = (
      <>
        <nav className="mk-ad-tabs mk-ad-row" role="tablist" aria-label={c.title}>
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              id={`mk-ad-tab-${t}`}
              aria-selected={tab === t}
              aria-controls="mk-ad-panel"
              className={`mk-ad-seg ${tab === t ? "mk-ad-seg--on" : ""}`}
              onClick={() => choose(t)}
            >
              {c.tabs[t]}
              {t === "feedback" && openCount > 0 && <span className="mk-ad-count">{openCount}</span>}
            </button>
          ))}
        </nav>
        {notice && (
          <p className={notice.ok ? "mk-ad-notice" : "mk-ad-notice mk-ad-notice--bad"} role="status">
            {notice.text}
          </p>
        )}
        <div id="mk-ad-panel" role="tabpanel" aria-labelledby={`mk-ad-tab-${tab}`} className="mk-ad-panel">
          {tab === "overview" && (
            <>
              <Overview locale={locale} apps={apps} list={list} reg={reg} trackers={trackers} usage={usage} />
              <Charts locale={locale} apps={apps} list={list} trackers={trackers} feedback={feedback} usage={usage} />
            </>
          )}
          {tab === "accounts" && (
            <Accounts
              locale={locale}
              apps={apps}
              list={list}
              me={me}
              act={act}
              finished={finished}
              trackers={trackers}
              setBeta={setBeta}
              base={base}
              lastSeen={usage?.last_seen ?? {}}
            />
          )}
          {tab === "feedback" && (
            <FeedbackTab locale={locale} apps={apps} items={allFeedback} feedback={feedback} save={saveFeedback} shot={shot} />
          )}
          {tab === "signup" && <SignUp locale={locale} apps={apps} reg={reg} act={act} inApp={inApp} registerPath={registerPath} />}
          {tab === "activity" && <Activity locale={locale} audit={reg.audit} />}
        </div>
      </>
    );

  if (inApp) {
    let away: string | null = null;
    if (frontDoor) {
      try {
        away = new URL(frontDoor).host;
      } catch {
        away = null;
      }
    }
    return (
      <div className="mk-ad mk-ad--app">
        <div className="mk-ad-main">
          {away && (
            <p className="mk-ad-away">
              <a href={`${frontDoor!.replace(/\/+$/, "")}/admin`}>{c.allTrackers(`${away}/admin`)}</a>
            </p>
          )}
          {body}
        </div>
      </div>
    );
  }
  return (
    <div className="mk-ad">
      <header className="mk-ad-top">
        <a href="/" className="mk-brand">
          <TrackerAIMark size={20} />
          <span>trackerai</span>
        </a>
        <span className="mk-ad-title">{c.title}</span>
        <a href="/" className="mk-ad-back">
          {c.back}
        </a>
      </header>
      <main className="mk-ad-main">{body}</main>
    </div>
  );
}

/** A quiet line for a tracker that is not connected here or did not answer; nothing when it did. */
function HubNote<T>({ locale, app, hub }: { locale: Locale; app: BrandId; hub: Hub<T> | undefined }) {
  const c = ADMIN_COPY[locale];
  if (hub?.state === "off") return <p className="mk-ad-muted">{c.hub.notConnected(BRANDS[app].name)}</p>;
  if (hub?.state === "error")
    return (
      <p className="mk-ad-muted">
        {c.hub.failed(BRANDS[app].name)} ({hub.text})
      </p>
    );
  return null;
}

function Overview({
  locale,
  apps,
  list,
  reg,
  trackers,
  usage,
}: {
  locale: Locale;
  apps: BrandId[];
  list: Account[];
  reg: Registration;
  trackers: PerApp<Tracker>;
  usage: Usage | null;
}) {
  const c = ADMIN_COPY[locale];
  const n = list.length;
  // Disk use: what each tracker reports, when it reports it.
  const disk = apps.flatMap((app) => {
    const h = trackers[app];
    const total = h?.state === "ok" ? h.data.disk_bytes_total : null;
    return typeof total === "number" ? [{ app, total }] : [];
  });
  const tiles: { label: string; value: string; hint?: string }[] = [
    { label: c.tiles.accounts, value: String(n), hint: c.tiles.newIn30(list.filter((a) => since(a.created_at, 30)).length) },
    ...apps.map((id) => ({ label: BRANDS[id].name, value: String(list.filter((a) => a.apps.includes(id)).length), hint: c.tiles.users })),
    usage
      ? { label: c.tiles.active, value: String(usage.active_7), hint: c.tiles.used7(usage.active_30) }
      : { label: c.tiles.active, value: String(list.filter((a) => since(a.last_login_at, 7)).length), hint: c.tiles.last7 },
    {
      label: c.tiles.twoStep,
      value: `${list.filter((a) => a.totp_enabled || a.email_codes).length} / ${n}`,
      hint: c.tiles.twoStepSplit(list.filter((a) => a.totp_enabled).length, list.filter((a) => a.email_codes).length),
    },
    {
      label: c.tiles.attention,
      value: String(list.filter((a) => a.suspended || (a.email && !a.email_verified)).length),
      hint: c.tiles.attentionSplit(list.filter((a) => a.suspended).length, list.filter((a) => a.email && !a.email_verified).length),
    },
    ...(disk.length
      ? [
          {
            label: c.tiles.disk,
            value: bytes(
              disk.reduce((s, d) => s + d.total, 0),
              locale,
            ),
            hint: disk.length > 1 ? disk.map((d) => `${BRANDS[d.app].name} ${bytes(d.total, locale)}`).join(" · ") : undefined,
          },
        ]
      : []),
  ];
  const s = reg.settings;
  return (
    <section className="mk-ad-section">
      <div className="mk-ad-tiles">
        {tiles.map((t) => (
          <div key={t.label} className="mk-ad-tile">
            <span className="mk-ad-tile-label">{t.label}</span>
            <span className="mk-ad-tile-value">{t.value}</span>
            {t.hint && <span className="mk-ad-muted">{t.hint}</span>}
          </div>
        ))}
      </div>
      {apps.map((app) => {
        const h = trackers[app];
        const facts = h?.state === "ok" ? (h.data.facts ?? []) : [];
        if (!facts.length) return null;
        return (
          <div key={`facts-${app}`}>
            <p className="mk-ad-muted">{BRANDS[app].name}</p>
            <div className="mk-ad-tiles">
              {facts.map((f) => (
                <div key={f.label.en} className="mk-ad-tile">
                  <span className="mk-ad-tile-label">{f.label[locale]}</span>
                  <span className="mk-ad-tile-value">{f.value}</span>
                  {f.note && <span className="mk-ad-muted">{f.note[locale]}</span>}
                </div>
              ))}
            </div>
          </div>
        );
      })}
      <p className="mk-ad-settings">
        {c.settings.signup}: <b>{c.modes[reg.registration]}</b> · {c.settings.policy}: <b>{c.policies[s.require_totp] ?? s.require_totp}</b>{" "}
        · {c.settings.mail}: <b>{s.email ? c.on : c.off}</b> · {c.settings.stay}: <b>{c.days(s.session_days)}</b>
      </p>
      {!s.email && <p className="mk-ad-muted">{c.settings.mailOff}</p>}
    </section>
  );
}

/** A few small charts over the last 12 weeks: accounts, page visits and active users per tracker, and feedback. */
function Charts({
  locale,
  apps,
  list,
  trackers,
  feedback,
  usage,
}: {
  locale: Locale;
  apps: BrandId[];
  list: Account[];
  trackers: PerApp<Tracker>;
  feedback: PerApp<Feedback[]>;
  usage: Usage | null;
}) {
  const c = ADMIN_COPY[locale];
  const weeks = useMemo(() => lastWeeks(12), []);
  const start = Date.parse(`${weeks[0]}T00:00:00Z`);
  const added = weeks.map(() => 0);
  let before = 0;
  for (const a of list) {
    const i = weekIndex(weeks, a.created_at);
    if (i >= 0) added[i] += 1;
    else if (!a.created_at || parse(a.created_at).getTime() < start) before += 1;
  }
  const total = added.map((_, i) => before + added.slice(0, i + 1).reduce((s, x) => s + x, 0));
  const fbSeries = apps
    .filter((app) => feedback[app]?.state === "ok")
    .map((app) => {
      const h = feedback[app];
      const values = weeks.map(() => 0);
      if (h?.state === "ok")
        for (const f of h.data) {
          const i = weekIndex(weeks, f.created_at);
          if (i >= 0) values[i] += 1;
        }
      return { id: app, label: BRANDS[app].name, color: COLOR[app], values };
    });
  // The accounts' weeks are the server's (UTC Mondays); match them by date.
  const used = (key: "visits" | "users") =>
    usage
      ? apps.map((app) => {
          const at = new Map(usage.weeks.map((w, i) => [w, usage.apps[app]?.[key][i] ?? 0]));
          return { id: app, label: BRANDS[app].name, color: COLOR[app], values: weeks.map((w) => at.get(w) ?? 0) };
        })
      : [];

  return (
    <section className="mk-ad-section">
      <div className="mk-ad-charts">
        <WeekChart
          title={c.charts.accounts}
          weeks={weeks}
          kind="line"
          locale={locale}
          series={[{ id: "accounts", label: c.charts.accounts.toLowerCase(), color: "var(--ad-series)", values: total }]}
          extra={(i) => (added[i] ? c.charts.newTip(added[i]) : null)}
        />
        {usage && (
          <WeekChart title={c.charts.visits} weeks={weeks} kind="bars" locale={locale} series={used("visits")} empty={c.charts.none} />
        )}
        {usage && (
          <WeekChart title={c.charts.users} weeks={weeks} kind="line" locale={locale} series={used("users")} empty={c.charts.none} />
        )}
        {fbSeries.length > 0 && (
          <WeekChart title={c.charts.feedback} weeks={weeks} kind="bars" locale={locale} series={fbSeries} empty={c.charts.none} />
        )}
      </div>
      {apps.map((app) => (
        <HubNote key={app} locale={locale} app={app} hub={trackers[app]} />
      ))}
    </section>
  );
}

/** A button with a menu. The menu floats over the page (fixed, from the button's place), opens upward when there is
 *  no room below, follows the button when the page scrolls, and closes on a click elsewhere, Escape or resizing. */
function RowMenu({
  label,
  ariaLabel,
  align = "right",
  disabled,
  children,
}: {
  label: string;
  ariaLabel?: string;
  align?: "left" | "right";
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [root, setRoot] = useState<Element | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const items = () => [...(menu.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? [])];
  const close = useCallback((focus = false) => {
    setOpen(false);
    setPos(null);
    if (focus) btn.current?.focus();
  }, []);

  const place = useCallback(() => {
    if (!btn.current || !menu.current) return;
    const b = btn.current.getBoundingClientRect();
    const h = menu.current.offsetHeight;
    const w = menu.current.offsetWidth;
    const below = window.innerHeight - b.bottom;
    const up = below < h + 8 && b.top > below;
    const top = up ? Math.max(8, b.top - h - 4) : b.bottom + 4;
    const left = Math.min(Math.max(8, align === "left" ? b.left : b.right - w), window.innerWidth - w - 8);
    setPos((now) => (now && now.top === top && now.left === left ? now : { top, left }));
    return b.bottom > 0 && b.top < window.innerHeight;
  }, [align]);
  useLayoutEffect(() => {
    if (open) place();
  }, [open, root, place]);
  // Once it is placed (and visible), the first item gets the focus.
  const focused = useRef(false);
  useEffect(() => {
    if (pos && !focused.current) items()[0]?.focus({ preventScroll: true });
    focused.current = !!pos;
  }, [pos]);

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!menu.current?.contains(t) && !btn.current?.contains(t)) close();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(true);
    };
    // Scrolling the page keeps the menu with its button, until the button is out of sight.
    const scroll = (e: Event) => {
      if (!menu.current?.contains(e.target as Node) && !place()) close();
    };
    const resize = () => close();
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", resize);
    };
  }, [open, close, place]);

  const onKey = (e: React.KeyboardEvent) => {
    const list = items();
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    const go = (j: number) => {
      e.preventDefault();
      list[(j + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(list.length - 1);
    else if (e.key === "Tab") close();
  };

  return (
    <>
      <button
        ref={btn}
        type="button"
        className="mk-ad-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => {
          if (open) return close();
          // Into the page's root rather than the table cell: no overflow or row opacity reaches it, the colours do.
          setRoot(btn.current?.closest(".mk-ad") ?? document.body);
          setOpen(true);
        }}
      >
        {label}
      </button>
      {open &&
        root &&
        createPortal(
          <div
            ref={menu}
            className="mk-ad-menu"
            role="menu"
            onKeyDown={onKey}
            onClick={() => close(true)}
            style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden" }}
          >
            {children}
          </div>,
          root,
        )}
    </>
  );
}

/** What a batch does, for each selected account. */
type Bulk =
  | { kind: "admin"; on: boolean }
  | { kind: "suspend"; on: boolean }
  | { kind: "app"; app: BrandId; on: boolean }
  | { kind: "beta"; app: BrandId; feature: string; on: boolean }
  | { kind: "twoStep" }
  | { kind: "delete" };
/** Never to your own account: you'd lock yourself out. */
const notSelf = (b: Bulk) => b.kind === "admin" || b.kind === "suspend" || b.kind === "delete";

function Accounts({
  locale,
  apps,
  list,
  me,
  act,
  finished,
  trackers,
  setBeta,
  base,
  lastSeen,
}: {
  locale: Locale;
  apps: BrandId[];
  list: Account[];
  me: Me;
  act: Act;
  finished: (text: string, ok: boolean) => Promise<void>;
  trackers: PerApp<Tracker>;
  setBeta: SetBeta;
  base: (app: BrandId) => string;
  lastSeen: Record<string, string>;
}) {
  const c = ADMIN_COPY[locale];
  const b = c.bulk;
  const [q, setQ] = useState("");
  const [betaFor, setBetaFor] = useState<number | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [ask, setAsk] = useState<Bulk | "beta" | null>(null);
  const [progress, setProgress] = useState<{ done: number; of: number } | null>(null);
  const all = useRef<HTMLInputElement>(null);
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? list.filter((a) => [a.username, a.display_name, a.email].some((v) => v?.toLowerCase().includes(s))) : list;
  }, [list, q]);
  // Only accounts that still exist stay selected (after a reload or a delete).
  useEffect(() => {
    setPicked((now) => {
      const ids = new Set(list.map((a) => a.id));
      const kept = [...now].filter((id) => ids.has(id));
      return kept.length === now.size ? now : new Set(kept);
    });
  }, [list]);
  const chosen = list.filter((a) => picked.has(a.id));
  const shownPicked = shown.filter((a) => picked.has(a.id)).length;
  const allShown = shown.length > 0 && shownPicked === shown.length;
  useEffect(() => {
    if (all.current) all.current.indeterminate = shownPicked > 0 && !allShown;
  }, [shownPicked, allShown]);
  const pick = (ids: number[], on: boolean) =>
    setPicked((now) => {
      const next = new Set(now);
      for (const id of ids)
        if (on) next.add(id);
        else next.delete(id);
      return next;
    });

  const twoStep = (a: Account) =>
    a.totp_enabled && a.email_codes ? c.twoStep.both : a.totp_enabled ? c.twoStep.app : a.email_codes ? c.twoStep.email : c.twoStep.off;
  const counted = (app: BrandId, id: number) => {
    const h = trackers[app];
    if (h?.state !== "ok") return null;
    const e = h.data.accounts.find((x) => x.account_id === id);
    if (!e) return null;
    const count = `${e.count.toLocaleString(intl(locale))} ${h.data.measure[locale]}`;
    return typeof e.disk_bytes === "number" ? `${count} · ${bytes(e.disk_bytes, locale)}` : count;
  };
  const betaAccount = list.find((a) => a.id === betaFor);
  const betaApps = apps.filter((app) => {
    const h = trackers[app];
    return h?.state === "ok" && h.data.betas.length > 0;
  });

  /** Whether the batch changes anything for this account; one that is already so counts as done. */
  const needs = (x: Bulk, a: Account): boolean => {
    switch (x.kind) {
      case "admin":
        return a.is_admin !== x.on;
      case "suspend":
        return a.suspended !== x.on;
      case "app":
        return a.apps.includes(x.app) !== x.on;
      case "twoStep":
        return a.totp_enabled || a.email_codes;
      case "delete":
        return true;
      case "beta": {
        const h = trackers[x.app];
        const e = h?.state === "ok" ? h.data.accounts.find((y) => y.account_id === a.id) : undefined;
        return !e || e.betas.includes(x.feature) !== x.on;
      }
    }
  };
  const step = (x: Bulk, a: Account): Promise<unknown> => {
    switch (x.kind) {
      case "admin":
        return call("PATCH", `${API}/accounts/${a.id}`, { is_admin: x.on });
      case "suspend":
        return call("PATCH", `${API}/accounts/${a.id}`, { suspended: x.on });
      case "app":
        return call("PATCH", `${API}/accounts/${a.id}/apps/${x.app}`, { enabled: x.on });
      case "twoStep":
        return call("DELETE", `${API}/accounts/${a.id}/totp`);
      case "delete":
        return call("DELETE", `${API}/accounts/${a.id}?confirm=${encodeURIComponent(a.username)}`);
      case "beta": {
        const h = trackers[x.app];
        const there = h?.state === "ok" && h.data.accounts.some((y) => y.account_id === a.id);
        if (!there) return Promise.reject(new Error(b.notIn(BRANDS[x.app].name)));
        return call("PATCH", `${base(x.app)}/admin/tracker/betas/${a.id}`, { feature: x.feature, enabled: x.on });
      }
    }
  };
  const selfIn = (x: Bulk) => notSelf(x) && picked.has(me.id);
  const targets = (x: Bulk) => chosen.filter((a) => !(notSelf(x) && a.id === me.id));

  /** One by one, so the trackers and the audit log see ordinary single actions; then one summary. */
  async function run(x: Bulk) {
    setAsk(null);
    const todo = targets(x);
    const skipped = selfIn(x) ? ` ${b.selfSkipped}` : "";
    if (todo.length === 0) {
      await finished(b.onlySelf, false);
      return;
    }
    let ok = 0;
    const failed: string[] = [];
    setProgress({ done: 0, of: todo.length });
    for (const [i, a] of todo.entries()) {
      try {
        if (needs(x, a)) await step(x, a);
        ok += 1;
      } catch (e) {
        failed.push(`@${a.username} (${(e as Error).message})`);
      }
      setProgress({ done: i + 1, of: todo.length });
    }
    setProgress(null);
    setPicked(new Set());
    await finished(`${b.summary(ok, todo.length, failed)}${skipped}`, failed.length === 0);
  }
  /** The destructive ones are confirmed once, for the whole batch; the rest runs straight away. */
  const start = (x: Bulk) => {
    if (x.kind === "delete" || x.kind === "twoStep" || (x.kind === "suspend" && x.on) || (x.kind === "app" && !x.on)) setAsk(x);
    else run(x);
  };
  const busy = progress !== null;

  return (
    <section className="mk-ad-section">
      <div className="mk-ad-head">
        <h2>{c.accounts.title}</h2>
        <input
          className="mk-ad-search"
          type="search"
          placeholder={c.accounts.search}
          aria-label={c.accounts.search}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      {(picked.size > 0 || busy) && (
        <div className="mk-ad-bulk" role="region" aria-label={b.label}>
          <span aria-live="polite">{busy ? b.working(progress.done, progress.of) : b.selected(picked.size)}</span>
          <RowMenu label={b.actions} align="left" disabled={busy}>
            <button type="button" role="menuitem" onClick={() => start({ kind: "admin", on: true })}>
              {c.menu.makeAdmin}
            </button>
            <button type="button" role="menuitem" onClick={() => start({ kind: "admin", on: false })}>
              {c.menu.removeAdmin}
            </button>
            <button type="button" role="menuitem" onClick={() => start({ kind: "suspend", on: true })}>
              {b.suspend}
            </button>
            <button type="button" role="menuitem" onClick={() => start({ kind: "suspend", on: false })}>
              {c.menu.unsuspend}
            </button>
            {apps.map((id) => (
              <button key={`give-${id}`} type="button" role="menuitem" onClick={() => start({ kind: "app", app: id, on: true })}>
                {c.menu.give(BRANDS[id].name)}
              </button>
            ))}
            {apps.map((id) => (
              <button key={`take-${id}`} type="button" role="menuitem" onClick={() => start({ kind: "app", app: id, on: false })}>
                {c.menu.take(BRANDS[id].name)}
              </button>
            ))}
            {betaApps.length > 0 && (
              <button type="button" role="menuitem" onClick={() => setAsk("beta")}>
                {c.betas.menu}
              </button>
            )}
            <button type="button" role="menuitem" onClick={() => start({ kind: "twoStep" })}>
              {c.menu.twoStepOff}
            </button>
            <button type="button" role="menuitem" className="mk-ad-danger" onClick={() => start({ kind: "delete" })}>
              {b.delete}
            </button>
          </RowMenu>
          <button type="button" className="mk-ad-btn mk-ad-btn--quiet" disabled={busy} onClick={() => setPicked(new Set())}>
            {b.clear}
          </button>
        </div>
      )}
      <div className="mk-ad-table-wrap">
        <table className="mk-ad-table">
          <thead>
            <tr>
              <th className="mk-ad-pick">
                <input
                  ref={all}
                  type="checkbox"
                  aria-label={b.pickAll}
                  checked={allShown}
                  disabled={shown.length === 0 || busy}
                  onChange={(e) =>
                    pick(
                      shown.map((a) => a.id),
                      e.target.checked,
                    )
                  }
                />
              </th>
              <th>{c.accounts.who}</th>
              <th>{c.accounts.email}</th>
              <th>{c.accounts.trackers}</th>
              <th>{c.accounts.twoStep}</th>
              <th>{c.accounts.lastActive}</th>
              <th aria-label={c.accounts.actions} />
            </tr>
          </thead>
          <tbody>
            {shown.map((a) => {
              const others = a.apps.filter((x) => !apps.includes(x as BrandId)).map((x) => BRANDS[x as BrandId]?.name ?? x);
              return (
                <tr
                  key={a.id}
                  className={
                    [a.suspended ? "mk-ad-row--off" : "", picked.has(a.id) ? "mk-ad-row--picked" : ""].join(" ").trim() || undefined
                  }
                >
                  <td className="mk-ad-pick">
                    <input
                      type="checkbox"
                      aria-label={b.pick(a.username)}
                      checked={picked.has(a.id)}
                      disabled={busy}
                      onChange={(e) => pick([a.id], e.target.checked)}
                    />
                  </td>
                  <td>
                    <b>{a.display_name || a.username}</b>
                    <span className="mk-ad-muted"> @{a.username}</span>
                    {a.is_admin && <span className="mk-ad-chip">{c.accounts.admin}</span>}
                    {a.suspended && <span className="mk-ad-chip mk-ad-chip--bad">{c.accounts.suspended}</span>}
                    <div className="mk-ad-muted mk-ad-since">{c.accounts.since(when(a.created_at, locale))}</div>
                  </td>
                  <td>
                    {a.email ?? <span className="mk-ad-muted">—</span>}
                    {a.email && !a.email_verified && <div className="mk-ad-chip mk-ad-chip--warn">{c.accounts.unconfirmed}</div>}
                  </td>
                  <td>
                    {apps.map((id) => {
                      const Mark = MARK[id];
                      const on = a.apps.includes(id);
                      const count = on ? counted(id, a.id) : null;
                      return (
                        <div key={id} className="mk-ad-app-line">
                          <span className={`mk-ad-app ${on ? "" : "mk-ad-app--off"}`} title={BRANDS[id].name}>
                            <Mark size={14} /> {on ? BRANDS[id].name : <s>{BRANDS[id].name}</s>}
                            {a.app_admin.includes(id) && <small> ({c.accounts.appAdmin})</small>}
                          </span>
                          {count && <span className="mk-ad-muted mk-ad-app-count">{count}</span>}
                        </div>
                      );
                    })}
                    {others.length > 0 && <div className="mk-ad-muted">{c.accounts.also(others.join(", "))}</div>}
                  </td>
                  <td className="mk-ad-nowrap">{twoStep(a)}</td>
                  <td className="mk-ad-nowrap">{when(lastSeen[String(a.id)] ?? a.last_login_at, locale)}</td>
                  <td className="mk-ad-actions-cell">
                    <RowMenu label={c.accounts.manage} ariaLabel={c.accounts.manageFor(a.username)}>
                      {a.id !== me.id && (
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => act(() => call("PATCH", `${API}/accounts/${a.id}`, { is_admin: !a.is_admin }), c.done)}
                        >
                          {a.is_admin ? c.menu.removeAdmin : c.menu.makeAdmin}
                        </button>
                      )}
                      {a.id !== me.id && (
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            if (a.suspended || confirm(c.menu.suspendConfirm(a.username)))
                              act(() => call("PATCH", `${API}/accounts/${a.id}`, { suspended: !a.suspended }), c.done);
                          }}
                        >
                          {a.suspended ? c.menu.unsuspend : c.menu.suspend}
                        </button>
                      )}
                      {apps.some((id) => a.apps.includes(id)) && (
                        <button type="button" role="menuitem" onClick={() => setBetaFor(a.id)}>
                          {c.betas.menu}
                        </button>
                      )}
                      {apps.map((id) => {
                        const on = a.apps.includes(id);
                        return (
                          <button
                            key={id}
                            type="button"
                            role="menuitem"
                            onClick={() => {
                              if (on && !confirm(c.menu.takeConfirm(a.username, BRANDS[id].name))) return;
                              act(() => call("PATCH", `${API}/accounts/${a.id}/apps/${id}`, { enabled: !on }), c.done);
                            }}
                          >
                            {(on ? c.menu.take : c.menu.give)(BRANDS[id].name)}
                          </button>
                        );
                      })}
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          if (!confirm(c.menu.resetConfirm(a.username))) return;
                          act(async () => {
                            const r = await call<{ password: string }>("POST", `${API}/accounts/${a.id}/reset-password`);
                            alert(c.menu.resetDone(a.username, r.password));
                          });
                        }}
                      >
                        {c.menu.reset}
                      </button>
                      {(a.totp_enabled || a.email_codes) && (
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            if (confirm(c.menu.twoStepConfirm(a.username)))
                              act(() => call("DELETE", `${API}/accounts/${a.id}/totp`), c.done);
                          }}
                        >
                          {c.menu.twoStepOff}
                        </button>
                      )}
                      {a.id !== me.id && (
                        <button
                          type="button"
                          role="menuitem"
                          className="mk-ad-danger"
                          onClick={() => {
                            const typed = prompt(c.menu.deletePrompt(a.username));
                            if (typed === a.username)
                              act(() => call("DELETE", `${API}/accounts/${a.id}?confirm=${encodeURIComponent(typed)}`), c.done);
                          }}
                        >
                          {c.menu.delete}
                        </button>
                      )}
                    </RowMenu>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {betaAccount && (
        <BetaDialog
          locale={locale}
          apps={apps}
          account={betaAccount}
          trackers={trackers}
          setBeta={setBeta}
          onClose={() => setBetaFor(null)}
        />
      )}
      {ask === "beta" && (
        <BulkBetaDialog
          locale={locale}
          apps={betaApps}
          count={chosen.length}
          trackers={trackers}
          onClose={() => setAsk(null)}
          onRun={(app, feature, on) => run({ kind: "beta", app, feature, on })}
        />
      )}
      {ask && ask !== "beta" && (
        <ConfirmDialog
          locale={locale}
          bulk={ask}
          count={targets(ask).filter((a) => needs(ask, a)).length}
          self={selfIn(ask)}
          onClose={() => setAsk(null)}
          onRun={() => run(ask)}
        />
      )}
    </section>
  );
}

/** A dialog that opens as a modal when it mounts, and calls onClose however it is closed. */
function useModal(onClose: () => void) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  const props = {
    ref,
    className: "mk-ad-dialog",
    onClose,
    onClick: (e: React.MouseEvent) => {
      if (e.target === ref.current) ref.current?.close();
    },
  };
  return { props, close: () => ref.current?.close() };
}

/** Once for the whole batch. Deleting asks to type the number of accounts. */
function ConfirmDialog({
  locale,
  bulk,
  count,
  self,
  onClose,
  onRun,
}: {
  locale: Locale;
  bulk: Bulk;
  count: number;
  self: boolean;
  onClose: () => void;
  onRun: () => void;
}) {
  const b = ADMIN_COPY[locale].bulk;
  const { props, close } = useModal(onClose);
  const [typed, setTyped] = useState("");
  const del = bulk.kind === "delete";
  const text =
    bulk.kind === "delete"
      ? b.deleteText(count)
      : bulk.kind === "twoStep"
        ? b.twoStepText(count)
        : bulk.kind === "app"
          ? b.takeText(count, BRANDS[bulk.app].name)
          : b.suspendText(count);
  const ready = count > 0 && (!del || typed.trim() === String(count));
  return (
    <dialog {...props} aria-labelledby="mk-ad-confirm-title">
      <form
        className="mk-ad-dialog-body"
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (!ready) return;
          onRun();
        }}
      >
        <h2 id="mk-ad-confirm-title">{b.confirmTitle}</h2>
        <p>{count > 0 ? text : b.nothing}</p>
        {self && <p className="mk-ad-muted">{b.selfNote}</p>}
        {del && count > 0 && (
          <label className="mk-ad-field">
            {b.typeToDelete(count)}
            <input
              className="mk-ad-input"
              inputMode="numeric"
              autoComplete="off"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoFocus
            />
          </label>
        )}
        <div className="mk-ad-dialog-foot">
          <button type="button" className="mk-ad-btn" onClick={close}>
            {b.cancel}
          </button>
          <button type="submit" className={`mk-ad-btn ${del ? "mk-ad-btn--danger" : "mk-ad-btn--primary"}`} disabled={!ready}>
            {del ? b.deleteGo(count) : b.go}
          </button>
        </div>
      </form>
    </dialog>
  );
}

/** One beta feature on or off for every selected account: choose the tracker and the feature. */
function BulkBetaDialog({
  locale,
  apps,
  count,
  trackers,
  onClose,
  onRun,
}: {
  locale: Locale;
  apps: BrandId[];
  count: number;
  trackers: PerApp<Tracker>;
  onClose: () => void;
  onRun: (app: BrandId, feature: string, on: boolean) => void;
}) {
  const c = ADMIN_COPY[locale];
  const { props, close } = useModal(onClose);
  const [app, setApp] = useState<BrandId>(apps[0]);
  const h = trackers[app];
  const betas = h?.state === "ok" ? h.data.betas : [];
  const [feature, setFeature] = useState(betas[0]?.id ?? "");
  const valid = betas.some((x) => x.id === feature);
  return (
    <dialog {...props} aria-labelledby="mk-ad-bulkbeta-title">
      <div className="mk-ad-dialog-body">
        <h2 id="mk-ad-bulkbeta-title">{c.bulk.betaTitle(count)}</h2>
        {apps.length > 1 && (
          <label className="mk-ad-field">
            {c.bulk.tracker}
            <select
              value={app}
              onChange={(e) => {
                const next = e.target.value as BrandId;
                const t = trackers[next];
                setApp(next);
                setFeature(t?.state === "ok" ? (t.data.betas[0]?.id ?? "") : "");
              }}
            >
              {apps.map((id) => (
                <option key={id} value={id}>
                  {BRANDS[id].name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="mk-ad-field">
          {c.bulk.feature}
          <select value={feature} onChange={(e) => setFeature(e.target.value)}>
            {betas.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name[locale]}
              </option>
            ))}
          </select>
        </label>
        <div className="mk-ad-dialog-foot">
          <button type="button" className="mk-ad-btn" onClick={close}>
            {c.bulk.cancel}
          </button>
          <button type="button" className="mk-ad-btn" disabled={!valid} onClick={() => onRun(app, feature, false)}>
            {c.bulk.turnOff}
          </button>
          <button type="button" className="mk-ad-btn mk-ad-btn--primary" disabled={!valid} onClick={() => onRun(app, feature, true)}>
            {c.bulk.turnOn}
          </button>
        </div>
      </div>
    </dialog>
  );
}

/** Per tracker the account uses, that tracker's beta features as checkboxes. */
function BetaDialog({
  locale,
  apps: managed,
  account,
  trackers,
  setBeta,
  onClose,
}: {
  locale: Locale;
  apps: BrandId[];
  account: Account;
  trackers: PerApp<Tracker>;
  setBeta: SetBeta;
  onClose: () => void;
}) {
  const c = ADMIN_COPY[locale];
  const { props, close } = useModal(onClose);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const apps = managed.filter((id) => account.apps.includes(id));

  return (
    <dialog {...props}>
      <div className="mk-ad-dialog-body">
        <h2>{c.betas.title(account.display_name || account.username)}</h2>
        {apps.length === 0 && <p className="mk-ad-muted">{c.betas.noTrackers}</p>}
        {apps.map((app) => {
          const Mark = MARK[app];
          const h = trackers[app];
          const entry = h?.state === "ok" ? h.data.accounts.find((x) => x.account_id === account.id) : undefined;
          return (
            <div key={app} className="mk-ad-beta">
              <b className="mk-ad-app">
                <Mark size={14} /> {BRANDS[app].name}
              </b>
              {!h || h.state === "loading" ? (
                <p className="mk-ad-muted">{c.loading}</p>
              ) : h.state !== "ok" ? (
                <HubNote locale={locale} app={app} hub={h} />
              ) : h.data.betas.length === 0 ? (
                <p className="mk-ad-muted">{c.betas.none(BRANDS[app].name)}</p>
              ) : !entry ? (
                <p className="mk-ad-muted">{c.betas.noUser(BRANDS[app].name)}</p>
              ) : (
                h.data.betas.map((x) => (
                  <label key={x.id} className="mk-ad-check">
                    <input
                      type="checkbox"
                      checked={entry.betas.includes(x.id)}
                      disabled={busy}
                      onChange={async (e) => {
                        setBusy(true);
                        setError(null);
                        try {
                          await setBeta(app, account.id, x.id, e.target.checked);
                        } catch (err) {
                          setError((err as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    />
                    {x.name[locale]}
                  </label>
                ))
              )}
            </div>
          );
        })}
        {error && (
          <p className="mk-ad-notice mk-ad-notice--bad" role="status">
            {error}
          </p>
        )}
        <div className="mk-ad-dialog-foot">
          <button type="button" className="mk-ad-btn" onClick={close}>
            {c.betas.close}
          </button>
        </div>
      </div>
    </dialog>
  );
}

function FeedbackTab({
  locale,
  apps,
  items,
  feedback,
  save,
  shot,
}: {
  locale: Locale;
  apps: BrandId[];
  items: Feedback[];
  feedback: PerApp<Feedback[]>;
  save: Save;
  shot: (f: Feedback) => string;
}) {
  const c = ADMIN_COPY[locale];
  const m = c.feedback;
  const [app, setApp] = useState<BrandId | "all">("all");
  const [status, setStatus] = useState<"open" | "all" | FeedbackStatus>("open");
  const [big, setBig] = useState<Feedback | null>(null);
  const shown = items.filter(
    (f) => (app === "all" || f.app === app) && (status === "all" || (status === "open" ? isOpen(f) : f.status === status)),
  );
  const loading = apps.some((a) => !feedback[a] || feedback[a]?.state === "loading");

  return (
    <section className="mk-ad-section">
      <div className="mk-ad-head">
        <h2>{m.title}</h2>
        <div className="mk-ad-row">
          {apps.length > 1 &&
            (["all", ...apps] as const).map((a) => (
              <button
                key={a}
                type="button"
                className={`mk-ad-seg ${app === a ? "mk-ad-seg--on" : ""}`}
                aria-pressed={app === a}
                onClick={() => setApp(a)}
              >
                {a === "all" ? m.allTrackers : BRANDS[a].name}
              </button>
            ))}
          <select aria-label={m.statusLabel} value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            <option value="open">{m.filter.open}</option>
            <option value="all">{m.filter.all}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {m.status[s]}
              </option>
            ))}
          </select>
        </div>
      </div>
      {apps.map((a) => (
        <HubNote key={a} locale={locale} app={a} hub={feedback[a]} />
      ))}
      {shown.length === 0 ? (
        <p className="mk-ad-muted">{loading ? c.loading : m.none}</p>
      ) : (
        <ul className="mk-ad-feed">
          {shown.map((f) => (
            <FeedbackItem
              key={`${f.app}:${f.id}`}
              locale={locale}
              f={f}
              save={save}
              src={shot(f)}
              withApp={apps.length > 1}
              enlarge={() => setBig(f)}
            />
          ))}
        </ul>
      )}
      {big && <Lightbox locale={locale} src={shot(big)} onClose={() => setBig(null)} />}
    </section>
  );
}

/** One feedback item: what, status, when, who, where; the message; the screenshot; the details; and a reply with a
 *  status. */
function FeedbackItem({
  locale,
  f,
  save,
  src,
  withApp,
  enlarge,
}: {
  locale: Locale;
  f: Feedback;
  save: Save;
  src: string;
  withApp: boolean;
  enlarge: () => void;
}) {
  const m = ADMIN_COPY[locale].feedback;
  const [status, setStatus] = useState<FeedbackStatus>(f.status);
  const [reply, setReply] = useState(f.reply ?? "");
  const [note, setNote] = useState<string | null>(null);
  const changed = status !== f.status || reply !== (f.reply ?? "");
  const ctx = f.context ?? {};
  const Mark = MARK[f.app];

  return (
    <li className="mk-ad-fb">
      <div className="mk-ad-fb-head">
        {withApp && (
          <span className="mk-ad-app">
            <Mark size={14} /> {BRANDS[f.app].name}
          </span>
        )}
        <span className="mk-ad-chip">{m.kind[f.kind]}</span>
        <span className="mk-ad-chip">{m.status[f.status]}</span>
        <span>{whenTime(f.created_at, locale)}</span>
        {f.username && <span>{m.from(f.username)}</span>}
        {f.page && <span className="mk-ad-code">{f.page}</span>}
      </div>
      <div className="mk-ad-fb-body">
        <p className="mk-ad-fb-msg">{f.message}</p>
        {f.has_screenshot && (
          <button type="button" className="mk-ad-thumb" onClick={enlarge} aria-label={m.screenshot}>
            <img src={src} alt="" loading="lazy" />
          </button>
        )}
      </div>
      <details className="mk-ad-fb-details">
        <summary>{m.details}</summary>
        <dl>
          {ctx.version && (
            <>
              <dt>{m.version}</dt>
              <dd className="mk-ad-code">{ctx.version}</dd>
            </>
          )}
          {ctx.browser && (
            <>
              <dt>{m.browser}</dt>
              <dd>{ctx.browser}</dd>
            </>
          )}
          {ctx.screen && (
            <>
              <dt>{m.screen}</dt>
              <dd>{[ctx.screen, ctx.language, ctx.theme].filter(Boolean).join(" · ")}</dd>
            </>
          )}
          {!!ctx.errors?.length && (
            <>
              <dt>{m.errors}</dt>
              <dd>
                <ul className="mk-ad-code">
                  {ctx.errors.map((e, i) => (
                    <li key={i}>
                      {e.message} {e.where ? `(${e.where})` : ""}
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          )}
        </dl>
      </details>
      <label className="mk-ad-fb-reply">
        {m.replyLabel}
        <textarea placeholder={m.replyPh} value={reply} maxLength={5000} onChange={(e) => setReply(e.target.value)} />
      </label>
      <div className="mk-ad-row">
        <select aria-label={m.statusLabel} value={status} onChange={(e) => setStatus(e.target.value as FeedbackStatus)}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {m.status[s]}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="mk-ad-btn mk-ad-btn--primary"
          disabled={!changed}
          onClick={async () => {
            setNote(null);
            try {
              await save(f, { status, reply });
              setNote(m.saved);
            } catch (e) {
              setNote((e as Error).message);
            }
          }}
        >
          {m.save}
        </button>
        {note && <span className="mk-ad-muted">{note}</span>}
      </div>
    </li>
  );
}

function Lightbox({ locale, src, onClose }: { locale: Locale; src: string; onClose: () => void }) {
  const m = ADMIN_COPY[locale].feedback;
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="mk-ad-dialog mk-ad-lightbox"
      onClose={onClose}
      onClick={() => ref.current?.close()}
      aria-label={m.screenshot}
    >
      <img src={src} alt={m.screenshot} />
      <button type="button" className="mk-ad-btn" onClick={() => ref.current?.close()}>
        {m.close}
      </button>
    </dialog>
  );
}

function SignUp({
  locale,
  apps,
  reg,
  act,
  inApp,
  registerPath,
}: {
  locale: Locale;
  apps: BrandId[];
  reg: Registration;
  act: Act;
  inApp: boolean;
  registerPath: string;
}) {
  const c = ADMIN_COPY[locale];
  const [chosen, setChosen] = useState<BrandId[]>(apps);
  const [days, setDays] = useState(14);
  const [made, setMade] = useState<string | null>(null);
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  // On the front door the link opens its sign-up; inside a tracker, that tracker's register page.
  const link = (code: string) =>
    inApp ? `${origin}${registerPath}?invite=${encodeURIComponent(code)}` : `${origin}/?invite=${encodeURIComponent(code)}#signup`;
  const open = reg.invites.filter((i) => i.used_by === null && (!i.expires_at || new Date(i.expires_at).getTime() > Date.now()));

  return (
    <section className="mk-ad-section">
      <div className="mk-ad-head">
        <h2>{c.signup.title}</h2>
      </div>
      <div className="mk-ad-row">
        {(["open", "invite", "closed"] as const).map((m) => (
          <button
            key={m}
            type="button"
            className={`mk-ad-seg ${reg.registration === m ? "mk-ad-seg--on" : ""}`}
            aria-pressed={reg.registration === m}
            onClick={() => act(() => call("PATCH", `${API}/registration`, { registration: m }), c.done)}
          >
            {c.modes[m]}
          </button>
        ))}
      </div>
      <p className="mk-ad-muted">{c.signup.modeText[reg.registration]}</p>

      <h3>{c.signup.invites}</h3>
      <form
        className="mk-ad-row"
        onSubmit={(e) => {
          e.preventDefault();
          act(async () => {
            const r = await call<{ code: string }>("POST", `${API}/invites`, { days, apps: apps.length > 1 ? chosen : apps });
            setMade(link(r.code));
          });
        }}
      >
        {apps.length > 1 &&
          apps.map((id) => (
            <label key={id} className="mk-ad-check">
              <input
                type="checkbox"
                checked={chosen.includes(id)}
                onChange={() => setChosen((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]))}
              />
              {BRANDS[id].name}
            </label>
          ))}
        <label className="mk-ad-check">
          {c.signup.valid}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 14, 30, 90].map((d) => (
              <option key={d} value={d}>
                {c.days(d)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="mk-ad-btn mk-ad-btn--primary" disabled={apps.length > 1 && chosen.length === 0}>
          {c.signup.make}
        </button>
      </form>
      {made && (
        <p className="mk-ad-notice">
          {c.signup.made} <code className="mk-ad-code">{made}</code>{" "}
          <button type="button" className="mk-ad-btn" onClick={() => navigator.clipboard?.writeText(made)}>
            {c.signup.copy}
          </button>
        </p>
      )}
      {open.length > 0 ? (
        <ul className="mk-ad-list">
          {open.map((i) => (
            <li key={i.code}>
              <code className="mk-ad-code">{i.code}</code>
              <span>{(i.apps ?? []).map((a) => BRANDS[a as BrandId]?.name ?? a).join(" + ") || "—"}</span>
              <span className="mk-ad-muted">{i.expires_at ? c.signup.until(when(i.expires_at, locale)) : c.signup.noEnd}</span>
              <button type="button" className="mk-ad-btn" onClick={() => navigator.clipboard?.writeText(link(i.code))}>
                {c.signup.copy}
              </button>
              <button
                type="button"
                className="mk-ad-btn"
                onClick={() => act(() => call("DELETE", `${API}/invites/${encodeURIComponent(i.code)}`), c.done)}
              >
                {c.signup.revoke}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mk-ad-muted">{c.signup.none}</p>
      )}
    </section>
  );
}

function Activity({ locale, audit }: { locale: Locale; audit: Audit[] }) {
  const c = ADMIN_COPY[locale];
  return (
    <section className="mk-ad-section">
      <div className="mk-ad-head">
        <h2>{c.activity.title}</h2>
      </div>
      {audit.length === 0 ? (
        <p className="mk-ad-muted">{c.activity.none}</p>
      ) : (
        <ul className="mk-ad-list">
          {audit.map((e) => (
            <li key={e.id}>
              <span className="mk-ad-muted">{when(e.at, locale)}</span>
              <span>
                <b>{e.actor}</b> {c.activity.actions[e.action] ?? e.action} {e.target && <b>{e.target}</b>}{" "}
                {e.detail && <span className="mk-ad-muted">({e.detail})</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
