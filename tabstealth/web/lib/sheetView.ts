// How the tab sheet is laid out: bars per line and a compact mode close to the tabs in the videos (no title block,
// smaller and tighter). Kept per device in localStorage; applied to alphaTab's settings.

export type SheetView = { barsPerRow: number; compact: boolean }; // barsPerRow -1: as many as fit

export const BARS_PER_ROW = [-1, 1, 2, 3, 4];
export const DEFAULT_VIEW: SheetView = { barsPerRow: 2, compact: true };
const KEY = "tabstealth.sheet";

export function readView(): SheetView {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (v && BARS_PER_ROW.includes(v.barsPerRow) && typeof v.compact === "boolean") return v;
  } catch {}
  return DEFAULT_VIEW;
}

export function saveView(v: SheetView): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(v));
  } catch {}
}

// the header Guitar Pro prints above the first line: the videos show none of it,
const HEADER = ["scoreTitle", "scoreSubTitle", "scoreArtist", "scoreAlbum", "scoreWords", "scoreMusic", "scoreWordsAndMusic", "scoreCopyright", "guitarTuning"];
// nor a "let ring" label over every beat (the notes still ring)
const COMPACT_HIDES = [...HEADER, "effectLetRing"];

/** Put the view into alphaTab's settings (the caller renders again). alphaTab 1.3 does not export its NotationElement
 *  enum, so the elements go in by name through its JSON settings. */
export function applyView(api: any, v: SheetView): void {
  api.settings.fillFromJson({
    display: { barsPerRow: v.barsPerRow, scale: v.compact ? 0.85 : 1, stretchForce: v.compact ? 0.8 : 1 },
    notation: { elements: Object.fromEntries(COMPACT_HIDES.map((name) => [name, !v.compact])) },
  });
  api.updateSettings();
}
