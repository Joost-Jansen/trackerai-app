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

