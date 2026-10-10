/** @type {import('next').NextConfig} */
const path = require("path");
// The repo root: the npm workspace with the one lockfile. Shared code comes from packages/ as TypeScript source
// (transpilePackages). The standalone output mirrors the repo from there: .next/standalone/trackerai/web/server.js.
const root = path.join(__dirname, "../..");

const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: root,
  turbopack: { root },
  transpilePackages: ["@trackerai/ui", "@trackerai/marketing"],
  poweredByHeader: false,
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
    // trackerai-api answers /api/* (the account, the admin's tools and /api/hub to each tracker). Next freezes the
    // address at build time, hence the build argument in the Dockerfile.
    const apiUrl = process.env.API_INTERNAL_URL || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

module.exports = nextConfig;
