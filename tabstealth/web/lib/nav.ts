// The site's navigation; the names come from lib/i18n (nav).

import type { NavGroup } from "@trackerai/ui/ds/SidebarNav";
import type { Messages } from "@/lib/i18n";

export const nav = (t: Messages): NavGroup[] => [
  {
    items: [
      { id: "library", label: t.nav.library, href: "/library/", icon: "list" },
      { id: "help", label: t.nav.help, href: "/help/", icon: "help" },
    ],
  },
];


/** Slots in the top bar that a page can fill with its own title and controls (the song page). */
export const TOPBAR_TITLE = "topbar-title";
export const TOPBAR_ACTIONS = "topbar-actions";
