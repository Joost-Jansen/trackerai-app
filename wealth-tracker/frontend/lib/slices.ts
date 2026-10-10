// The look-through breakdown in segments: names in the reader's language, and the
// top-N + "Other" roll-up the distribution bar wants.
//
// Lived inside the dashboard page until the Allocation-tab needed the same
// three conversions. One copy, because the dashboard's "Allocation" card and that
// tab draw the same numbers from the same cached breakdown — a slice must not be
// called "Technologie" on one and "Information Technology" on the other.

import type { AllocationSlice } from "./dashboard";
import { locale } from "./i18n/locale";
import { tr } from "./i18n/tr";

/** The issuers' English labels, in Dutch. Covers sectors, continents and the
 *  handful of country names that arrive un-localised. */
const NL: Record<string, string> = {
  "Information Technology": "Technologie",
  Technology: "Technologie",
  Financials: "Financials",
  "Financial Services": "Financials",
  "Health Care": "Gezondheid",
  Healthcare: "Gezondheid",
  "Consumer Discretionary": "Consument (cycl.)",
  "Consumer Cyclical": "Consument (cycl.)",
  "Consumer Staples": "Consument (def.)",
  "Consumer Defensive": "Consument (def.)",
  Industrials: "Industrie",
  Energy: "Energie",
  "Communication Services": "Communicatie",
  Communication: "Communicatie",
  Utilities: "Nutsbedrijven",
  Materials: "Materialen",
  "Basic Materials": "Materialen",
  "Real Estate": "Vastgoed",
  "North America": "Noord-Amerika",
  Europe: "Europa",
  Asia: "Azië",
  "Asia-Pacific": "Azië-Pacific",
  Oceania: "Oceanië",
  "South America": "Zuid-Amerika",
  Africa: "Afrika",
  // Countries, as the issuers spell them. Every country etf_holdings knows a
  // continent for is in here — the list used to stop at the couple of dozen big
  // ones, which was enough while the tab only ever drew countries above 0,5%.
  // Now that the tail is openklapbaar, that same tail is exactly the part that
  // was missing: a Nederlandse pagina die "Saudi Arabia" en "Poland" opsomt.
  "United States": "Verenigde Staten",
  "United Kingdom": "Verenigd Koninkrijk",
  Germany: "Duitsland",
  France: "Frankrijk",
  Netherlands: "Nederland",
  Switzerland: "Zwitserland",
  Japan: "Japan",
  Canada: "Canada",
  Australia: "Australië",
  China: "China",
  Taiwan: "Taiwan",
  India: "India",
  "South Korea": "Zuid-Korea",
  Korea: "Zuid-Korea",
  Sweden: "Zweden",
  Denmark: "Denemarken",
  Spain: "Spanje",
  Italy: "Italië",
  Belgium: "België",
  Ireland: "Ierland",
  Brazil: "Brazilië",
  Mexico: "Mexico",
  "South Africa": "Zuid-Afrika",
  Norway: "Noorwegen",
  Finland: "Finland",
  Austria: "Oostenrijk",
  Portugal: "Portugal",
  Luxembourg: "Luxemburg",
  Poland: "Polen",
  Czechia: "Tsjechië",
  Greece: "Griekenland",
  Hungary: "Hongarije",
  Russia: "Rusland",
  Jersey: "Jersey",
  Guernsey: "Guernsey",
  Liechtenstein: "Liechtenstein",
  Monaco: "Monaco",
  Iceland: "IJsland",
  "Hong Kong": "Hongkong",
  Singapore: "Singapore",
  Indonesia: "Indonesië",
  Thailand: "Thailand",
  Malaysia: "Maleisië",
  Philippines: "Filipijnen",
  Vietnam: "Vietnam",
  Israel: "Israël",
  "Saudi Arabia": "Saoedi-Arabië",
  "United Arab Emirates": "Ver. Arabische Emiraten",
  Qatar: "Qatar",
  Kuwait: "Koeweit",
  Turkey: "Turkije",
  "New Zealand": "Nieuw-Zeeland",
  Bermuda: "Bermuda",
  "Cayman Islands": "Kaaimaneilanden",
  Argentina: "Argentinië",
  Chile: "Chili",
  Colombia: "Colombia",
  Peru: "Peru",
  Uruguay: "Uruguay",
  Egypt: "Egypte",
  Nigeria: "Nigeria",
  Morocco: "Marokko",
  Kenya: "Kenia",
  Other: "Overig",
  Unknown: "Onbekend",
};

/** A sector, continent or country as the issuers name it, in the reader's language. */
export const localName = (name: string) =>
  name === "Other" ? tr("Other") : name === "Unknown" ? tr("Unknown") : locale === "nl" ? NL[name] ?? name : name;

export type Slice = { name: string; pct: number; colour: string };

/**
 * The categorical palette for a distribution: five colours plus grey for
 *  "Other", deliberately not repeated.
 *
 *  Note what is *not* in it: --chart-2, the walnut black. In this design that is
 *  reserved for the line you measure something against — the benchmark — and in
 *  a horizontal distribution bar an almost black segment reads as a hole in the
 *  bar instead of as a category. The rest of the palette is in order of
 *  descending emphasis.
 */
export const SEGMENT_COLOURS = [
  "var(--chart-1)", // terracotta
  "var(--chart-4)", // oker
  "var(--chart-5)", // steenblauw
  "var(--chart-3)", // olijf
  "var(--chart-6)", // walnoot
  // Grey closes the row. A list of exactly six categories is drawn in full (see
  // topSlices), and without this sixth colour the series started again at
  // terracotta — then Oceania had the same colour as North America. Grey is the
  // least emphatic colour and falls on the smallest item, and it can never clash
  // with "Other": that segment only exists with *more* than six.
  "var(--n-400)",
];
const PALETTE = SEGMENT_COLOURS.length;

/**
 * The biggest `n` slices, with everything below them folded into "Other".
 *
 * Capped at n=5 by default because the palette is six colours and deliberately
 * not cycled — a seventh slice would have to reuse a hue, and two slices of the
 * same colour in one donut is worse than a rolled-up remainder.
 *
 * Unless the whole list fits in those six, in which case it is drawn whole: for
 * the six continents that "Other" was a single category wearing the wrong
 * name, and it hid one of them behind a click for no reason at all.
 */
export function topSlices(list: AllocationSlice[], n = 5): Slice[] {
  const sorted = [...list].sort((a, b) => b.pct - a.pct);
  const cap = sorted.length <= PALETTE ? sorted.length : n;
  const top = sorted.slice(0, cap);
  const rest = sorted.slice(cap).reduce((s, x) => s + x.pct, 0);
  const slices: Slice[] = top.map((s, i) => ({
    name: localName(s.name),
    pct: s.pct,
    colour: SEGMENT_COLOURS[i % SEGMENT_COLOURS.length],
  }));
  // 0.05: below that the remainder rounds to 0,0% and a slice labelled "Other
  // 0,0%" reads as a bug rather than a rounding artefact.
  if (rest > 0.05) {
    slices.push({ name: localName("Other"), pct: Math.round(rest * 10) / 10, colour: "var(--n-400)" });
  }
  return slices;
}
