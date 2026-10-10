// Builds the site icons from the brand mark (components/ds/Logomark.tsx).
//
//   node scripts/build-icons.mjs              writes app/icon.svg, app/apple-icon.png, public/icons/*.png
//   node scripts/build-icons.mjs --preview p  also writes a 64x64 preview PNG to p
//
// Rendering uses sharp, which Next.js already installs; no extra dependency.
// Run from web/. Commit the generated files.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");

const INK = "#26362f"; // --surface-ink, the dark sidebar
const LINE = "#eaf1ec"; // off-white
const DOT = "#8cb9a0"; // light sage

// The Logomark path and dot (viewBox 0 0 32 24). Its drawn extent incl. stroke
// is roughly x 0.3..30.5, y 4.8..22.2; centre (15.4, 13.5).
const CX = 15.4;
const CY = 13.5;

function mark(scale) {
  const tx = (16 - scale * CX).toFixed(2);
  const ty = (16 - scale * CY).toFixed(2);
  return (
    `<g transform="translate(${tx} ${ty}) scale(${scale})">` +
    `<path d="M1.5 14h6l2.5-8 4 15 3-10 2 3h4.5" fill="none" stroke="${LINE}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>` +
    `<circle cx="26.5" cy="14" r="4" fill="${DOT}"/>` +
    `</g>`
  );
}

// rounded: a soft tile with transparent corners (favicon, manifest "any").
// full-bleed: square, no transparency (apple-touch-icon, manifest "maskable";
// the OS applies its own mask).
function svg({ rounded, scale }) {
  const tile = rounded
    ? `<rect class="tile" width="32" height="32" rx="7.5" fill="${INK}"/>`
    : `<rect width="32" height="32" fill="${INK}"/>`;
  // On a dark tab bar the ink tile gets a faint light edge so its shape still reads.
  const style = rounded
    ? `<style>@media (prefers-color-scheme: dark){.tile{stroke:#4d6a5b;stroke-width:1}}</style>`
    : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${style}${tile}${mark(scale)}</svg>\n`;
}

const favicon = svg({ rounded: true, scale: 0.9 });
const fullBleed = svg({ rounded: false, scale: 0.78 });
// Maskable: keep the mark inside the 80% safe circle (diagonal of its box <= 25.6).
const maskable = svg({ rounded: false, scale: 0.64 });

async function png(source, size, out, { opaque = false } = {}) {
  mkdirSync(dirname(out), { recursive: true });
  let img = sharp(Buffer.from(source), { density: (72 * size) / 32 }).resize(size, size);
  // apple-touch-icon and maskable: drop the alpha channel entirely.
  if (opaque) img = img.flatten({ background: INK });
  await img.png({ compressionLevel: 9 }).toFile(out);
  console.log(`${out.replace(WEB + "/", "")}  ${size}x${size}`);
}

writeFileSync(join(WEB, "app/icon.svg"), favicon);
console.log("app/icon.svg");
await png(fullBleed, 180, join(WEB, "app/apple-icon.png"), { opaque: true });
await png(favicon, 192, join(WEB, "public/icons/icon-192.png"));
await png(favicon, 512, join(WEB, "public/icons/icon-512.png"));
await png(maskable, 512, join(WEB, "public/icons/icon-maskable-512.png"), { opaque: true });

const i = process.argv.indexOf("--preview");
if (i > 0 && process.argv[i + 1]) await png(favicon, 64, process.argv[i + 1]);
