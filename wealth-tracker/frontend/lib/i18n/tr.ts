// tr() without React, so plain modules (lib/format.ts, lib/dashboard.ts) and the node-driven tests can use it.
// See lib/i18n/index.ts.

import { locale } from "./locale";
import { nl } from "./nl";

/** The text in the current language, without filling in anything. */
export const text = (english: string): string => (locale === "nl" ? nl[english] ?? english : english);

/** The text in the current language, with {0}, {1}… filled in. */
export function tr(english: string, ...args: unknown[]): string {
  const s = text(english);
  return args.length ? s.replace(/\{(\d+)\}/g, (m, i) => (Number(i) < args.length ? String(args[Number(i)]) : m)) : s;
}
