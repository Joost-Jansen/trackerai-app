// Bakes the world map for Allocation into one TypeScript file with ready-made
// SVG paths. Run by hand; the output is in git and the build does not touch it —
// the world's country borders change rarely enough not to be worth a network
// request per build.
//
//     node scripts/build-world-map.mjs
//
// Why like this, and not with a map library: the frontend has zero chart
// dependencies — every chart in this app is hand-drawn SVG. A runtime projection
// would ship d3-geo + topojson-client + the raw geometry (~250 kB) only to
// calculate the same answer on every page view. Projecting ahead of time leaves
// only the answer.
//
// Source: world-atlas 110m (Natural Earth, public domain), TopoJSON. Only needed
// here, so no dependency in package.json — the script fetches the file itself.
//
// Projection: Equal Earth (Šavrič, Patterson & Jenny 2018). Equal areas, which is
// a choice and not a detail: on this map how *much* you hold somewhere is in the
// shade, and a projection that draws Greenland four times too large (Mercator) or
// stretches the poles (equirectangular) still lets a light shade over an inflated
// area shout. Antarctica goes — nobody holds a position there, and it costs a
// fifth of the height.

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const SOURCE = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "lib", "worldGeo.ts");

/** Width of the viewBox. The height follows from the projection. */
const WIDTH = 1000;
/**
 * Douglas-Peucker in projected units. 0.3 on 1000 wide is a third of a pixel on a
 *  map that is ~600 px wide in the app: invisible, and it saves well over half
 *  the points.
 */
const TOLERANCE = 0.3;
/**
 * Rings smaller than this (px² on 1000 wide) drop out, unless it is a country's
 *  largest ring. Catches the loose rocks in the ocean that are one pixel at
 *  screen size anyway.
 */
const MIN_RING_AREA = 0.8;
/**
 * Below this area a country at screen size is too small to point at *and* too
 *  small to show its shade. Those countries get a dot, provided you hold
 *  something there. Calibrated on the Netherlands (35) and Switzerland (40) —
 *  those must get it, because together they can be a quarter of a portfolio —
 *  and on Greece (107) and Bangladesh (95), which do not need it.
 */
const TINY = 90;

// Countries the file does not draw separately but that can be in a portfolio —
// all too small for 110m geometry. They get a dot at their own coordinate;
// without this a position in Hong Kong or Singapore would disappear from the map
// without anything saying so.
const POINT_ONLY = {
  "Hong Kong": [114.17, 22.32],
  Singapore: [103.82, 1.35],
  Bermuda: [-64.78, 32.31],
  "Cayman Islands": [-81.25, 19.31],
  Jersey: [-2.11, 49.21],
  Guernsey: [-2.58, 49.46],
  Liechtenstein: [9.55, 47.17],
  Monaco: [7.42, 43.74],
  Malta: [14.44, 35.9],
  Mauritius: [57.55, -20.35],
  Cyprus: [33.36, 35.13],
  Bahrain: [50.55, 26.07],
};

// Natural Earth spells a handful of countries differently from the issuers'
// holdings files. The backend already normalises the latter
// (etf_holdings._COUNTRY_ALIASES); this is the bridge to the map.
const ATLAS_TO_APP = {
  "United States of America": "United States",
  "Bosnia and Herz.": "Bosnia and Herzegovina",
  "Central African Rep.": "Central African Republic",
  "Dem. Rep. Congo": "Democratic Republic of the Congo",
  "Dominican Rep.": "Dominican Republic",
  "Eq. Guinea": "Equatorial Guinea",
  "Falkland Is.": "Falkland Islands",
  "S. Sudan": "South Sudan",
  "Solomon Is.": "Solomon Islands",
  "W. Sahara": "Western Sahara",
  "Fr. S. Antarctic Lands": "French Southern Territories",
  "N. Cyprus": "Northern Cyprus",
  Macedonia: "North Macedonia",
  eSwatini: "Eswatini",
  "Côte d'Ivoire": "Ivory Coast",
};

// Left off the map. Antarctica and the French Southern Territories are left out
// for the same reason: no listed company, a lot of height.
const DROP = new Set(["Antarctica", "Fr. S. Antarctic Lands"]);

// ---------------------------------------------------------------------------
// Unpacking TopoJSON. Twenty lines, so no reason to install topojson-client too:
// arcs are quantised deltas, and we use nothing more than that.
// ---------------------------------------------------------------------------

function decodeArcs(topology) {
  const { scale, translate } = topology.transform;
  return topology.arcs.map((arc) => {
    let x = 0;
    let y = 0;
    return arc.map(([dx, dy]) => {
      x += dx;
      y += dy;
      return [x * scale[0] + translate[0], y * scale[1] + translate[1]];
    });
  });
}

/**
 * A ring from a list of arc indices. Negative index = that arc reversed (~i, so
 *  -1 is arc 0 reversed). The end point of each arc is the start point of the
 *  next, hence the slice(1).
 */
function ringOf(indices, arcs) {
  const points = [];
  for (const idx of indices) {
    const arc = idx < 0 ? arcs[~idx].slice().reverse() : arcs[idx];
    points.push(...(points.length ? arc.slice(1) : arc));
  }
  return points;
}

/**
 * Chops a ring that crosses the date line into separate pieces.
 *
 * Natural Earth puts Russia, Fiji and Antarctica in one ring with points on both
 * -180 and +180. Projecting that ring flat gives a line straight across the whole
 * map: from Kamchatka all the way left to Chukotka. That showed as a stripe over
 * the Pacific and a bar over Siberia.
 *
 * The data already has a point exactly on ±180 at every crossing, so cutting
 * where two consecutive points are more than half a world apart is enough; each
 * piece then closes neatly along the map edge by itself. The last piece goes back
 * into the first, because a ring is round: the start and the end are the same
 * point and belong together.
 */
function splitAtDateline(ring) {
  const parts = [[ring[0]]];
  for (let i = 1; i < ring.length; i++) {
    if (Math.abs(ring[i][0] - ring[i - 1][0]) > 180) parts.push([ring[i]]);
    else parts[parts.length - 1].push(ring[i]);
  }
  if (parts.length === 1) return parts;
  const tail = parts.pop();
  parts[0] = [...tail, ...parts[0].slice(1)];
  return parts.filter((p) => p.length >= 3);
}

// ---------------------------------------------------------------------------
// Equal Earth
// ---------------------------------------------------------------------------

const A1 = 1.340264;
const A2 = -0.081106;
const A3 = 0.000893;
const A4 = 0.003796;
const M = Math.sqrt(3) / 2;

function project([lon, lat]) {
  const l = (lon * Math.PI) / 180;
  const t = Math.asin(M * Math.sin((lat * Math.PI) / 180));
  const t2 = t * t;
  const t6 = t2 * t2 * t2;
  return [
    (l * Math.cos(t)) / (M * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2))),
    t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2)),
  ];
}

// ---------------------------------------------------------------------------
// Simplifying
// ---------------------------------------------------------------------------

function perpendicular([px, py], [ax, ay], [bx, by]) {
  const dx = bx - ax;
  const dy = by - ay;
  const len = dx * dx + dy * dy;
  if (len === 0) return Math.hypot(px - ax, py - ay);
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/**
 * Douglas-Peucker, iterative. Recursively it ran into the stack depth on Russia:
 *  that is one ring of well over a thousand points.
 */
function simplify(points, tolerance) {
  if (points.length < 3) return points;
  const keep = new Uint8Array(points.length);
  keep[0] = 1;
  keep[points.length - 1] = 1;
  const stack = [[0, points.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop();
    let worst = 0;
    let at = -1;
    for (let i = first + 1; i < last; i++) {
      const d = perpendicular(points[i], points[first], points[last]);
      if (d > worst) {
        worst = d;
        at = i;
      }
    }
    if (worst > tolerance && at > 0) {
      keep[at] = 1;
      stack.push([first, at], [at, last]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

function ringArea(points) {
  let sum = 0;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    sum += points[j][0] * points[i][1] - points[i][0] * points[j][1];
  }
  return Math.abs(sum) / 2;
}

/**
 * Centroid of a ring — where the dot goes when a country is too small to point at.
 */
function ringCentroid(points) {
  let cx = 0;
  let cy = 0;
  let a = 0;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const f = points[j][0] * points[i][1] - points[i][0] * points[j][1];
    a += f;
    cx += (points[j][0] + points[i][0]) * f;
    cy += (points[j][1] + points[i][1]) * f;
  }
  if (a === 0) return points[0];
  return [cx / (3 * a), cy / (3 * a)];
}

// ---------------------------------------------------------------------------

const res = await fetch(SOURCE);
if (!res.ok) throw new Error(`${SOURCE}: HTTP ${res.status}`);
const topology = await res.json();
const arcs = decodeArcs(topology);

// Every country as a list of rings in lon/lat, then projected.
const countries = [];
for (const geom of topology.objects.countries.geometries) {
  const atlasName = geom.properties.name;
  if (DROP.has(atlasName)) continue;
  const polygons = geom.type === "Polygon" ? [geom.arcs] : geom.arcs;
  const rings = polygons.flatMap((poly) =>
    poly.flatMap((r) => splitAtDateline(ringOf(r, arcs)).map((part) => part.map(project))),
  );
  if (rings.length === 0) continue;
  countries.push({ name: ATLAS_TO_APP[atlasName] ?? atlasName, rings });
}

// The viewBox: the envelope of what is left. From the data and not from the
// formula, because with Antarctica out the bottom edge is Cape Horn and not -90°.
let minX = Infinity;
let minY = Infinity;
let maxX = -Infinity;
let maxY = -Infinity;
for (const { rings } of countries) {
  for (const ring of rings) {
    for (const [x, y] of ring) {
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }
}
const k = WIDTH / (maxX - minX);
const HEIGHT = Math.round((maxY - minY) * k * 10) / 10;
// Flip y: in SVG it runs downward, on earth upward.
const toScreen = ([x, y]) => [(x - minX) * k, (maxY - y) * k];

const round = (n) => Math.round(n * 10) / 10;

const out = [];
for (const { name, rings } of countries) {
  const screen = rings.map((r) => r.map(toScreen));
  const areas = screen.map(ringArea);
  const biggest = areas.indexOf(Math.max(...areas));
  const kept = screen
    .map((r, i) => ({ ring: r, area: areas[i], main: i === biggest }))
    .filter((r) => r.main || r.area >= MIN_RING_AREA);

  const d = kept
    .map(({ ring }) => {
      const pts = simplify(ring, TOLERANCE).map(([x, y]) => [round(x), round(y)]);
      return `M${pts.map((p) => p.join(" ")).join("L")}Z`;
    })
    .join("");

  const [cx, cy] = ringCentroid(screen[biggest]);
  out.push({ name, d, area: round(areas[biggest]), c: [round(cx), round(cy)] });
}

out.sort((a, b) => a.name.localeCompare(b.name));

const points = Object.entries(POINT_ONLY).map(([name, lonlat]) => {
  const [x, y] = toScreen(project(lonlat));
  return { name, c: [round(x), round(y)] };
});

const body = `// GEGENEREERD — niet met de hand bijwerken.
// Opnieuw maken: \`node scripts/build-world-map.mjs\` (zie dat script voor het waarom).
//
// Bron: world-atlas 110m (Natural Earth, publiek domein), Equal Earth-projectie,
// Antarctica eruit. Coördinaten liggen al in het viewBox hieronder.

/** Eén land: het SVG-pad, het zwaartepunt, en hoe groot het op deze kaart is. */
export type Country = {
  name: string;
  /** Het \`d\`-attribuut. Meerdere eilanden zitten als losse M…Z in hetzelfde pad. */
  d: string;
  /** Zwaartepunt van het grootste eiland — waar de stip komt te staan. */
  c: [number, number];
  /** Oppervlak van dat eiland in viewBox-eenheden. Onder \`TINY\` is een land te
   *  klein om aan te wijzen en krijgt het een stip erbij. */
  area: number;
};

export const VIEWBOX = { width: ${WIDTH}, height: ${HEIGHT} };

/** Onder dit oppervlak (viewBox-eenheden) is een land op schermformaat kleiner dan
 *  een muisaanwijzer. Die landen krijgen een stip als aanwijspunt. */
export const TINY = ${TINY};

export const COUNTRIES: Country[] = ${JSON.stringify(
  out.map(({ name, d, c, area }) => ({ name, d, c, area })),
).replace(/},{/g, "},\n  {").replace(/^\[/, "[\n  ").replace(/\]$/, ",\n]")};

/** Landen die op 110m geen eigen vorm hebben maar wel in een portefeuille kunnen
 *  zitten. Alleen een aanwijspunt. */
export const POINT_COUNTRIES: { name: string; c: [number, number] }[] = ${JSON.stringify(
  points,
).replace(/},{/g, "},\n  {").replace(/^\[/, "[\n  ").replace(/\]$/, ",\n]")};
`;

writeFileSync(OUT, body);
const kb = (body.length / 1024).toFixed(1);
console.log(`${out.length} landen + ${points.length} punten → ${OUT} (${kb} kB)`);
