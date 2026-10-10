"use client";

// Light or dark as the page currently shows it (data-theme or the system preference), and a
// CSS token as a real colour. Leaflet draws svg attributes; var(--zone-1) does not work in those.

import { useEffect, useState } from "react";

function isDark(): boolean {
  const set = document.documentElement.getAttribute("data-theme");
  if (set === "dark") return true;
  if (set === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function useDark(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const update = () => setDark(isDark());
    update();
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    return () => {
      mo.disconnect();
      mq.removeEventListener("change", update);
    };
  }, []);
  return dark;
}

export function cssVar(name: string, fallback = "#888"): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

// OpenStreetMap standard tiles: no API key needed (CARTO asks for one outside localhost). The
// tiles are bright by themselves; the classes `map-tiles` and `map-tiles--dark` in globals.css make them
// soft (light) or invert them (dark). The filter sits on the tile layer, not on lines and dots.
export function tileLayerFor(dark: boolean) {
  return {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    options: {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
      className: dark ? "map-tiles map-tiles--dark" : "map-tiles",
    },
  };
}
