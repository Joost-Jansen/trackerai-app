// The app's navigation, in one place.
//
// Meridian's starting point: a long-term investment tool has **few destinations
// and many views within each destination**. Hence the rule that brings the ten
// tabs from before back to six:
//
//   · a tab that is a different subject (Portfolio, News, Settings) becomes an
//     item in the sidebar;
//   · a tab that is a *different* view of the same subject (Positions next to
//     Details, Returns next to Benchmarks) becomes a tab *within* that screen;
//   · a tab that is really a filter or a period becomes a quiet switch next to
//     the thing it filters — those live on the pages themselves.
//
// Old Dutch addresses redirect to the English ones (next.config.js), so every
// bookmark keeps working; only the place where you click it has changed.

import { tr } from "@/lib/i18n";

export type NavTab = {
  id: string;
  label: string;
  href: string;
  /** Visible as soon as the user has this beta flag. */
  beta?: string;
  /** Admins only. */
  adminOnly?: boolean;
};

export type NavItem = {
  id: string;
  label: string;
  /** Where the item itself points to. Always the address of the first visible tab. */
  href: string;
  icon: string;
  beta?: string;
  adminOnly?: boolean;
  /** The views within this screen. One tab means: show no tab bar. */
  tabs?: NavTab[];
  /** Addresses that belong to this item without being a tab of their own (a detail page). */
  extraPaths?: string[];
};

export type NavGroup = {
  /** Fixed name for the code: the label is translated. */
  id?: string;
  label?: string;
  items: NavItem[];
};

/**
 * Your wealth is the app: net worth and spending come first, arranged by what you
 * come to do: Insight (how am I doing) and Keep track (reviewing, labelling,
 * setting up). Accounts keeps its tabs: the bank connection is about the same
 * accounts. The portfolio follows below as one group, its analysis included:
 * part of your wealth, not the main subject.
 *
 * Money is turned on per account with the beta flag `money` (Admin). The flag is
 * here *and* on every money router (`require_money`): hiding a page while the API
 * answers everyone is not gated, only unlinked.
 */
const MONEY = "money";
/** The full navigation of this site, before the filter on beta flags and admin. */
export const SITE_NAV: NavGroup[] = [
  {
    label: tr("Insight"),
    items: [
      { id: "net_worth", label: tr("Net worth"), href: "/net-worth", icon: "growth", beta: MONEY },
      // Icons of their own: the portfolio below uses chart, segments, list and coins.
      { id: "spending", label: tr("Spending"), href: "/spending", icon: "trending-down", beta: MONEY },
      { id: "budget", label: "Budget", href: "/spending/budget", icon: "gauge", beta: MONEY },
    ],
  },
  {
    label: tr("Keep track"),
    items: [
      { id: "transactions", label: tr("Transactions"), href: "/spending/transactions", icon: "swap", beta: MONEY },
      { id: "labelling", label: tr("To label"), href: "/spending/labelling", icon: "inbox", beta: MONEY },
      { id: "categories", label: tr("Categories"), href: "/categories", icon: "tag", beta: MONEY },
      {
        id: "accounts",
        label: tr("Accounts"),
        href: "/accounts",
        icon: "wallet",
        beta: MONEY,
        tabs: [
          { id: "accounts", label: tr("Accounts"), href: "/accounts" },
          { id: "connect", label: tr("Bank connection"), href: "/accounts/connect" },
        ],
      },
    ],
  },
  // The portfolio is one subject here, below your wealth: one header, and per
  // question one item, with the views as tabs (the rule at the top). Allocation
  // is another view of what you own, dividend part of what it earns, and the
  // calendar and the news are both about what happens around your holdings.
  // Beta flags stay on the tabs; an item with one visible tab shows no tab bar.
  {
    id: "portfolio",
    label: tr("Portfolio"),
    items: [
      { id: "today", label: tr("Today"), href: "/dashboard", icon: "layout" },
      {
        id: "holdings",
        label: tr("Holdings"),
        href: "/portfolio",
        icon: "list",
        extraPaths: ["/portfolio/"],
        tabs: [
          { id: "positions", label: tr("Positions"), href: "/portfolio" },
          { id: "details", label: "Details", href: "/details" },
          { id: "allocation", label: tr("Allocation"), href: "/allocation" },
          { id: "rebalancing", label: tr("Rebalancing"), href: "/rebalancing", beta: "rebalancing" },
        ],
      },
      {
        id: "performance",
        label: tr("Performance"),
        href: "/returns",
        icon: "chart",
        tabs: [
          { id: "returns", label: tr("Returns"), href: "/returns" },
          { id: "dividend", label: "Dividend", href: "/dividend", beta: "dividends" },
        ],
      },
      {
        id: "agenda",
        label: tr("Agenda & news"),
        href: "/calendar",
        icon: "calendar",
        tabs: [
          { id: "calendar", label: tr("Calendar"), href: "/calendar", beta: "calendar" },
          { id: "market", label: tr("Market news"), href: "/news" },
          { id: "shares", label: tr("My shares"), href: "/news/shares" },
          { id: "etf-top", label: tr("Top 5 in ETF's"), href: "/news/etfs" },
        ],
      },
    ],
  },
  {
    id: "account",
    label: "Account",
    items: [
      {
        id: "settings",
        label: tr("Settings"),
        href: "/account",
        icon: "settings",
        tabs: [
          { id: "account", label: "Account", href: "/account" },
          { id: "agents", label: "Agents", href: "/account/agents" },
          { id: "feedback", label: "Feedback", href: "/account/feedback" },
          { id: "admin", label: tr("Admin"), href: "/admin", adminOnly: true },
        ],
      },
      {
        // One place for all explanation, for both parts of the app, with the same
        // structure: getting started, bringing data in, how the figures work. The "?" on
        // every screen and the explanation in Update point here.
        id: "help",
        label: "Help",
        href: "/help",
        icon: "help",
        tabs: [
          { id: "start", label: tr("Getting started"), href: "/help" },
          { id: "portfolio", label: tr("Portfolio"), href: "/help/portfolio" },
          { id: "money", label: tr("Money"), href: "/help/money", beta: "money" },
        ],
      },
    ],
  },
];

type Access = { beta: string[]; isAdmin: boolean };

function allowed(x: { beta?: string; adminOnly?: boolean }, access: Access): boolean {
  if (x.beta && !access.beta.includes(x.beta) && !access.isAdmin) return false;
  if (x.adminOnly && !access.isAdmin) return false;
  return true;
}

/**
 * The sidebar as this user sees it.
 *
 * An item with tabs of which none is visible drops out. An item with exactly one
 * visible tab keeps its own name but gets no tab bar: one tab is not a choice.
 *
 * This is not access control. The API checks every beta flag and every admin
 * right itself, on every request — a hidden link is not a lock.
 */
export function visibleNav(access: Access): NavGroup[] {
  return SITE_NAV.map((group) => ({
    id: group.id,
    label: group.label,
    items: group.items
      .filter((item) => allowed(item, access))
      .map((item) => {
        if (!item.tabs) return item;
        const tabs = item.tabs.filter((t) => allowed(t, access));
        return { ...item, tabs, href: tabs[0]?.href ?? item.href };
      })
      .filter((item) => !item.tabs || item.tabs.length > 0),
  })).filter((group) => group.items.length > 0);
}

/**
 * The item this address belongs to, with its tabs.
 *
 *  First an exact match, then the longest address that fits: in wealth-tracker
 *  /spending and /spending/budget are each an item of their own, and
 *  /spending/budget belongs to Budget, not to the first item that looks like it.
 */
export function findItem(groups: NavGroup[], pathname: string): NavItem | null {
  const items = groups.flatMap((g) => g.items);
  for (const item of items) {
    if ([item.href, ...(item.tabs?.map((t) => t.href) ?? [])].includes(pathname)) return item;
  }
  let best: NavItem | null = null;
  let bestLen = -1;
  for (const item of items) {
    const paths = [item.href, ...(item.tabs?.map((t) => t.href) ?? [])].map((p) => `${p}/`);
    for (const p of [...paths, ...(item.extraPaths ?? [])]) {
      if (pathname.startsWith(p) && p.length > bestLen) {
        best = item;
        bestLen = p.length;
      }
    }
  }
  return best;
}

/** The active tab within an item — the longest address that fits this path. */
export function findTab(item: NavItem | null, pathname: string): NavTab | null {
  if (!item?.tabs) return null;
  const exact = item.tabs.find((t) => t.href === pathname);
  if (exact) return exact;
  return [...item.tabs].sort((a, b) => b.href.length - a.href.length).find((t) => pathname.startsWith(`${t.href}/`)) ?? null;
}
