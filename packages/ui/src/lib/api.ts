// The fetch wrapper of both apps: always same-origin (`/api/...`), always with the httpOnly session cookie. In
// production the proxy routes /api/* to the backend; under `next dev`, next.config.js rewrites it there. Either way
// the frontend never needs to know the backend's real address.
//
// Each app makes its own with createApi(): the headers it adds (its language, example data) and the errors whose
// server message it replaces.

import { recordError } from "@trackerai/ui/lib/recentErrors";

export class ApiError extends Error {
  status: number;
  /** A stable code for errors the app reacts to ("totp_required", "csrf_origin", …), from the backend's errors module. */
  code?: string;
  /** What the code's message needs filled in ({ minutes: 15 }). */
  params?: Record<string, unknown>;
  constructor(status: number, message: string, code?: string, params?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.params = params;
  }
}

export type ApiOptions = {
  /** Extra headers for a request to `path`: the language, example data. */
  headers?: (path: string) => Record<string, string>;
  /** A message of the app's own for an error code (null: the server's message). */
  message?: (code: string | undefined) => string | null;
};

export function createApi({ headers, message }: ApiOptions = {}) {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(path, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...headers?.(path), ...(init?.headers || {}) },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const code = typeof body.code === "string" ? body.code : undefined;
      const detail = typeof body.detail === "string" && body.detail ? body.detail : undefined;
      if (res.status !== 401)
        recordError(`${res.status} ${code ?? detail ?? res.statusText}`, {
          where: `${init?.method ?? "GET"} ${path.split("?")[0]}`,
          status: res.status,
        });
      throw new ApiError(res.status, message?.(code) ?? detail ?? res.statusText, code, body.params);
    }
    return res.json() as Promise<T>;
  }
  const json = (method: string, body?: unknown): RequestInit => ({ method, body: body ? JSON.stringify(body) : undefined });
  return {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body?: unknown) => request<T>(path, json("POST", body)),
    put: <T>(path: string, body?: unknown) => request<T>(path, json("PUT", body)),
    patch: <T>(path: string, body?: unknown) => request<T>(path, json("PATCH", body)),
    del: <T>(path: string, body?: unknown) => request<T>(path, json("DELETE", body)),
    /** A file as the raw body (an upload): no multipart needed on the server. */
    upload: <T>(path: string, file: Blob) =>
      request<T>(path, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  };
}

/**
 * Example data: while the first-run walk shows a page, data requests carry `X-Example-Data: 1` and the API answers
 * them from a shared, read-only example account. Paths under `personal` never carry it (who you are, your account,
 * the onboarding state that drives the walk); an app whose backend decides that itself passes none.
 */
export function createExampleData(personal: string[] = []) {
  let on = false;
  const listeners = new Set<() => void>();
  return {
    set(value: boolean) {
      if (on === value) return;
      on = value;
      listeners.forEach((fn) => fn());
    },
    isOn: () => on,
    subscribe(fn: () => void): () => void {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    header(path: string): Record<string, string> {
      const bare = path.split("?")[0];
      const mine = personal.some((p) => bare === p || bare.startsWith(p + "/"));
      return on && !mine ? { "X-Example-Data": "1" } : {};
    },
  };
}
