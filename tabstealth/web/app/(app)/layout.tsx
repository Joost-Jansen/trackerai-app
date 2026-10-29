"use client";

// The shell of every page: sidebar, top bar, content. The same layout as health-tracker and wealth-tracker.
// Behind the trackerai login: logged out goes to /login/ (and back after), an account without tabstealth sees why.

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import SidebarNav from "@trackerai/ui/ds/SidebarNav";
import ThemeToggle from "@trackerai/ui/components/ThemeToggle";
import { IconButton } from "@trackerai/ui/ds/Button";
import { MenuIcon } from "@trackerai/ui/icons";
import Logomark from "@/components/Logomark";
import { api, ApiError } from "@/lib/api";

const SIDEBAR_KEY = "tabstealth.sidebar";

function SidebarIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg viewBox="0 0 20 20" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden>
      <rect x="2.5" y="3.5" width="15" height="13" rx="2" />
      <path d="M7.5 3.5v13" />
      <path d={collapsed ? "M11 8.5l2 1.5-2 1.5" : "M13 8.5l-2 1.5 2 1.5"} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
import { useLocale, useT } from "@/lib/i18n";
import { nav, TOPBAR_ACTIONS, TOPBAR_TITLE } from "@/lib/nav";

type Me = { username: string; is_admin: boolean; front_door_url: string | null };

/** No tabstealth for this account (yet): why, and the way out. */
function Gate({ code, onLogout }: { code: string; onLogout: () => void }) {
  const t = useT();
  const status = useQuery({
    queryKey: ["registration-status"],
    queryFn: () => api.get<{ front_door_url?: string | null }>("/api/auth/registration-status"),
  });
  const setup = code === "totp_setup_required" || code === "email_verify_required";
  const account = status.data?.front_door_url;
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="flex w-full max-w-[360px] flex-col gap-4">
        <Logomark height={30} />
        <h1 className="font-display text-[28px] font-light leading-tight">{setup ? t.auth.setupTitle : t.auth.notEnabledTitle}</h1>
        <p className="text-sm text-ink-muted">{setup ? t.auth.setupNeeded : t.auth.notEnabled}</p>
        <div className="flex flex-wrap gap-4 text-[12.5px] text-ink-muted">
          {setup && account && (
            <a href={account} className="underline underline-offset-2">
              {t.auth.openAccount}
            </a>
          )}
          <button type="button" className="underline underline-offset-2" onClick={onLogout}>
            {t.auth.otherAccount}
          </button>
        </div>
      </div>
    </main>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const t = useT();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me"), retry: false });
  const denied = me.error instanceof ApiError ? me.error : null;
  useEffect(() => {
    if (denied?.status === 401) router.replace(`/login/?next=${encodeURIComponent(pathname)}`);
  }, [denied, pathname, router]);
  const logout = async () => {
    await api.post("/api/auth/logout").catch(() => {});
    qc.clear();
    router.replace("/login/");
  };
  const { locale, setLocale } = useLocale();
  const [navOpen, setNavOpen] = useState(false);
  // The sidebar folds away so the video and the tab get the room. Your last choice is kept on this device;
  // without one, a song page starts folded.
  const [pref, setPref] = useState<"open" | "closed" | null>(null);
  useEffect(() => {
    try {
      const v = localStorage.getItem(SIDEBAR_KEY);
      if (v === "open" || v === "closed") setPref(v);
    } catch {
      /* private window: then we do not remember it */
    }
  }, []);
  const collapsed = pref ? pref === "closed" : pathname.startsWith("/song");
  const toggleSidebar = () => {
    const next = collapsed ? "open" : "closed";
    setPref(next);
    setNavOpen(false);
    try {
      localStorage.setItem(SIDEBAR_KEY, next);
    } catch {
      /* private window: then we do not remember it */
    }
  };
  const groups = nav(t);
  // A song page belongs to the library.
  // the song, video and PDF pages fill the title slot themselves
  const ownHeader = ["/song", "/watch", "/pdf"].some((p) => pathname.startsWith(p));
  // a song, video or PDF belongs to the library
  const item = groups[0].items.find((i) => pathname.startsWith(i.href)) ?? (ownHeader ? groups[0].items[0] : null);

  if (denied && denied.status !== 401) return <Gate code={denied.code ?? ""} onLogout={logout} />;
  if (!me.data) return <div className="min-h-screen" />; // checking the login, or on the way to it

  return (
    <div className="flex min-h-screen">
      <SidebarNav
        logo={<Logomark height={15} className="ds-sidebar__logo" />}
        name="tabstealth"
        homeHref="/library/"
        groups={groups}
        activeId={item?.id ?? null}
        open={navOpen}
        onOpen={() => setNavOpen(true)}
        onClose={() => setNavOpen(false)}
        collapsed={collapsed}
        footer={
          <div
            className="flex items-center justify-between gap-3 px-2 pb-1 text-xs leading-normal"
            style={{ color: "var(--text-on-ink-muted)" }}
          >
            <button type="button" className="underline underline-offset-4" onClick={() => setLocale(locale === "nl" ? "en" : "nl")}>
              {t.common.language}
            </button>
            <button type="button" className="underline underline-offset-4" onClick={() => void logout()} title={me.data.username}>
              {t.auth.logout}
            </button>
          </div>
        }
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-30">
          <header className="ds-topbar ds-topbar--flush !gap-3 !px-4 sm:!px-6 lg:!px-page">
            <IconButton
              label={t.nav.openMenu}
              onClick={() => setNavOpen(true)}
              icon={<MenuIcon className="h-[18px] w-[18px]" />}
              className={`-ml-2 ${collapsed ? "" : "lg:hidden"}`}
            />
            {/* a page can put its own title and controls here (the song page: the song and its transport) */}
            <div id={TOPBAR_TITLE} className="flex min-w-0 flex-1 items-center">
              {!ownHeader && <h1 className="ds-topbar__title truncate">{item?.label ?? "tabstealth"}</h1>}
            </div>
            <div id={TOPBAR_ACTIONS} className="flex flex-none items-center" />
            <div className="flex flex-none items-center gap-1.5">
              {/* wide screens: fold the sidebar away or bring it back */}
              <IconButton
                label={collapsed ? t.nav.showSidebar : t.nav.hideSidebar}
                onClick={toggleSidebar}
                icon={<SidebarIcon collapsed={collapsed} />}
                className="hidden lg:inline-flex"
              />
              <ThemeToggle />
            </div>
          </header>
        </div>
        {/* a song page ends with its tab panel exactly at the bottom of the screen: no extra room to scroll into */}
        <main className={`w-full flex-1 px-4 pt-4 sm:px-6 lg:px-page lg:pt-5 ${ownHeader ? "pb-4" : "pb-20"}`}>{children}</main>
      </div>
    </div>
  );
}
