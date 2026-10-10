// Checks the translations. Run from web/: `npm run check:i18n` (also run by tests/test_i18n_web.py).
//
// 1. Key parity: every key of lib/i18n/nl.ts exists in en.ts and the other way round, with the same kind (text,
//    function with the same number of parameters, list, group). Same for the health texts: lib/texts.ts (T) against
//    lib/i18n/texts.en.ts. A Dutch text added to T without an English one fails here (the site shows Dutch meanwhile).
// 2. Hardcoded Dutch: string literals and JSX text in the converted files (CONVERTED) that contain common Dutch
//    words. A line that must stay Dutch can end with `// i18n-ignore`.

import { register } from "node:module";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
register("./ts-loader.mjs", pathToFileURL(join(WEB, "scripts/")));

const problems = [];

// ── 1. parity ─────────────────────────────────────────────────────────────────

const kind = (v) => (Array.isArray(v) ? "list" : typeof v === "function" ? `function(${v.length})` : v !== null && typeof v === "object" ? "group" : typeof v);

function compare(a, b, path, nameA, nameB) {
  for (const k of Object.keys(a)) {
    const p = path ? `${path}.${k}` : k;
    if (!(k in b)) {
      problems.push(`missing in ${nameB}: ${p}`);
      continue;
    }
    const ka = kind(a[k]);
    const kb = kind(b[k]);
    if (ka !== kb) problems.push(`different kind for ${p}: ${nameA} ${ka}, ${nameB} ${kb}`);
    else if (ka === "group") compare(a[k], b[k], p, nameA, nameB);
  }
  for (const k of Object.keys(b)) if (!(k in a)) problems.push(`missing in ${nameA}: ${path ? `${path}.${k}` : k}`);
}

const { nl } = await import("../lib/i18n/nl.ts");
const { en } = await import("../lib/i18n/en.ts");
const { T } = await import("../lib/texts.ts");
const { textsEn } = await import("../lib/i18n/texts.en.ts");
const { texts: _nlTexts, ...nlRest } = nl;
const { texts: _enTexts, ...enRest } = en;
compare(nlRest, enRest, "", "nl.ts", "en.ts");
compare(T, textsEn, "texts", "lib/texts.ts", "texts.en.ts");

// ── 2. hardcoded Dutch ───────────────────────────────────────────────────────

const CONVERTED = [
  "app/layout.tsx",
  "app/(app)/layout.tsx",
  "app/login",
  "app/register",
  "app/(app)/history",
  "app/(app)/routes",
  "app/(app)/plan",
  "app/(app)/log",
  "app/(app)/analyses",
  "app/(app)/settings",
  "app/(app)/help",
  "app/(app)/dashboard",
  "app/(app)/trends",
  "components/dashboard",
  "components/trends",
  "components/charts",
  "components/timefilter",
  "components/zones",
  "components/LanguageSwitch.tsx",
  "components/onboarding",
  "components/plan",
  "components/routes",
  "components/log",
  "components/map",
  "components/ds",
  "components/ZoneBar.tsx",
  "lib/nav.ts",
  "lib/onboarding.ts",
];

const DUTCH = /\b(de|het|een|je|jouw|jij|niet|nog|geen|voor|naar|met|van|bij|wordt|zijn|deze|dit|dat|wat|hoe|waar|ook|maar|uit|tot|keer|dagen|laden|opslaan|annuleren|bewerken|verwijderen|volgende|vorige|gebruiker|wachtwoord|instellingen|kies|vul|bekijk|zoek|gelopen|gefietst|hartslag|snelheid|afstand|uitleg|klaar|gekoppeld|koppelen)\b/i;

function files(p) {
  const full = join(WEB, p);
  if (statSync(full).isFile()) return [full];
  return readdirSync(full).flatMap((n) => files(join(p, n)));
}

function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .split("\n")
    .map((line) => (line.includes("i18n-ignore") ? "" : line.replace(/(^|[^:"'`\\])\/\/.*$/, "$1")))
    .join("\n");
}

const literal = /"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`|>([^<>{}]*[A-Za-z][^<>{}]*)</g;

for (const file of CONVERTED.flatMap(files).filter((f) => /\.(tsx?|mjs)$/.test(f))) {
  const src = stripComments(readFileSync(file, "utf8"));
  for (const m of src.matchAll(literal)) {
    const text = (m[1] ?? m[2] ?? m[3] ?? m[4] ?? "").replace(/\$\{[^}]*\}/g, " ");
    if (!text.trim() || /^[@./]/.test(text.trim()) || /^[\w-]+$/.test(text.trim())) continue;
    const word = DUTCH.exec(text);
    if (!word) continue;
    const line = src.slice(0, m.index).split("\n").length;
    problems.push(`Dutch text in ${relative(WEB, file)}:${line}: ${JSON.stringify(text.trim().slice(0, 70))}`);
  }
}

if (problems.length) {
  console.error(problems.map((p) => `  ${p}`).join("\n"));
  console.error(`check-i18n: ${problems.length} problem(s)`);
  process.exit(1);
}
console.log("check-i18n: nl and en have the same keys; no hardcoded Dutch in the converted files");
