/** @type {import('next').NextConfig} */
const path = require("path");
// The repo root: the npm workspace with the one lockfile. Shared code comes
// from packages/ as TypeScript source (transpilePackages). The standalone
// output mirrors the repo from there: .next/standalone/wealth-tracker/frontend/server.js.
const root = path.join(__dirname, "../..");

const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: root,
  turbopack: { root },
  transpilePackages: ["@trackerai/ui", "@trackerai/marketing"],
  // The proxy to the API cut a request off after 30 seconds ("socket hang up").
  // Claude rounds are short on purpose, but a slow one must not fail silently
  // while the API carries on.
  experimental: { proxyTimeout: 120_000 },
  // Don't announce the framework in every response.
  poweredByHeader: false,
  async headers() {
    // On every response, static files included. The Content Security Policy
    // itself is per request (it carries a nonce) and comes from proxy.ts.
    // HSTS only in production: a browser ignores it over plain http anyway,
    // and on https it keeps the next visit from ever trying http first.
    const common = [
      { key: "X-Frame-Options", value: "DENY" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
      { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
    ];
    if (process.env.NODE_ENV === "production") {
      common.push({ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" });
    }
    return [{ source: "/:path*", headers: common }];
  },
  async redirects() {
    // Addresses from before the English rename, and the ETF analysis tab that
    // became Allocation. Permanent: a bookmark or a shared link from that time
    // keeps working. The longer paths come first.
    const renamed = [
      ["/etf-analysis", "/allocation"],
      // Benchmarks moved onto Returns, under the same period.
      ["/benchmarks", "/returns"],
      ["/rekeningen/koppelen", "/accounts/connect"],
      ["/rekeningen", "/accounts"],
      ["/uitgaven/transacties", "/spending/transactions"],
      ["/uitgaven/labelen", "/spending/labelling"],
      ["/uitgaven/vaste-lasten", "/spending/fixed-costs"],
      ["/uitgaven/budget", "/spending/budget"],
      ["/uitgaven", "/spending"],
      ["/categorieen", "/categories"],
      ["/vermogen", "/net-worth"],
      ["/portefeuille/:isin", "/portfolio/:isin"],
      ["/portefeuille", "/portfolio"],
      ["/rendement", "/returns"],
      ["/spreiding", "/allocation"],
      ["/kalender", "/calendar"],
      ["/nieuws/aandelen", "/news/shares"],
      ["/nieuws/:path*", "/news/:path*"],
      ["/help/geldzaken", "/help/money"],
      ["/help/portefeuille", "/help/portfolio"],
      ["/uitleg", "/explainer"],
      ["/voorwaarden", "/terms"],
    ];
    const redirects = renamed.map(([source, destination]) => ({ source, destination, permanent: true }));
    return redirects;
  },
  async rewrites() {
    // Behind Caddy (the Pi) this never fires: Caddy routes /api/* straight to
    // the FastAPI container (see deploy/Caddyfile.beta). Under `next dev` and
    // on Railway, where there is no Caddy, this is how /api/* reaches the API.
    // Next freezes the value at build time, hence the build arg in Dockerfile.
    const apiUrl = process.env.API_INTERNAL_URL || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
      { source: "/.well-known/:path*", destination: `${apiUrl}/.well-known/:path*` },
    ];
  },
};

module.exports = nextConfig;
