// A login may resume only our consent page, never an arbitrary redirect URL.
export function consentReturn(search: string): string | null {
  const next = new URLSearchParams(search).get("next");
  if (!next) return null;
  try {
    const url = new URL(next, "https://local.invalid");
    const request = url.searchParams.get("request");
    if (
      url.origin !== "https://local.invalid" ||
      !["/connect", "/connect/"].includes(url.pathname) ||
      url.hash ||
      !request ||
      !/^[A-Za-z0-9_-]{43}$/.test(request)
    )
      return null;
    return `/connect/?request=${request}`;
  } catch {
    return null;
  }
}

export function loginReturn(fallback: string): string {
  return typeof window === "undefined" ? fallback : (consentReturn(window.location.search) ?? fallback);
}
