// Makes the wealth-tracker app icons (app/icon.png, app/apple-icon.png) from the
// mark in components/ds/MoneyMark.tsx: a wallet with a coin as the clasp, on a
// dark tile. Run by hand; the output is in git and the build does not touch it.
//
//     node scripts/build-money-logo.mjs
//
// A tile without rounded corners and without transparency: iOS rounds itself and
// turns transparent corners black. Chromium (Playwright)
// draws; no image library is needed.

import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "app");
const SIZES = [
  { file: "apple-icon.png", size: 180 },
  { file: "icon.png", size: 512 },
];

// The same paths as in MoneyMark.tsx; one source to check.
const src = readFileSync(join(HERE, "..", "components", "ds", "MoneyMark.tsx"), "utf8");
const PATH = src.match(/MONEY_PATH = "([^"]+)"/)[1];
const COIN = src.match(/MONEY_COIN = \{ cx: ([\d.]+), cy: ([\d.]+), r: ([\d.]+) \}/).slice(1).map(Number);

// The site's colours: a walnut tile, a paper wallet and a terracotta coin.
const TILE = "#211e18";
const PAPER = "#f9f8f4";
const ACCENT = "#c4714b";

const svg = (size) => `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32">
  <rect width="32" height="32" fill="${TILE}"/>
  <g transform="translate(4.8 6.9) scale(0.7)">
    <path d="${PATH}" fill="none" stroke="${PAPER}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${COIN[0]}" cy="${COIN[1]}" r="${COIN[2]}" fill="${ACCENT}"/>
  </g>
</svg>`;

const require = createRequire(import.meta.url);
const pw = await import(pathToFileURL(require.resolve("playwright")).href);
const chromium = pw.chromium ?? pw.default?.chromium;
const browser = await chromium.launch();
for (const { file, size } of SIZES) {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  await page.setContent(`<html><body style="margin:0">${svg(size)}</body></html>`);
  await page.screenshot({ path: join(OUT, file), omitBackground: false });
  await page.close();
  console.log(`${size}×${size} → ${join(OUT, file)}`);
}
await browser.close();
