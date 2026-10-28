// Checks the translations. Run from web/: `npm run check:i18n`.
//
// Key parity: every key of lib/i18n/nl.ts exists in en.ts and the other way round, with the same kind (text,
// function with the same number of parameters, group), and no text is empty. Node 23+ imports the .ts directly.

import { nl } from "../lib/i18n/nl.ts";
import { en } from "../lib/i18n/en.ts";

const problems = [];
const kind = (v) => (typeof v === "function" ? `function(${v.length})` : v !== null && typeof v === "object" ? "group" : typeof v);

function compare(a, b, path, nameA, nameB) {
  for (const k of Object.keys(a)) {
    const p = path ? `${path}.${k}` : k;
    if (!(k in b)) {
      problems.push(`missing in ${nameB}: ${p}`);
      continue;
    }
    if (kind(a[k]) !== kind(b[k])) problems.push(`different kind at ${p}: ${kind(a[k])} vs ${kind(b[k])}`);
    else if (kind(a[k]) === "group") compare(a[k], b[k], p, nameA, nameB);
    else if (typeof a[k] === "string" && !a[k].trim()) problems.push(`empty text in ${nameA}: ${p}`);
  }
}

compare(nl, en, "", "nl", "en");
compare(en, nl, "", "en", "nl");

if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log("i18n ok: nl and en have the same keys");
