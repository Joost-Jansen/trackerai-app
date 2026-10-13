"use client";

// Add or edit one piece of gear (POST / PATCH /api/gear). Name and kind are all it needs; the rest refines the
// distance (kilometres before, replace at), which activities count (in use since, retired on) and which sports get
// it by default.

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Checkbox, Dialog, Input, Select } from "@/components/ds";
import { api } from "@/lib/api";
import { GEAR_KINDS, type Gear, type GearKind, type GearOverview } from "@/lib/gear";
import { errorText, useFormat, useT } from "@/lib/i18n";

const DEFAULT_MAX_KM: Partial<Record<GearKind, number>> = { shoes: 700 }; // api/gear.py DEFAULT_MAX_KM

export default function GearDialog({ gear, overview, onClose, onRemove }: { gear: Gear | null; overview: GearOverview; onClose: () => void; onRemove: (g: Gear) => void }) {
  const t = useT();
  const m = t.gear.form;
  const f = useFormat();
  const qc = useQueryClient();
  const [kind, setKind] = useState<GearKind>(gear?.kind ?? "shoes");
  const [name, setName] = useState(gear?.name ?? "");
  const [brand, setBrand] = useState(gear?.brand ?? "");
  const [model, setModel] = useState(gear?.model ?? "");
  const [startKm, setStartKm] = useState(f.input(gear?.start_km));
  const [maxKm, setMaxKm] = useState(f.input(gear?.max_km));
  const [since, setSince] = useState(gear?.since ?? "");
  const [retiredOn, setRetiredOn] = useState(gear?.retired_on ?? "");
  const [notes, setNotes] = useState(gear?.notes ?? "");
  const [defaults, setDefaults] = useState<string[]>(gear?.default_for ?? []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const garminLimit = gear?.limit_from === "garmin" ? gear.limit_km : null;
  const fallback = garminLimit ?? DEFAULT_MAX_KM[kind] ?? null;
  const owner = (sport: string) => overview.gear.find((g) => g.id === overview.defaults[sport] && g.id !== gear?.id);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const start = f.parse(startKm);
    const max = f.parse(maxKm);
    if (!name.trim()) return setError(t.errors.gear_name_required);
    if ((start != null && !Number.isFinite(start)) || (max != null && !Number.isFinite(max))) return setError(m.failed);
    setBusy(true);
    setError(null);
    const body = {
      kind, name: name.trim(), brand: brand.trim() || null, model: model.trim() || null, start_km: start, max_km: max,
      since: since || null, retired_on: retiredOn || null, notes: notes.trim() || null, default_for: defaults,
    };
    try {
      if (gear) await api.patch(`/api/gear/${gear.id}`, body);
      else await api.post("/api/gear", body);
      qc.invalidateQueries();
      onClose();
    } catch (err) {
      setError(errorText(err, t, m.failed));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={gear ? m.editTitle(gear.name) : m.addTitle}
      description={gear?.source === "garmin" ? m.garminNote : undefined}
      actions={
        <>
          {gear?.source === "manual" && <Button variant="danger" className="mr-auto" onClick={() => onRemove(gear)}>{t.gear.remove}</Button>}
          <Button variant="ghost" onClick={onClose}>{m.cancel}</Button>
          <Button variant="primary" type="submit" form="gear-form" disabled={busy}>{m.save}</Button>
        </>
      }
    >
      <form id="gear-form" onSubmit={save} className="-mx-1 flex max-h-[60vh] flex-col gap-4 overflow-y-auto px-1">
        <div className="grid grid-cols-[120px_1fr] gap-3">
          <Select label={m.kind} value={kind} onChange={(e) => setKind(e.target.value as GearKind)}>
            {GEAR_KINDS.map((k) => <option key={k} value={k}>{t.gear.kinds[k]}</option>)}
          </Select>
          <Input label={m.name} placeholder={m.namePlaceholder} value={name} onChange={(e) => setName(e.target.value)} autoFocus={!gear} maxLength={100} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input label={m.brand} value={brand} onChange={(e) => setBrand(e.target.value)} maxLength={60} />
          <Input label={m.model} value={model} onChange={(e) => setModel(e.target.value)} maxLength={80} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input label={m.startKm} inputMode="decimal" value={startKm} onChange={(e) => setStartKm(e.target.value)} hint={m.startKmHint} />
          <Input label={m.maxKm} inputMode="decimal" value={maxKm} onChange={(e) => setMaxKm(e.target.value)} hint={m.maxKmHint(fallback ? f.km(fallback, 0) : null)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input label={m.since} type="date" value={since} onChange={(e) => setSince(e.target.value)} hint={m.sinceHint} />
          {gear && <Input label={m.retiredOn} type="date" value={retiredOn} onChange={(e) => setRetiredOn(e.target.value)} />}
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="ds-field__label mb-1">{m.defaultFor}</legend>
          {overview.sports.length === 0 ? (
            <p className="text-[12px] text-ink-muted">{m.noSports}</p>
          ) : (
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              {overview.sports.map((s) => {
                const other = owner(s);
                const on = defaults.includes(s);
                return (
                  <Checkbox
                    key={s}
                    checked={on}
                    onChange={(v) => setDefaults(v ? [...defaults, s] : defaults.filter((x) => x !== s))}
                    label={<span>{t.sport(s)}{on && other && <span className="text-ink-muted"> · {m.takesOver(other.name)}</span>}</span>}
                  />
                );
              })}
            </div>
          )}
          <p className="text-[11.5px] leading-relaxed text-ink-muted">{m.defaultForHint}</p>
        </fieldset>
        <label className="ds-field">
          <span className="ds-field__label">{m.notes}</span>
          <textarea className="ds-input min-h-[64px] py-2" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} />
        </label>
        {error && <p className="text-[12.5px] text-loss" role="alert">{error}</p>}
      </form>
    </Dialog>
  );
}
