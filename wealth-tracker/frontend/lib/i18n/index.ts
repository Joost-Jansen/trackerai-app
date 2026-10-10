// Dutch and English, no library. The code holds the English text; lib/i18n/nl.ts maps each English text to its
// Dutch version.
//
//   tr("Save")                          -> "Opslaan" / "Save"
//   tr("{0} accounts", n)               -> "3 rekeningen" / "3 accounts"
//   trx("Click {0} to go on.", <b>…</b>) -> a ReactNode, for a sentence with an element in it
//
// Adding a text: write it in English in tr()/trx(), add the Dutch to nl.ts, run `npm run check:i18n`. The
// placeholders {0}, {1}… are the arguments in order; a translation may move them around.
//
// Names that are data stay as they are: category names, account names, ISINs and the like.

import { createElement, Fragment, type ReactNode } from "react";
import { text } from "./tr";

export { tr } from "./tr";
export { locale, intlLocale, LOCALES, type Locale } from "./locale";

/** Like tr, but the arguments may be elements: returns a fragment. */
export function trx(english: string, ...args: ReactNode[]): ReactNode {
  const parts: ReactNode[] = [];
  const re = /\{(\d+)\}/g;
  const s = text(english);
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > last) parts.push(s.slice(last, m.index));
    parts.push(Number(m[1]) < args.length ? args[Number(m[1])] : m[0]);
    last = m.index + m[0].length;
  }
  if (last < s.length) parts.push(s.slice(last));
  return createElement(Fragment, null, ...parts);
}
