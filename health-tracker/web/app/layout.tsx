import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import "./globals.css";
import Providers from "./providers";
import { fontVariables } from "@trackerai/ui/lib/fonts";
import { LOCALE_INIT_SCRIPT } from "@/lib/i18n/locale";

export const metadata: Metadata = {
  title: "health-tracker",
  applicationName: "health-tracker",
  appleWebApp: { capable: true, title: "health-tracker" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f9f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1412" },
  ],
};

// Before the first paint, so a saved theme choice never flashes the other theme. <html lang> also follows
// the language of this device right away (lib/i18n/locale.ts); Dutch is the default.
const themeInit = `
try {
  var t = localStorage.getItem("theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
`;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // The Content Security Policy only lets scripts with this request's nonce run (proxy.ts).
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="nl" className={fontVariables} suppressHydrationWarning>
      <body>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeInit + LOCALE_INIT_SCRIPT }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
