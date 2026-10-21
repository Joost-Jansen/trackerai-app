"use client";

// The route of one activity on OpenStreetMap, coloured per heart-rate zone. A dark or light casing
// under the line keeps the soft zone colours readable on any background. `cursor` (0..1) puts a dot
// at the spot you point at in the chart.

import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import type * as L from "leaflet";
import { ZONES, type Zone } from "@/lib/training";
import { useT } from "@/lib/i18n";
import { cssVar, tileLayerFor, useDark } from "./useTheme";

type Track = { latlng: [number, number][]; zone: (Zone | null)[] };

function segments(track: Track) {
  const out: { zone: Zone | null; points: [number, number][] }[] = [];
  track.latlng.forEach((p, i) => {
    const z = track.zone[i] ?? null;
    const last = out[out.length - 1];
    if (last && last.zone === z) last.points.push(p);
    else out.push({ zone: z, points: last ? [last.points[last.points.length - 1], p] : [p] });
  });
  return out;
}

export default function ActivityMap({ track, cursor, height = 360 }: { track: Track; cursor?: number | null; height?: number }) {
  const t = useT();
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const dark = useDark();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const Lf = await import("leaflet");
      if (cancelled || !box.current) return;
      const m = Lf.map(box.current, { scrollWheelZoom: true, wheelPxPerZoomLevel: 100, attributionControl: true });
      map.current = m;
      const tiles = tileLayerFor(dark);
      Lf.tileLayer(tiles.url, tiles.options).addTo(m);

      const casing = dark ? "#0b0f0d" : "#ffffff";
      Lf.polyline(track.latlng, { color: casing, weight: 7, opacity: 0.9 }).addTo(m);
      const colour: Record<string, string> = Object.fromEntries(ZONES.map((z, i) => [z, cssVar(`--zone-${i + 1}`)]));
      for (const s of segments(track)) {
        Lf.polyline(s.points, { color: s.zone ? colour[s.zone] : cssVar("--n-400"), weight: 4, opacity: 1 }).addTo(m);
      }
      const ink = cssVar("--n-800", "#1f2a26");
      const start = track.latlng[0];
      const end = track.latlng[track.latlng.length - 1];
      Lf.circleMarker(end, { radius: 5, color: casing, weight: 2, fillColor: ink, fillOpacity: 1 }).bindTooltip(t.common.finish).addTo(m);
      Lf.circleMarker(start, { radius: 5, color: ink, weight: 2, fillColor: casing, fillOpacity: 1 }).bindTooltip(t.common.start).addTo(m);
      marker.current = Lf.circleMarker(start, {
        radius: 6,
        color: casing,
        weight: 2,
        fillColor: cssVar("--brand-600", "#3e7258"),
        fillOpacity: 0,
        opacity: 0,
      }).addTo(m);
      m.fitBounds(Lf.latLngBounds(track.latlng), { padding: [16, 16] });
    })();
    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
      marker.current = null;
    };
  }, [track, dark, t]);

  useEffect(() => {
    const mk = marker.current;
    if (!mk) return;
    if (cursor == null) {
      mk.setStyle({ opacity: 0, fillOpacity: 0 });
      return;
    }
    const i = Math.min(track.latlng.length - 1, Math.max(0, Math.round(cursor * (track.latlng.length - 1))));
    mk.setLatLng(track.latlng[i]);
    mk.setStyle({ opacity: 1, fillOpacity: 1 });
  }, [cursor, track]);

  return <div ref={box} className="z-0 w-full overflow-hidden rounded" style={{ height }} role="img" aria-label={t.activity.mapAria} />;
}
