// For running the app's .ts modules directly in node (the backend's parity tests, scripts/test-*.mjs): resolves
// "@/x" to the frontend root, "@trackerai/ui/x" to packages/ui by its package.json exports (so no npm install is
// needed, as in the backend's CI job), and an import without an extension to its .ts file, the way Next's bundler does.
//
//   node --import ./scripts/ts-resolve.mjs some-test.mjs
import { register } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const UI = path.resolve(ROOT, "../../packages/ui");
const UI_EXPORTS = JSON.parse(readFileSync(path.join(UI, "package.json"), "utf8")).exports;

/** "@trackerai/ui/lib/dates" -> packages/ui/src/lib/dates.ts, through the "./lib/*" export. */
function sharedPath(subpath) {
  for (const [key, target] of Object.entries(UI_EXPORTS)) {
    if (key === subpath) return path.join(UI, target);
    const star = key.indexOf("*");
    if (star >= 0 && subpath.startsWith(key.slice(0, star)) && subpath.endsWith(key.slice(star + 1))) {
      const middle = subpath.slice(star, subpath.length - (key.length - star - 1));
      return path.join(UI, target.replace("*", middle));
    }
  }
  return null;
}

export async function resolve(specifier, context, next) {
  let base = null;
  if (specifier.startsWith("@/")) base = path.join(ROOT, specifier.slice(2));
  else if (specifier.startsWith("@trackerai/ui/")) base = sharedPath(`./${specifier.slice("@trackerai/ui/".length)}`);
  else if ((specifier.startsWith("./") || specifier.startsWith("../")) && context.parentURL?.startsWith("file:") && !path.extname(specifier))
    base = path.resolve(path.dirname(fileURLToPath(context.parentURL)), specifier);
  if (base) {
    for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts")]) {
      if (path.extname(candidate) && existsSync(candidate)) return next(pathToFileURL(candidate).href, context);
    }
  }
  return next(specifier, context);
}

if (!import.meta.url.includes("?hooks")) register(`${import.meta.url}?hooks`);
