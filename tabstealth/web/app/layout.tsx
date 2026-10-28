import type { Metadata, Viewport } from "next";
import "./globals.css";
import Providers from "./providers";
import { fontVariables } from "@trackerai/ui/lib/fonts";
import { LOCALE_INIT_SCRIPT } from "@trackerai/ui/i18n/locale";

export const metadata: Metadata = {
  title: "tabstealth",
  applicationName: "tabstealth",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8f8fb" },
    { media: "(prefers-color-scheme: dark)", color: "#100f17" },
  ],
};

// Before the first paint, so a saved theme choice never flashes the other theme.
const themeInit = `
try {
  var t = localStorage.getItem("theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="nl" className={fontVariables} suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeInit + LOCALE_INIT_SCRIPT }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
