/** @type {import('next').NextConfig} */
// tabstealth-web; tabstealth-api answers /api/* behind it. Shared code comes from packages/ as TypeScript source
// (transpilePackages); the workspace root is the repo root, where the one lockfile is.
const path = require("path");
const root = path.join(__dirname, "../..");

module.exports = {
  outputFileTracingRoot: root,
  turbopack: { root },
  transpilePackages: ["@trackerai/ui"],
  trailingSlash: true,
  skipTrailingSlashRedirect: true,
  poweredByHeader: false,
  async headers() {
    // The player embeds the YouTube video and loads alphaTab (the tab renderer and synth) from jsDelivr.
    const csp = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://www.youtube.com https://s.ytimg.com",
      "worker-src 'self' blob: https://cdn.jsdelivr.net",
      "style-src 'self' 'unsafe-inline'",
      "font-src 'self' data: https://cdn.jsdelivr.net",
      "img-src 'self' data: https://i.ytimg.com",
      "media-src 'self' blob:",
      "connect-src 'self' https://cdn.jsdelivr.net",
      "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com", // 'self': the PDF viewer
    ].join("; ");
    return [{
      source: "/:path*",
      headers: [
        { key: "Content-Security-Policy", value: csp },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      ],
    }];
  },
  async rewrites() {
    const apiUrl = process.env.API_INTERNAL_URL || "http://127.0.0.1:8770";
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};
