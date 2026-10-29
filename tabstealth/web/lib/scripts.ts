// The two players come from their own hosts as plain scripts: alphaTab (tab rendering and the synth, from jsDelivr,
// a fixed version) and the YouTube iframe API. Each is loaded once and shared by every page.

import type { AlphaTab, YouTube } from "./vendor.ts";

const ALPHATAB = "https://cdn.jsdelivr.net/npm/@coderline/alphatab@1.3.1/dist/";

let alphaTabPromise: Promise<AlphaTab> | null = null;
let youTubePromise: Promise<YouTube> | null = null;

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

type PlayerWindow = Window & { alphaTab?: AlphaTab; YT?: YouTube; onYouTubeIframeAPIReady?: () => void };

export function loadAlphaTab(): Promise<AlphaTab> {
  alphaTabPromise ??= addScript(`${ALPHATAB}alphaTab.js`, true).then(() => (window as PlayerWindow).alphaTab!);
  return alphaTabPromise;
}

export function loadYouTube(): Promise<YouTube> {
  youTubePromise ??= new Promise((resolve) => {
    const w = window as PlayerWindow;
    if (w.YT?.Player) return resolve(w.YT);
    w.onYouTubeIframeAPIReady = () => resolve(w.YT!);
    void addScript("https://www.youtube.com/iframe_api");
  });
  return youTubePromise;
}
