// Security headers for every page request, with a Content Security Policy that allows only scripts carrying this
// request's nonce. Next reads the nonce from the request's Content-Security-Policy header and puts it on its own
// scripts; app/layout.tsx reads `x-nonce` for the one inline script of our own (the theme before first paint).
// Styles keep 'unsafe-inline': style="" attributes cannot carry a nonce. /api/* is not matched: trackerai-api sets
// its own, stricter headers.
import { NextResponse, type NextRequest } from "next/server";
import { LOCALE_COOKIE } from "@trackerai/marketing";

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
  ].join("; ");
}

export function proxy(request: NextRequest) {
  // The language switch at the bottom of the front door: ?lang=en or ?lang=nl keeps the choice for a year and goes
  // back to the same page without it. English is the default; the browser's own language is not used.
  const lang = request.nextUrl.searchParams.get("lang");
  if (lang === "en" || lang === "nl") {
    const back = request.nextUrl.clone();
    back.searchParams.delete("lang");
    // To the address the browser used (its Host header), not the internal one the server sees behind the proxy.
    const host = request.headers.get("host") ?? "";
    const target = /^[a-z0-9.-]+(:\d+)?$/i.test(host)
      ? `${process.env.NODE_ENV === "production" ? "https" : "http"}://${host}${back.pathname}${back.search}`
      : back.toString();
    const response = NextResponse.redirect(target, 303);
    response.cookies.set(LOCALE_COOKIE, lang, {
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
    });
    return response;
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
  matcher: "/((?!api/|_next/static|_next/image|icon.svg).*)",
};
