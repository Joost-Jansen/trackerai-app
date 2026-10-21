// Retake the README screenshots (docs/screenshots/*.jpg) from a running instance with the demo account.
//
//   DEMO_PASSWORD=... python scripts/seed_demo.py --reset
//   (start the API on :8000 and the frontend on :3000, see README "Try it locally with demo data")
//   DEMO_PASSWORD=... node scripts/screenshots.mjs [--base http://localhost:3000] [--locale en] [--out docs/screenshots]
//
// Needs Playwright (`npm i -g playwright`, or run it with `npx -p playwright node scripts/screenshots.mjs`).
// Sets the demo account's language to --locale first and marks the welcome tour done, so the pages show as a
// returning user sees them.

import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { parseArgs } from "node:util";

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require("playwright");
} catch {
  // a global install is not on the module path of an ES module
  const { execSync } = await import("node:child_process");
  playwright = require(`${execSync("npm root -g").toString().trim()}/playwright`);
}

const { values: opts } = parseArgs({
  options: {
    base: { type: "string", default: "http://localhost:3000" },
    locale: { type: "string", default: "en" },
    out: { type: "string", default: "docs/screenshots" },
    user: { type: "string", default: "demo" },
  },
});
const password = process.env.DEMO_PASSWORD;
if (!password) throw new Error("set DEMO_PASSWORD (the password seed_demo.py printed or was given)");

const VIEWPORT = { width: 1600, height: 1000 };

const browser = await playwright.chromium.launch();
const context = await browser.newContext({ viewport: VIEWPORT, locale: opts.locale === "nl" ? "nl-NL" : "en-GB" });

// Log in, set the language and finish the tour through the API; the session cookie is shared with the pages.
const api = context.request;
const headers = { origin: opts.base };
const login = await api.post(`${opts.base}/api/auth/login`, { data: { username: opts.user, password }, headers });
if (!login.ok()) throw new Error(`login failed: ${login.status()} ${await login.text()}`);
await api.put(`${opts.base}/api/auth/me/locale`, { data: { locale: opts.locale }, headers });
await api.put(`${opts.base}/api/onboarding`, { data: { choice: "both", done: true }, headers });
await context.addInitScript(() => {
  if (!localStorage.getItem("theme")) localStorage.setItem("theme", "light");
});

const page = await context.newPage();
await mkdir(opts.out, { recursive: true });

async function open(path, height = VIEWPORT.height) {
  await page.setViewportSize({ width: VIEWPORT.width, height });
  await page.goto(`${opts.base}${path}`);
  await page.waitForLoadState("networkidle").catch(() => {});
  // `next dev` shows its own badge in a corner; it is not part of the app
  await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
  // charts draw after the data arrives; give fonts and charts a moment
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1500);
}

async function shot(name) {
  await page.screenshot({ path: `${opts.out}/${name}.jpg`, type: "jpeg", quality: 85 });
  console.log(`${opts.out}/${name}.jpg`);
}

await open("/net-worth");
await shot("net-worth");
await open("/spending/budget");
await shot("budget");
await open("/spending/transactions");
await shot("transactions");
await open("/spending");
await shot("spending");
await open("/dashboard");
await shot("dashboard");
await open("/portfolio");
await shot("portfolio");
await open("/returns");
await shot("benchmarks");
await open("/dividend");
await shot("dividend");

await page.evaluate(() => localStorage.setItem("theme", "dark"));
await open("/dashboard");
await shot("dashboard-dark");

await browser.close();
