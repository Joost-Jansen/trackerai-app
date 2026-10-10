// The three typeface families of the Meridian design.
//
// Meridian prescribes Söhne (interface), Founders Grotesk Text (large numbers)
// and Söhne Mono. Those are Klim typefaces of which the handoff package only
// includes *trial versions*; those may not go to a public site. These are the
// free replacements, with the same division of roles:
//
//   Inter          → Söhne          neutral, engineered interface grotesk
//   Hanken Grotesk → Founders Text  warmer and a bit more idiosyncratic at
//                                   large sizes, with a real Light (300) — exactly
//                                   what the hero number needs
//   IBM Plex Mono  → Söhne Mono     tickers, ISINs, times
//
// If you want the real Klim cuts later after all: replace the files in `fonts/`
// and the paths below. Nothing else changes — the rest of the app only reads
// --font-sans / --font-display / --font-mono.
//
// Only the latin subset. That covers the whole Dutch alphabet including the
// accents (é ë ï ö ü are in Latin-1); for a single Eastern European character in
// a fund name the browser falls back on the system font. That costs 103 kB
// instead of 226 kB, on every page.
//
// next/font/local and not next/font/google: the files are in the repo, so the
// Docker build needs no network and the user no connection with Google. Next
// bundles them in .next/static/media, and *that* path the Dockerfile already
// copies — a public/ folder it would skip.

import localFont from "next/font/local";

export const interSans = localFont({
  src: [{ path: "../../fonts/Inter-300-600-latin.woff2", weight: "300 600", style: "normal" }],
  variable: "--font-sans-loaded",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
});

export const hankenDisplay = localFont({
  src: [{ path: "../../fonts/HankenGrotesk-300-600-latin.woff2", weight: "300 600", style: "normal" }],
  variable: "--font-display-loaded",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
});

export const plexMono = localFont({
  src: [
    { path: "../../fonts/IBMPlexMono-400-latin.woff2", weight: "400", style: "normal" },
    { path: "../../fonts/IBMPlexMono-500-latin.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-mono-loaded",
  display: "swap",
  fallback: ["ui-monospace", "SF Mono", "Menlo", "monospace"],
});

/** The three classes Next wants to see on <html>. */
export const fontVariables = `${interSans.variable} ${hankenDisplay.variable} ${plexMono.variable}`;
