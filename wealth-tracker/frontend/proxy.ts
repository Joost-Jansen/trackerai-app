// Every page request (/api/* is not matched: the API sets its own, stricter headers) gets security headers, with a
// Content Security Policy that allows only scripts carrying this request's nonce (S5). Next.js reads the nonce from
// the request's Content-Security-Policy header and puts it on its own scripts; app/layout.tsx reads `x-nonce` for the
// one inline script of our own (theme and language before first paint). That needs dynamic rendering, which the
// layout opts into by reading the request headers. Styles keep 'unsafe-inline': server-rendered style="" attributes
// are all over the design system, and a nonce cannot cover attributes. Scripts are what matters for XSS, and those get
// no 'unsafe-inline'.
//
// The front door (trackerai.nl) is no longer served here: it is trackerai/web (step 11 of docs/PLAN.md).
import { NextResponse, type NextRequest } from "next/server";

function contentSecurityPolicy(nonce: string): string {
  const dev = process.env.NODE_ENV === "development";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
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
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

// Static files skip the proxy.
export const config = {
  matcher: "/((?!api/|_next/static|_next/image|favicon.ico|icon.png|apple-icon.png|manifest.webmanifest).*)",
};
