"use client";

// All routes on top of each other: thin, half-transparent lines. Where you run often the line becomes thick
// and saturated by itself. On canvas, because hundreds of polylines as svg make the map slow.

import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import { useT } from "@/lib/i18n";
import { cssVar, tileLayerFor, useDark } from "./useTheme";

export default function HeatMap({ tracks, height = 520 }: { tracks: [number, number][][]; height?: number }) {
  const t = useT();
  const box = useRef<HTMLDivElement>(null);
  const dark = useDark();

  useEffect(() => {
    let cancelled = false;
    let remove = () => {};
    (async () => {
      const Lf = await import("leaflet");
      if (cancelled || !box.current || tracks.length === 0) return;
      const m = Lf.map(box.current, { preferCanvas: true, scrollWheelZoom: true, wheelPxPerZoomLevel: 100 });
      remove = () => m.remove();
      const tiles = tileLayerFor(dark);
      Lf.tileLayer(tiles.url, tiles.options).addTo(m);
      const colour = dark ? cssVar("--zone-5", "#cf6d71") : cssVar("--oxblood-400", "#d9484c");
      const renderer = Lf.canvas();
      for (const t of tracks) Lf.polyline(t, { color: colour, weight: 2.5, opacity: 0.28, renderer, interactive: false }).addTo(m);

      // Zoom in on the area where most routes start (home), not on all holidays together.
      const starts = tracks.map((t) => t[0]);
      const key = (p: [number, number]) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`;
      const counts = new Map<string, number>();
      starts.forEach((p) => counts.set(key(p), (counts.get(key(p)) ?? 0) + 1));
      const home = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
      const local = tracks.filter((t) => key(t[0]) === home).flat();
      m.fitBounds(Lf.latLngBounds(local.length ? local : tracks.flat()), { padding: [12, 12] });
    })();
    return () => {
      cancelled = true;
      remove();
    };
  }, [tracks, dark]);

  if (tracks.length === 0) return <p className="py-6 text-center text-sm text-ink-muted">{t.history.noGps}</p>;
  return <div ref={box} className="z-0 w-full overflow-hidden rounded" style={{ height }} role="img" aria-label={t.history.heatAria(tracks.length)} />;
}
