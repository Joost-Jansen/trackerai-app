import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import "./globals.css";
import Providers from "./providers";
import { fontVariables } from "@trackerai/ui/lib/fonts";
import { APP } from "@/lib/app";
import { LOCALE_INIT_SCRIPT } from "@/lib/i18n/locale";

// The name in the browser tab and in a bookmark. The same spelling as the
// wordmark in the sidebar and as the domain.
//
// appleWebApp makes an iPhone open the site as an app instead of as a tab, with
// `title` as the name under the icon. We do not get the status bar: statusBarStyle
// is deliberately left out, because "black-translucent" slides the page *under*
// the clock and the app nowhere calculates with safe-area insets. Without that
// setting iOS keeps the bar clear and colours it with themeColor below.
//
// The icon itself is app/icon.png (browser) and app/apple-icon.png (home screen)
// next to this file; Next adds those links itself.
export const metadata: Metadata = {
  title: APP.name,
  applicationName: APP.name,
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: APP.name,
  },
};

// Next injects width=device-width by itself, but not themeColor — and the two
// belong together: without it a phone paints the browser chrome around a dark
// app in default light grey. maximumScale is deliberately left alone; capping
// pinch-zoom to make a layout "look right" is an accessibility regression, and
// the layout no longer needs it to stay inside the screen.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    // Meridian's paper (--n-25) and its night-time counterpart.
    { media: "(prefers-color-scheme: light)", color: APP.paper.light },
    { media: "(prefers-color-scheme: dark)", color: APP.paper.dark },
  ],
};

// Runs before first paint so a saved theme choice never flashes the other
// theme. No saved choice -> no data-theme attribute -> the CSS @media block
// answers to the OS preference.
const themeInit = `
try {
  var t = localStorage.getItem("theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
`;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // The Content Security Policy only lets scripts with this request's nonce run
  // (proxy.ts); reading it also makes every page render per request.
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
