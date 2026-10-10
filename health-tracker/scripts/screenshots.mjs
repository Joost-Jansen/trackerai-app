// Retake the README screenshots (docs/screenshots/*.jpg) from a running instance with the synthetic demo user.
//
//   DATABASE_URL=sqlite:///demo.db DEMO_PASSWORD=... python scripts/seed_demo.py --reset
//   (start the API on :8000 against demo.db, see README "Try it locally with demo data")
//   DEMO_PASSWORD=... node scripts/screenshots.mjs [--base http://localhost:8000] [--locale en] [--out docs/screenshots]
//
// Needs Playwright (`npm i -g playwright`, or run it with `npx -p playwright node scripts/screenshots.mjs`).
// Sets the demo account's language to --locale first, so the screenshots match the README (English).
// Map tiles come from tile.openstreetmap.org; without network access to it the maps show a plain background.
// Behind an HTTPS proxy (HTTPS_PROXY set) the tiles are fetched through it from Node.

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
    base: { type: "string", default: "http://localhost:8000" },
    locale: { type: "string", default: "en" },
    out: { type: "string", default: "docs/screenshots" },
    user: { type: "string", default: "demo" },
  },
});
const password = process.env.DEMO_PASSWORD;
if (!password) throw new Error("set DEMO_PASSWORD (the password seed_demo.py printed or was given)");

const VIEWPORT = { width: 1600, height: 1000 };

const browser = await playwright.chromium.launch(
  process.env.PLAYWRIGHT_BROWSERS_PATH ? {} : { executablePath: process.env.CHROMIUM_PATH },
);
// Behind an HTTPS proxy (HTTPS_PROXY) Chromium may not trust its certificate, so fetch the map tiles
// from Node instead (which honours NODE_EXTRA_CA_CERTS) and hand them to the page.
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
const context = await browser.newContext({
  viewport: VIEWPORT,
  locale: opts.locale === "nl" ? "nl-NL" : "en-GB",
  ...(proxy ? { proxy: { server: proxy, bypass: "localhost,127.0.0.1" } } : {}),
});
if (proxy) {
  await context.route("https://tile.openstreetmap.org/**", async (route) =>
    route.fulfill({ response: await route.fetch() }),
  );
}

// Log in and set the account language through the API; the session cookie is shared with the pages.
const api = context.request;
const login = await api.post(`${opts.base}/api/login`, { data: { username: opts.user, password } });
if (!login.ok()) throw new Error(`login failed: ${login.status()} ${await login.text()}`);
await api.patch(`${opts.base}/api/account`, { data: { locale: opts.locale } });
await context.addInitScript(
  ([locale]) => {
    localStorage.setItem("locale", locale);
    if (!localStorage.getItem("theme")) localStorage.setItem("theme", "light");
  },
  [opts.locale],
);

const page = await context.newPage();
await mkdir(opts.out, { recursive: true });

async function settle() {
  await page.waitForLoadState("networkidle").catch(() => {});
  // charts and maps draw after the data arrives; give fonts, Leaflet and tiles a moment
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1200);
}

// `height`: a taller window for pages whose interesting part does not fit in 1000px.
async function open(path, height = VIEWPORT.height) {
  await page.setViewportSize({ width: VIEWPORT.width, height });
  await page.goto(`${opts.base}${path}`);
  await settle();
}

async function shot(name) {
  await page.screenshot({ path: `${opts.out}/${name}.jpg`, type: "jpeg", quality: 85 });
  console.log(`${opts.out}/${name}.jpg`);
}

// The first link on a list page that points at a detail page (the newest activity, the most-run route).
async function firstLink(prefix) {
  const href = await page.locator(`a[href^="${prefix}"]`).first().getAttribute("href");
  if (!href) throw new Error(`no link to ${prefix} found`);
  return href;
}

await open("/dashboard/");
await shot("dashboard");

await open("/history/");
await shot("history");
const run = await page
  .locator('a[href^="/history/activity/?id="]', { hasText: opts.locale === "nl" ? "Hardlopen" : "Run" })
  .first()
  .getAttribute("href")
  .catch(() => null);
await open(run ?? (await firstLink("/history/activity/?id=")), 1444);
await shot("activity");

await open("/trends/");
await shot("trends");

await open("/routes/");
await shot("routes");
await open(await firstLink("/routes/route/?"));
await shot("route");

await open("/plan/");
await shot("plan");
// The latest week with sessions done, each matched to its activity (on a Monday "this week" has nothing done yet).
await open("/plan/", 1222);
const weeks = page.locator("section:has(> button[aria-expanded])");
const headers = await weeks.locator("> button").allInnerTexts();
const doneIn = (text) => Number((text.match(/(\d+)\s*\/\s*\d+/) ?? [0, 0])[1]);
const pick = headers.map(doneIn).findLastIndex((n, i) => n > 0 && doneIn(headers[i + 1] ?? "") === 0);
const week = weeks.nth(Math.max(pick, 0));
const toggle = week.locator("> button");
if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
await week.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 70));
await page.waitForTimeout(600);
await shot("plan-week");

await open("/settings/zones/");
await shot("zones");

// a fresh token shows the connector URL and the `claude mcp add` command (a token in the local demo database only)
await open("/settings/agents/");
await page.locator("form button[type=submit], button", { hasText: opts.locale === "nl" ? "Nieuw token" : "New token" }).first().click();
await settle();
await shot("agents");

await page.evaluate(() => localStorage.setItem("theme", "dark"));
await open("/dashboard/");
await shot("dashboard-dark");

await browser.close();
