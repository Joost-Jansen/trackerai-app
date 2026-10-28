// The two players come from their own hosts as plain scripts: alphaTab (tab rendering and the synth, from jsDelivr,
// a fixed version) and the YouTube iframe API. Each is loaded once and shared by every page.

const ALPHATAB = "https://cdn.jsdelivr.net/npm/@coderline/alphatab@1.3.1/dist/";

let alphaTabPromise: Promise<any> | null = null;
let youTubePromise: Promise<any> | null = null;

function addScript(src: string, cors = false): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    // jsDelivr sends CORS headers, so alphaTab's errors show their message; YouTube does not and would be blocked
    if (cors) s.crossOrigin = "anonymous";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`could not load ${src}`));
    document.head.appendChild(s);
  });
}

export const ALPHATAB_BASE = ALPHATAB;

export function loadAlphaTab(): Promise<any> {
  alphaTabPromise ??= addScript(`${ALPHATAB}alphaTab.js`, true).then(() => (window as any).alphaTab);
  return alphaTabPromise;
}

export function loadYouTube(): Promise<any> {
  youTubePromise ??= new Promise((resolve) => {
    const w = window as any;
    if (w.YT?.Player) return resolve(w.YT);
    w.onYouTubeIframeAPIReady = () => resolve(w.YT);
    void addScript("https://www.youtube.com/iframe_api");
  });
  return youTubePromise;
}
