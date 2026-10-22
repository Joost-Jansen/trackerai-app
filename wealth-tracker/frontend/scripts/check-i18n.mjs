// Checks lib/i18n/nl.ts against the code: every tr("…")/trx("…") text has a Dutch entry with the same
// placeholders, and every entry is still used. A text that is the same in Dutch is listed with itself.
//
//   node scripts/check-i18n.mjs
import ts from "typescript";
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const catalogSrc = readFileSync(path.join(ROOT, "lib/i18n/nl.ts"), "utf8");
const catalog = new Map(
  [...catalogSrc.matchAll(/^ {2}("(?:[^"\\]|\\.)*"): ("(?:[^"\\]|\\.)*"),$/gm)].map((m) => [JSON.parse(m[1]), JSON.parse(m[2])]),
);

const files = execSync("git ls-files --cached --others --exclude-standard '*.ts' '*.tsx'", { cwd: ROOT, encoding: "utf8" })
  .trim()
  .split("\n");
const used = new Map(); // text -> first place
const dynamic = [];
for (const f of files) {
  const src = readFileSync(path.join(ROOT, f), "utf8");
  if (!/\btrx?\(/.test(src)) continue;
  const sf = ts.createSourceFile(f, src, ts.ScriptTarget.Latest, true, f.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const visit = (n) => {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && (n.expression.text === "tr" || n.expression.text === "trx")) {
      const a = n.arguments[0];
      const where = `${f}:${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}`;
      if (a && (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a))) {
        if (!used.has(a.text)) used.set(a.text, where);
      } else if (!f.startsWith("lib/i18n/")) dynamic.push(where);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
}
const placeholders = (s) => [...new Set(s.match(/\{\d+\}/g) ?? [])].sort().join(",");
const problems = [];
for (const [text, where] of used) {
  if (!catalog.has(text)) problems.push(`missing in nl.ts: ${JSON.stringify(text)} (${where})`);
  else if (placeholders(text) !== placeholders(catalog.get(text)))
    problems.push(`placeholders differ: ${JSON.stringify(text)} → ${JSON.stringify(catalog.get(text))}`);
}
for (const text of catalog.keys()) if (!used.has(text)) problems.push(`unused in nl.ts: ${JSON.stringify(text)}`);
for (const where of dynamic) problems.push(`tr() with a text that is not a literal, the check can't see it: ${where}`);
if (problems.length) {
  console.error(problems.join("\n"));
  console.error(`\n${problems.length} problem(s); ${used.size} texts, ${catalog.size} entries.`);
  process.exit(1);
}
console.log(`i18n ok: ${used.size} texts, all in nl.ts.`);
