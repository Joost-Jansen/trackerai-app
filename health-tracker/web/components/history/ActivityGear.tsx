"use client";

// Which gear an activity used, and why (chosen here, from Garmin, or the default of its sport). Change sets the
// choice (PUT /api/activities/{id}/gear); None means no gear at all; Automatic hands it back to Garmin and the default.

import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Checkbox } from "@/components/ds";
import { api } from "@/lib/api";
import { useGear } from "@/lib/gear";
import { errorText, useT } from "@/lib/i18n";
import type { ActivityDetail } from "@/lib/training";

export default function ActivityGear({ a }: { a: ActivityDetail }) {
  const t = useT();
  const m = t.activity.gear;
  const qc = useQueryClient();
  const all = useGear().data?.gear;
  const [editing, setEditing] = useState(false);
  const [chosen, setChosen] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const used = a.gear ?? [];

  if (!all) return null;
  if (all.length === 0 && used.length === 0) {
    if (!a.distance_km) return null;
    return (
      <p className="text-[12.5px] text-ink-muted">
        {m.noGear}{" "}
        <Link href="/history/#gear" className="text-ink underline-offset-2 hover:underline">
          {m.addGear}
        </Link>
      </p>
    );
  }

  async function save(ids: number[] | null) {
    setBusy(true);
    setError(null);
    try {
      await api.put(`/api/activities/${encodeURIComponent(a.id)}/gear`, { gear_ids: ids });
      setEditing(false);
      qc.invalidateQueries();
    } catch (err) {
      setError(errorText(err, t, m.failed));
    } finally {
      setBusy(false);
    }
  }

  // what is in use, the defaults of this sport first; retired gear only when this activity already has it
  const options = all
    .filter((g) => g.state !== "retired" || used.some((u) => u.id === g.id))
    .sort(
      (x, y) =>
        Number(y.default_for.includes(a.sport)) - Number(x.default_for.includes(a.sport)) ||
        (y.last_used ?? "").localeCompare(x.last_used ?? ""),
    );

  if (editing) {
    return (
      <div className="flex flex-col gap-3 rounded-md bg-[var(--surface-inset)] px-4 py-3 text-[12.5px]">
        <span className="font-medium">{m.choose}</span>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {options.map((g) => (
            <Checkbox
              key={g.id}
              checked={chosen.includes(g.id)}
              onChange={(v) => setChosen(v ? [...chosen, g.id] : chosen.filter((x) => x !== g.id))}
              label={
                <span>
                  {g.name}
                  <span className="text-ink-muted">
                    {" "}
                    · {t.gear.kinds[g.kind].toLowerCase()}
                    {g.state === "retired" ? ` · ${m.retired}` : ""}
                  </span>
                </span>
              }
            />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="primary" disabled={busy} onClick={() => save(chosen)}>
            {m.save}
          </Button>
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => save([])}>
            {m.none}
          </Button>
          {a.gear_chosen && (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => save(null)}>
              {m.automatic}
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setEditing(false);
              setError(null);
            }}
          >
            {m.cancel}
          </Button>
          {error && <span className="text-loss">{error}</span>}
        </div>
        {a.gear_chosen && (
          <span className="text-[11.5px] text-ink-muted">
            {m.automatic}: {m.automaticHint}
          </span>
        )}
      </div>
    );
  }

  return (
    <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[12.5px]">
      <span className="text-ink-muted">{m.label}</span>
      {used.length === 0 ? (
        <span className="text-ink-muted">{m.noneChosen}</span>
      ) : (
        used.map((g) => (
          <span key={g.id}>
            <Link href="/history/#gear" className="font-medium underline-offset-2 hover:underline">
              {g.name}
            </Link>
            <span className="text-ink-muted"> · {m.why[g.source]}</span>
          </span>
        ))
      )}
      <button
        type="button"
        className="text-ink underline-offset-2 hover:underline"
        onClick={() => {
          setChosen(used.map((g) => g.id));
          setEditing(true);
        }}
      >
        {m.change}
      </button>
    </p>
  );
}
