"use client";

// The shell of the app.
//
//   ┌──────────┬────────────────────────────────────────┐
//   │ sidebar  │ top bar 60px, no bottom border         │
//   │ 248px    ├────────────────────────────────────────┤
//   │ walnut   │ content, 40px margin, max 1180px       │
//   └──────────┴────────────────────────────────────────┘
//
// Before this there were ten tabs here in a bar you had to scroll sideways on a
// phone — so the tab you were on regularly started out of view. Meridian's
// starting point is the opposite: few destinations, and within every destination
// several views. The layout lives in lib/nav.ts; the tab bar below shows the
// views of the destination you are in, and is not there if it only has one.
//
// The pages kept their place: /details and /rebalancing exist exactly as they
// did, they have only become reachable through the tab of the screen they
// belong to. /benchmarks is now part of Returns and redirects there. No
// bookmark breaks.

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { useCountVisits } from "@trackerai/ui/lib/visits";
import type { Summary } from "@/lib/dashboard";
import { findItem, findTab, SITE_NAV, visibleNav } from "@/lib/nav";
import { MenuIcon, SwapIcon, UploadIcon } from "@trackerai/ui/icons";
import { Badge, Button, IconButton, Tabs } from "@/components/ds";
import SidebarNav from "@trackerai/ui/ds/SidebarNav";
import Logomark from "@/components/ds/Logomark";
import SubNav from "@trackerai/ui/ds/SubNav";
import FeedbackDialog from "@/components/feedback/FeedbackDialog";
import PageHelp from "@/components/PageHelp";
import StartBanner from "@/components/StartBanner";
import Welcome from "@/components/Welcome";
import { APP } from "@/lib/app";
import { isIncluded, useOnboarding } from "@/lib/onboarding";
import ThemeToggle from "@trackerai/ui/components/ThemeToggle";
import UpdateSheet from "@/components/UpdateSheet";
import DegiroExplanation from "@/components/OnboardingTutorial";
import { tr, trx } from "@/lib/i18n";
import { useAccountLocale } from "@/lib/i18n/provider";
import AccountGate, { needsGate } from "@/components/AccountGate";
import { adminHref, useFrontDoor, useTrackerUrl } from "@/lib/frontDoor";

type Me = {
  username: string; name: string; is_admin: boolean; beta_features: string[]; locale?: string | null;
  // the shared trackerai account: what is still missing before this tracker opens (components/AccountGate.tsx)
  totp_setup_required?: boolean; in_app?: boolean;
};

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : parts[0]?.[1] ?? "";
  return (first + last).toUpperCase();
}

const postVisit = (path: string) => api.post(path);

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [me, setMe] = useState<Me | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useAccountLocale(me?.locale);
  useCountVisits(pathname, !!me, postVisit);

  const [meVersion, setMeVersion] = useState(0);
  // An account that still has to set up two-step login, or join this tracker: the gate instead of the app.
  const [gate, setGate] = useState<Me | null>(null);
  useEffect(() => {
    api
      .get<Me>("/api/auth/me")
      .then((m) => {
        setGate(needsGate(m) ? m : null);
        setMe(needsGate(m) ? null : m);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
      });
  }, [router, meVersion]);

  // Refresh prices automatically once per browser session on arrival, so a fresh
  // login lands on current prices without opening the Update panel.
  // sessionStorage makes sure it stays at once: navigating within the app and
  // reloading keep the prices from the start of the session instead of querying
  // the external price API again. The flag flips *before* the request, so React
  // StrictMode cannot start two refreshes; a failure clears it, so the next time
  // may try again.
  useEffect(() => {
    if (!me || typeof window === "undefined") return;
    if (sessionStorage.getItem("prices-auto-refreshed") === "1") return;
    sessionStorage.setItem("prices-auto-refreshed", "1");
    api
      .post("/api/prices/refresh")
      .then(() => queryClient.invalidateQueries())
      .catch(() => {
        // A background refresh that fails must not interrupt the user — the Update
        // button and its own error message stay there.
        sessionStorage.removeItem("prices-auto-refreshed");
      });
  }, [me, queryClient]);

  // Fetch connected bank accounts on arrival, like the prices: once per browser
  // session, and then only what was fetched more than six hours ago — a tab you
  // open often does not ask the bank every time. Not in the background: someone
  // who does not open the app gains nothing from fresh figures. Someone without a
  // connection gets a 409; that stays silent. Only with the money beta flag;
  // without the flag the API refuses anyway.
  const money = !!me?.beta_features.includes("money");
  useEffect(() => {
    if (!money || typeof window === "undefined") return;
    if (sessionStorage.getItem("bank-auto-fetched") === "1") return;
    sessionStorage.setItem("bank-auto-fetched", "1");
    api
      .post<{ added: number; balances: number }>("/api/connections/enablebanking/fetch?only_if_older_than_hours=6")
      .then((v) => {
        if (v.added > 0 || v.balances > 0) queryClient.invalidateQueries();
      })
      .catch(() => {
        // Geen koppeling, of de bank antwoordt niet: de knop in Bijwerken en
        // op de Bankkoppeling-pagina laat zien wat er aan de hand is.
      });
  }, [money, queryClient]);

  // The account menu closes on every click outside it.
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  const groups = useMemo(
    () => visibleNav({ beta: me?.beta_features ?? [], isAdmin: me?.is_admin ?? false }),
    [me]
  );
  const item = findItem(groups, pathname);
  const tab = findTab(item, pathname);

  // An address that is in the navigation but not for this account (beta flag,
  // admin): do not show the page, it only gets 403s from the API anyway.
  const allItem = findItem(SITE_NAV, pathname);
  const allTab = findTab(allItem, pathname);
  const gated = !!me && ((!!allItem && !item) || (!!allTab && allTab.id !== tab?.id));

  // The counter at "To label": the same number as "Waiting for you" on that page —
  // what needs a decision from you, per counterparty. To label is in the sidebar,
  // with the counter, so it is fetched everywhere once Money is on.
  const inSpending = item?.id === "spending" || (me?.beta_features ?? []).includes("money");
  const queue = useQuery({
    queryKey: ["labelling", "queue"],
    queryFn: () => api.get<{ waiting: number }>("/api/labelling/queue"),
    enabled: !!me && inSpending,
  });
  const outstanding = queue.data?.waiting ?? 0;

  // Help only shows the manual of what you track.
  const onboardingQ = useOnboarding(!!me);
  const choice = onboardingQ.data?.choice;
  // Admin goes to trackerai.nl/admin when this installation has the front door (lib/frontDoor.ts); the logo goes to
  // its homepage, and the account menu has a way to the other tracker.
  const frontDoor = useFrontDoor(!!me);
  const healthUrl = useTrackerUrl("health", !!me);
  const tabVisible = (itemId: string, tabId: string) =>
    itemId !== "help"
    || (tabId === "portfolio" ? isIncluded(choice, "investments") : tabId === "money" ? isIncluded(choice, "money") : true);
  const visibleTabs = item?.tabs?.filter((t) => tabVisible(item.id, t.id)).map((t) => ({
    id: t.id,
    label: t.id === "labelling" && outstanding > 0
      ? <span className="inline-flex items-center gap-1.5">{t.label} <Badge>{outstanding}</Badge></span>
      : t.label,
    href: t.id === "admin" ? adminHref(frontDoor) : t.href,
  })) ?? [];

  if (gate) return <AccountGate me={gate} onReady={() => setMeVersion((v) => v + 1)} />;
  if (!me) {
    return (
      <div className="grid min-h-screen place-items-center text-sm text-ink-muted">{tr("Loading…")}</div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <SidebarNav
        logo={<Logomark height={15} className="ds-sidebar__logo" />}
        name={APP.name}
        homeHref={frontDoor ?? APP.home}
        groups={groups}
        activeId={item?.id ?? null}
        badges={outstanding > 0 ? { labelling: outstanding } : undefined}
        open={navOpen}
        onOpen={() => setNavOpen(true)}
        onClose={() => setNavOpen(false)}
        footer={
          <div className="flex flex-col gap-2 px-2 pb-1 text-xs leading-normal" style={{ color: "var(--text-on-ink-muted)" }}>
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                className="underline underline-offset-4"
                onClick={() => {
                  setNavOpen(false);
                  setFeedbackOpen(true);
                }}
              >
                Feedback
              </button>
              {healthUrl && (
                <a href={healthUrl} className="inline-flex items-center gap-1 underline underline-offset-4">
                  <SwapIcon className="h-3 w-3" />
                  health-tracker
                </a>
              )}
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate">{trx("Logged in as {0}", me.name)}</span>
              <button
                type="button"
                className="flex-none underline underline-offset-4"
                onClick={async () => {
                  await api.post("/api/auth/logout");
                  router.replace("/login");
                }}
              >{tr("Log out")}</button>
            </div>
          </div>
        }
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Sticky, and the bar below it not: on a phone the dashboard is five blocks tall, and
            reaching another destination otherwise meant scrolling all the way back up first.
            Opaque, not translucent — frosted glass doesn't belong in this design. */}
        {/* Eén plakkend blok: de balk, en op een telefoon de tabs als eigen rij eronder, groot genoeg om te tikken. */}
        <div className="sticky top-0 z-30">
          <header className="ds-topbar ds-topbar--flush !gap-3 !px-4 sm:!px-6 lg:!px-page">
            <IconButton
              label={tr("Open menu")}
              onClick={() => setNavOpen(true)}
              icon={<MenuIcon className="h-[18px] w-[18px]" />}
              className="-ml-2 lg:hidden"
            />
            {/* The title and its "?" belong together, so they share one line and one truncation:
                the button may never drop away with the title on a narrow screen, and it may never
                end up apart from it either. */}
            <span className="flex min-w-0 items-center gap-1.5">
              <h1 className="ds-topbar__title truncate">{item?.label ?? tr("Portfolio")}</h1>
              <PageHelp />
            </span>
            {visibleTabs.length > 1 ? (
              <nav className="ds-topbar__tabs ml-2 hidden min-w-0 flex-1 self-stretch overflow-x-auto no-scrollbar lg:block" aria-label={tr("Views of {0}", item?.label ?? tr("this page"))}>
                <Tabs items={visibleTabs} value={tab?.id} ariaLabel={tr("Views of {0}", item?.label ?? tr("this page"))} className="h-full whitespace-nowrap" />
              </nav>
            ) : null}
            <span className={`ds-topbar__spacer ${visibleTabs.length > 1 ? "lg:hidden" : ""}`} />

            <div className="flex flex-none items-center gap-1.5">
              <Button
                variant="secondary"
                onClick={() => setSheetOpen(true)}
                icon={<UploadIcon className="h-[15px] w-[15px]" />}
                // On a phone the label drops away and a button with only a glyph remains — that
                // needs a name, otherwise it is a button without meaning for a screen reader
                // (and for a test). The visible label and aria-label say the same.
                aria-label={tr("Update")}
              >
                <span className="hidden sm:inline">{tr("Update")}</span>
              </Button>
              <ThemeToggle />
              <div className="relative" ref={menuRef}>
                <button
                  type="button"
                  onClick={() => setMenuOpen((v) => !v)}
                  aria-label={`Account: ${me.name}`}
                  aria-expanded={menuOpen}
                  className="grid h-8 w-8 place-items-center rounded-full text-[11px] font-medium"
                  style={{ background: "var(--surface-inset)", color: "var(--text-secondary)" }}
                >
                  {initials(me.name)}
                </button>
                {menuOpen && (
                  <div
                    className="absolute right-0 top-full z-30 mt-2 w-52 overflow-hidden rounded-md py-1"
                    style={{
                      background: "var(--surface-card)",
                      boxShadow: "inset 0 0 0 1px var(--border-hairline), var(--shadow-3)",
                    }}
                  >
                    <Link
                      href="/account"
                      onClick={() => setMenuOpen(false)}
                      className="block px-3 py-2 text-sm hover:bg-surface-2"
                    >{tr("Settings")}</Link>
                    <Link
                      href="/help"
                      onClick={() => setMenuOpen(false)}
                      className="block px-3 py-2 text-sm hover:bg-surface-2"
                    >
                      Help
                    </Link>
                    <button
                      type="button"
                      onClick={() => {
                        setMenuOpen(false);
                        setFeedbackOpen(true);
                      }}
                      className="block w-full px-3 py-2 text-left text-sm hover:bg-surface-2"
                    >
                      Feedback
                    </button>
                    {healthUrl && (
                      <a href={healthUrl} className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-surface-2">
                        <SwapIcon className="h-3.5 w-3.5" />
                        health-tracker
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={async () => {
                        await api.post("/api/auth/logout");
                        router.replace("/login");
                      }}
                      className="block w-full px-3 py-2 text-left text-sm hover:bg-surface-2"
                    >{tr("Log out")}</button>
                  </div>
                )}
              </div>
            </div>
          </header>
          {visibleTabs.length > 1 && (
            <SubNav label={tr("Views of {0}", item?.label ?? tr("this page"))} items={visibleTabs} value={tab?.id} />
          )}
        </div>

        {/* Left-aligned, not centred: that way the content sits right below the title and tabs in
            the top bar. */}
        <main className="w-full max-w-content flex-1 px-4 pb-20 pt-4 sm:px-6 lg:px-page lg:pt-5">
          {/* Only above a part that is still empty, and until you dismiss it. */}
          <StartBanner enabled={!!me} />
          {gated ? (
            <div className="mx-auto flex max-w-md flex-col items-start gap-3 py-16">
              <h2 className="font-display text-[21px] font-normal tracking-[-0.014em]">{tr("This isn't on for your account")}</h2>
              <p className="text-[13px] leading-relaxed text-ink-muted">{tr("This part is turned on per account. Ask the admin about it if you want to use it.")}</p>
              <Link href={APP.home} className="text-[13px] underline underline-offset-4">{tr("To Net worth")}</Link>
            </div>
          ) : children}
        </main>
      </div>

      <UpdateSheet
        money={money}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onOpenTutorial={() => setTutorialOpen(true)}
      />
      <DegiroExplanation
        open={tutorialOpen}
        onClose={() => setTutorialOpen(false)}
        onUpdate={() => setSheetOpen(true)}
      />
      {/* The first time: what do you want to keep track of, and the steps that go with it. */}
      <Welcome enabled={!!me} onUpdate={() => setSheetOpen(true)} nav={groups} />
      <FeedbackDialog open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
    </div>
  );
}
