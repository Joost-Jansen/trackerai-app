// This site's name and look: wealth-tracker.
//
// Your wealth first (net worth, spending, accounts) and the portfolio below it.
// The code for it stays "money" (the beta flag, the feedback app code): codes stay
// codes.

import { tr } from "@/lib/i18n";

type Brand = {
  /** Name in tab, sidebar, manifest and on the login screen. Lowercase and hyphen. */
  name: string;
  /** One line below the name on the login screen and in the manifest. */
  tagline: string;
  /** Where the app opens after logging in and on "/". */
  home: string;
  /** Page colour light and dark: the browser's themeColor and a phone's splash screen. */
  paper: { light: string; dark: string };
};

export const APP: Brand = {
  name: "wealth-tracker",
  tagline: tr("Your net worth, spending and portfolio, in one place."),
  home: "/net-worth",
  paper: { light: "#f9f8f4", dark: "#15130e" },
};
