"use client";

// The shell of every page: sidebar, top bar, content. The same layout as health-tracker and wealth-tracker.

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import SidebarNav from "@trackerai/ui/ds/SidebarNav";
import ThemeToggle from "@trackerai/ui/components/ThemeToggle";
import { IconButton } from "@trackerai/ui/ds/Button";
import { MenuIcon } from "@trackerai/ui/icons";
import Logomark from "@/components/Logomark";

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

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const t = useT();
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
