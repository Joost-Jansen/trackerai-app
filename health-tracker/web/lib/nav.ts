// The site's navigation, in one place. The names are in lib/i18n (nav.items, nav.tabs); localizeNav fills them in.
// The ids are catalog keys (lib/i18n nav.items, nav.tabs).

import type { Messages } from "@/lib/i18n";

export type NavTab = { id: keyof Messages["nav"]["tabs"]; label: string; href: string; adminOnly?: boolean };

export type NavItem = {
  id: keyof Messages["nav"]["items"];
  label: string;
  href: string;
  icon: string;
  tabs?: NavTab[];
  extraPaths?: string[];
};

export type NavGroup = { label?: string; items: NavItem[] };

const tab = (id: NavTab["id"], href: string, adminOnly?: boolean): NavTab => ({ id, label: "", href, ...(adminOnly ? { adminOnly } : {}) });

export const NAV: NavGroup[] = [
  {
    items: [
      { id: "dashboard", label: "", href: "/dashboard/", icon: "layout", tabs: [tab("overview", "/dashboard/"), tab("sleepBody", "/dashboard/body/")] },
      {
        id: "trends",
        label: "",
        href: "/trends/",
        icon: "chart",
        tabs: [tab("training", "/trends/"), tab("recovery", "/trends/recovery/"), tab("performance", "/trends/performance/")],
      },
      { id: "routes", label: "", href: "/routes/", icon: "route" },
      { id: "history", label: "", href: "/history/", icon: "map" },
      { id: "plan", label: "", href: "/plan/", icon: "clipboard" },
      {
        id: "log",
        label: "",
        href: "/log/",
        icon: "book",
        extraPaths: ["/analyses/"],
        tabs: [tab("log", "/log/"), tab("analyses", "/analyses/"), tab("goals", "/analyses/goals/"), tab("profile", "/analyses/profile/")],
      },
      {
        id: "settings",
        label: "",
        href: "/settings/",
        icon: "settings",
        tabs: [
          tab("account", "/settings/"),
          tab("connections", "/settings/connections/"),
          tab("zones", "/settings/zones/"),
          tab("agents", "/settings/agents/"),
          tab("feedback", "/settings/feedback/"),
          tab("admin", "/settings/admin/", true),
        ],
      },
      {
        // One place for all explanations: the checklist, the guide and Claude as coach.
        id: "help",
        label: "",
        href: "/help/",
        icon: "help",
        tabs: [tab("start", "/help/"), tab("guide", "/help/guide/"), tab("claude", "/help/claude/")],
      },
    ],
  },
];

/** NAV with the names in the user's language. */
export function localizeNav(groups: NavGroup[], t: Messages): NavGroup[] {
  return groups.map((g) => ({
    ...g,
    items: g.items.map((i) => ({ ...i, label: t.nav.items[i.id], tabs: i.tabs?.map((x) => ({ ...x, label: t.nav.tabs[x.id] })) })),
  }));
}

export function findItem(groups: NavGroup[], pathname: string): NavItem | undefined {
  const path = pathname.endsWith("/") ? pathname : pathname + "/";
  return groups.flatMap((g) => g.items).find((i) => path.startsWith(i.href) || i.extraPaths?.some((p) => path.startsWith(p)));
}
