"use client";

// An open-water swim measures its distance with GPS, which barely works in water (tools/distance.py). The app does
// not count an impossible distance; here you see what GPS gave and can enter the real distance (PATCH
// /api/activities/{id}), which every later sync keeps.

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";
import type { ActivityDetail } from "@/lib/training";

export default function DistanceCorrection({ a }: { a: ActivityDetail }) {
  const t = useT();
  const m = t.activity.distanceFix;
  const f = useFormat();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!a.open_water && !a.distance_manual && !a.distance_doubtful) return null;

  async function save(km: number | null) {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/api/activities/${encodeURIComponent(a.id)}`, { distance_km: km });
      setEditing(false);
      qc.invalidateQueries();
    } catch (err) {
      setError(errorText(err, t, m.failed));
    } finally {
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const km = Number(value.replace(",", "."));
    if (!value.trim() || !Number.isFinite(km)) return setError(m.failed);
    save(km);
  }

  // under a kilometre in metres: "20 m", not "0.0 km"
  const gps = a.gps_distance_km != null ? (a.gps_distance_km < 1 ? `${Math.round(a.gps_distance_km * 1000)} m` : f.km(a.gps_distance_km)) : null;
  const text = a.distance_doubtful ? m.doubtful(gps ?? "0 m", f.clock(a.moving_time_s)) : a.distance_manual ? m.corrected : m.openWater;

  return (
    <div className={`text-[12.5px] ${a.distance_doubtful && !editing ? "rounded-md bg-[var(--surface-inset)] px-4 py-3" : ""}`}>
      {editing ? (
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <Input label={m.label} inputMode="decimal" autoFocus value={value} onChange={(e) => setValue(e.target.value)} error={error ?? undefined} className="w-32" />
          <Button size="sm" variant="primary" type="submit" disabled={busy}>{m.save}</Button>
          <Button size="sm" variant="ghost" type="button" onClick={() => { setEditing(false); setError(null); }}>{m.cancel}</Button>
        </form>
      ) : (
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-ink-muted">
          <span>{text}</span>
          <button type="button" className="text-ink underline-offset-2 hover:underline" onClick={() => { setValue(a.distance_km ? String(a.distance_km) : ""); setEditing(true); }}>
            {a.distance_manual ? m.change : m.fix}
          </button>
          {a.distance_manual && (
            <button type="button" className="text-ink underline-offset-2 hover:underline" disabled={busy} onClick={() => save(null)}>
              {m.undo(gps)}
            </button>
          )}
          {error && !editing && <span className="text-loss">{error}</span>}
        </p>
      )}
    </div>
  );
}
