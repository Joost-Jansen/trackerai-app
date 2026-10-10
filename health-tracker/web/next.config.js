/** @type {import('next').NextConfig} */
// A Next standalone server (health-web); health-api answers /api/* behind it. Shared code comes from packages/ as
// TypeScript source (transpilePackages); the workspace root is the repo root, where the one lockfile is. The standalone
// output mirrors the repo from there: .next/standalone/health-tracker/web/server.js.
const path = require("path");
const root = path.join(__dirname, "../..");

module.exports = {
  output: "standalone",
  outputFileTracingRoot: root,
  turbopack: { root },
  transpilePackages: ["@trackerai/ui", "@trackerai/marketing"],
  // Page URLs end in a slash (/history/, as the links do). Next's own redirect to that would also hit /api/* before
  // the rewrite below (the API's paths have none), so it is off and proxy.ts adds the slash for pages only.
  trailingSlash: true,
  skipTrailingSlashRedirect: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  // Apple imports and exports can take a while through the rewrite below (the default is 30 seconds).
  experimental: { proxyTimeout: 300_000 },
  async headers() {
    // On every response, static files included. The Content Security Policy itself is per request (it carries a
    // nonce) and comes from proxy.ts. HSTS only in production: a browser ignores it over plain http anyway.
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
  async rewrites() {
    // health-api answers /api/* and the OAuth metadata for agents (/.well-known). Behind Caddy (docker-compose.yml)
    // this never fires: Caddy routes those paths to the API itself. Next fixes the address at build time, hence the
    // build argument in the Dockerfile.
    const apiUrl = process.env.API_INTERNAL_URL || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
      { source: "/.well-known/:path*", destination: `${apiUrl}/.well-known/:path*` },
    ];
  },
};
