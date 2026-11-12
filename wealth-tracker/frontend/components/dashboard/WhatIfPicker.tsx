"use client";

// Under the value chart: which stored portfolio to draw next to your own, and a
// way to store one. A snapshot is the holdings at the end of a day, rebuilt from
// your transactions and kept under a name (backend routers/what_if.py); the chart
// then draws what that portfolio would be worth had you kept it.
//
// The choice itself is the page's (it decides the line and the period); this only
// lists, saves and deletes.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Snapshot } from "@/lib/dashboard";
import { fmtDayMonthYear } from "@/lib/format";
import { tr } from "@/lib/i18n";

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function WhatIfPicker({
  snapshots,
  chosen,
  onChoose,
}: {
  snapshots: Snapshot[];
  chosen: number | null;
  onChoose: (snapshot: Snapshot | null) => void;
}) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [date, setDate] = useState(() => isoDaysAgo(30));
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => api.post<Snapshot>("/api/what-if/snapshots", { date, name: name.trim() || null }),
    onSuccess: (s) => {
      qc.setQueryData<{ snapshots: Snapshot[] }>(["what-if-snapshots"], (old) => ({
        snapshots: [...(old?.snapshots ?? []), s].sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id),
      }));
      setAdding(false);
      setName("");
      setError(null);
      onChoose(s);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : tr("Saving did not work. Try again.")),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/api/what-if/snapshots/${id}`),
    onSuccess: (_, id) => {
      qc.setQueryData<{ snapshots: Snapshot[] }>(["what-if-snapshots"], (old) => ({
        snapshots: (old?.snapshots ?? []).filter((s) => s.id !== id),
      }));
      if (chosen === id) onChoose(null);
    },
  });

  const current = snapshots.find((s) => s.id === chosen) ?? null;

  return (
    <div className="mt-3 flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <label className="inline-flex items-center gap-1.5 text-ink-muted">
          {tr("Compare with")}
          <select
            value={chosen ?? ""}
            onChange={(e) => onChoose(snapshots.find((s) => String(s.id) === e.target.value) ?? null)}
            className="cursor-pointer rounded-sm border border-[var(--border-hairline)] bg-transparent px-1.5 py-0.5 text-xs text-text"
            disabled={snapshots.length === 0}
          >
            <option value="">{snapshots.length === 0 ? tr("no snapshot yet") : tr("nothing")}</option>
            {snapshots.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({fmtDayMonthYear(s.date)})
              </option>
            ))}
          </select>
        </label>
        {current && (
          <button
            type="button"
            className="ds-link text-ink-muted"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(tr("Delete the snapshot '{0}'?", current.name))) remove.mutate(current.id);
            }}
          >
            {tr("delete")}
          </button>
        )}
        {!adding && (
          <button type="button" className="ds-link" onClick={() => setAdding(true)}>
            {tr("+ save the portfolio of a day")}
          </button>
        )}
      </div>

      {adding && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <input
            type="date"
            required
            value={date}
            max={isoDaysAgo(0)}
            onChange={(e) => setDate(e.target.value)}
            aria-label={tr("Day")}
            className="rounded-sm border border-[var(--border-hairline)] bg-transparent px-1.5 py-0.5 text-xs"
          />
          <input
            type="text"
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
            placeholder={tr("Name, e.g. Before the switch")}
            aria-label={tr("Name")}
            className="min-w-[12rem] flex-1 rounded-sm border border-[var(--border-hairline)] bg-transparent px-1.5 py-0.5 text-xs"
          />
          <button type="submit" className="ds-link font-medium" disabled={save.isPending}>
            {save.isPending ? tr("saving…") : tr("save")}
          </button>
          <button
            type="button"
            className="ds-link text-ink-muted"
            onClick={() => {
              setAdding(false);
              setError(null);
            }}
          >
            {tr("cancel")}
          </button>
          <span className="basis-full text-[11.5px] text-ink-muted">
            {tr("Stores what you held at the end of that day, so you can see how it would have done had you kept it.")}
          </span>
          {error && (
            <span className="basis-full text-[11.5px]" style={{ color: "var(--text-loss)" }}>
              {error}
            </span>
          )}
        </form>
      )}
    </div>
  );
}
