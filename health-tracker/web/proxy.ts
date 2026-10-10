// Security headers for every page request, with a Content Security Policy that allows only scripts carrying this
// request's nonce. Next reads the nonce from the request's Content-Security-Policy header and puts it on its own
// scripts; app/layout.tsx reads `x-nonce` for the one inline script of our own (theme and language before first
// paint). Styles keep 'unsafe-inline': React writes style="" attributes and Leaflet positions map tiles with inline
// styles; neither can carry a nonce. /api/* is not matched: health-api sets its own, stricter headers.
import { NextResponse, type NextRequest } from "next/server";

function contentSecurityPolicy(nonce: string): string {
  const dev = process.env.NODE_ENV === "development";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    // Map tiles (components/map/useTheme.ts); data: and blob: for the feedback screenshot (html-to-image) and icons.
    "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "manifest-src 'self'",
    "worker-src 'self' blob:",
  ].join("; ");
}

export function proxy(request: NextRequest) {
  // A page path without its trailing slash (next.config.js); a path with a dot is a file.
  // As a plain header: NextResponse.redirect() would take the slash off again. The host the visitor used, not the
  // address this server listens on.
  const { pathname, search } = request.nextUrl;
  if (!pathname.endsWith("/") && !pathname.split("/").pop()!.includes(".")) {
    const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? request.nextUrl.host;
    const proto = request.headers.get("x-forwarded-proto")?.split(",")[0].trim() ?? request.nextUrl.protocol.replace(":", "");
    const location = `${proto}://${host}${pathname}/${search}`;
    return new NextResponse(null, { status: 308, headers: { Location: location } });
  }
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: "/((?!api/|\\.well-known/|_next/static|_next/image|icons/|icon.svg|apple-icon.png|manifest.webmanifest).*)",
};
