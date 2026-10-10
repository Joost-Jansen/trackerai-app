// trackerai.nl: the front door of the trackers (app/page.tsx) and the admin page for every tracker (app/admin).
import type { Metadata, Viewport } from "next";
import { cookies, headers } from "next/headers";
import { LOCALE_COOKIE, localeFromCookie } from "@trackerai/marketing";
import { fontVariables } from "@trackerai/ui/lib/fonts";
import "./globals.css";
import "@trackerai/marketing/marketing.css";

export const metadata: Metadata = {
  title: "trackerai",
  description: "Your health and your money in two private dashboards that fill themselves, with one account and your own AI agent.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f4ef" },
    { media: "(prefers-color-scheme: dark)", color: "#161512" },
  ],
};

// Before first paint, so a theme chosen in a tracker (the same localStorage key on this origin) never flashes the
// other one. No saved choice: the CSS follows the system.
const themeInit = `
try {
  var t = localStorage.getItem("theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
`;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // The Content Security Policy only lets scripts with this request's nonce run (proxy.ts).
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  const lang = localeFromCookie((await cookies()).get(LOCALE_COOKIE)?.value);
  return (
    <html lang={lang} className={fontVariables} suppressHydrationWarning>
      <body>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeInit }} />
        {children}
      </body>
    </html>
  );
}
