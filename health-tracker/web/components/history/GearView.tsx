"use client";

// History, Gear: per item how far it went against when it should be replaced, what needs attention first (api/gear.py
// sorts replace, soon, in use, retired), and the activities it was used on. Retired gear folds away below.

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Badge, Button, Dialog, EmptyState, Tag } from "@/components/ds";
import GearDialog from "@/components/history/GearDialog";
import { api } from "@/lib/api";
import { type Gear, type GearActivity, type GearOverview, type GearState, useGear } from "@/lib/gear";
import { errorText, useFormat, useT } from "@/lib/i18n";

const BAR: Record<GearState, string> = {
  ok: "var(--data-gain)",
  soon: "var(--warn)",
  replace: "var(--data-loss)",
  retired: "var(--text-muted)",
};
const TONE: Record<GearState, "neutral" | "gain" | "loss" | "brand"> = {
  ok: "neutral",
  soon: "brand",
  replace: "loss",
  retired: "neutral",
};
const SHOWN = 8; // activities listed at first under an item

function Activities({ g }: { g: Gear }) {
  const t = useT();
  const f = useFormat();
  const [all, setAll] = useState(false);
  const q = useQuery({ queryKey: ["gear", g.id, "activities"], queryFn: () => api.get<GearActivity[]>(`/api/gear/${g.id}/activities`) });
  if (q.isLoading) return <p className="text-[12.5px] text-ink-muted">{t.common.loading}</p>;
  const rows = q.data ?? [];
  if (!rows.length) return <p className="text-[12.5px] text-ink-muted">{t.gear.noActivities}</p>;
  return (
    <ul className="flex flex-col text-[12.5px]">
      {(all ? rows : rows.slice(0, SHOWN)).map((a) => (
        <li key={a.id} className="border-t border-border first:border-t-0">
          <Link
            href={`/history/activity/?id=${encodeURIComponent(a.id)}`}
            className="flex items-baseline gap-3 py-1.5 hover:bg-[var(--surface-hover)]"
          >
            <span className="w-[84px] flex-none text-ink-muted">{f.dayShortYear(a.start_local.slice(0, 10))}</span>
            <span className="min-w-0 flex-1 truncate">{a.name ?? t.sport(a.sport)}</span>
            <span className="tabular-nums text-ink-muted">
              {a.distance_km ? f.km(a.distance_km) : f.duration(a.moving_time_s ?? undefined)}
            </span>
          </Link>
        </li>
      ))}
      {!all && rows.length > SHOWN && (
        <li className="border-t border-border pt-1.5">
          <button type="button" className="text-ink-muted underline-offset-2 hover:underline" onClick={() => setAll(true)}>
            {t.gear.moreActivities(rows.length - SHOWN)}
          </button>
        </li>
      )}
    </ul>
  );
}

function GearCard({ g, onEdit }: { g: Gear; onEdit: () => void }) {
  const t = useT();
  const m = t.gear;
  const f = useFormat();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pct = g.share != null ? Math.min(100, g.share * 100) : null;
  const sub = [g.brand, g.model].filter(Boolean).join(" ");

  async function retire(on: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/api/gear/${g.id}`, { retired_on: on ? new Date().toISOString().slice(0, 10) : null });
      qc.invalidateQueries();
    } catch (err) {
      setError(errorText(err, t, m.form.failed));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title={g.name}
      action={
        <span className="flex items-center gap-1.5">
          {g.source === "garmin" && <Badge quiet>{m.garmin}</Badge>}
          <Tag tone={TONE[g.state]}>{m.states[g.state]}</Tag>
        </span>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-[12px] text-ink-muted">{[m.kinds[g.kind], sub].filter(Boolean).join(" · ")}</p>
        <div className="flex items-baseline gap-2">
          <span className="font-display text-[27px] font-light leading-none tabular-nums">{f.km(g.total_km, 0)}</span>
          {g.limit_km && <span className="text-[12.5px] text-ink-muted">{m.of(f.km(g.limit_km, 0))}</span>}
        </div>
        {pct != null && (
          <div
            className="h-1.5 overflow-hidden rounded-full bg-surface-sunk"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pct)}
          >
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: BAR[g.state] }} />
          </div>
        )}
        <p className="text-[12.5px]">
          {g.state === "retired" ? (
            <span className="text-ink-muted">{m.retiredOn(f.day(g.retired_on))}</span>
          ) : g.left_km == null ? (
            <span className="text-ink-muted">{m.noLimit}</span>
          ) : g.left_km < 0 ? (
            <span className="text-loss">{m.over(f.km(-g.left_km, 0))}</span>
          ) : (
            <span className={g.state === "soon" ? "text-[var(--warn)]" : "text-ink-muted"}>{m.left(f.km(g.left_km, 0))}</span>
          )}
          {g.limit_from && g.state !== "retired" && <span className="text-ink-muted"> · {m.limitFrom[g.limit_from]}</span>}
        </p>
        <p className="text-[12px] leading-relaxed text-ink-muted">
          {[
            m.uses(g.uses),
            g.first_used && m.since(f.day(g.first_used)),
            g.last_used ? m.lastUsed(f.dayMonth(g.last_used)) : !g.uses && m.notUsed,
            g.km_30d > 0 && g.state !== "retired" && m.last30(f.km(g.km_30d, 0)),
          ]
            .filter(Boolean)
            .join(" · ")}
          {g.before_km > 0 && (
            <>
              <br />
              {m.before(f.km(g.before_km, 0))}
            </>
          )}
        </p>
        {g.default_for.length > 0 && (
          <p className="text-[12px]">{m.defaultFor(f.list(g.default_for.map((s) => t.sport(s).toLowerCase())))}</p>
        )}
        {g.notes && <p className="whitespace-pre-line text-[12px] text-ink-muted">{g.notes}</p>}
        <div className="border-t border-border pt-2">
          <div className="-mx-3 flex flex-wrap items-center gap-1">
            <Button size="sm" variant="ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
              {m.showActivities} {open ? "▴" : "▾"}
            </Button>
            <Button size="sm" variant="ghost" onClick={onEdit}>
              {m.edit}
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => retire(g.state !== "retired")}>
              {g.state === "retired" ? m.unretire : m.retire}
            </Button>
          </div>
        </div>
        {error && <p className="text-[12.5px] text-loss">{error}</p>}
        {open && <Activities g={g} />}
      </div>
    </Card>
  );
}

function RemoveDialog({ g, onClose }: { g: Gear; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function remove() {
    setBusy(true);
    try {
      await api.del(`/api/gear/${g.id}`);
      qc.invalidateQueries();
      onClose();
    } catch (err) {
      setError(errorText(err, t, t.gear.removeFailed));
      setBusy(false);
    }
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title={t.gear.removeTitle(g.name)}
      description={t.gear.removeBody}
      actions={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t.gear.form.cancel}
          </Button>
          <Button variant="danger" disabled={busy} onClick={remove}>
            {t.gear.remove}
          </Button>
        </>
      }
    >
      {error && (
        <p className="text-[12.5px] text-loss" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}

export default function GearView() {
  const t = useT();
  const m = t.gear;
  const q = useGear();
  const [editing, setEditing] = useState<Gear | "new" | null>(null);
  const [removing, setRemoving] = useState<Gear | null>(null);
  const [showRetired, setShowRetired] = useState(false);

  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{m.loadFailed}</p>;
  const data: GearOverview = q.data;
  const active = data.gear.filter((g) => g.state !== "retired");
  const retired = data.gear.filter((g) => g.state === "retired");
  const card = (g: Gear) => <GearCard key={g.id} g={g} onEdit={() => setEditing(g)} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-2xl text-[12.5px] leading-relaxed text-ink-muted">{m.intro}</p>
        {data.gear.length > 0 && (
          <Button variant="primary" size="sm" onClick={() => setEditing("new")}>
            {m.add}
          </Button>
        )}
      </div>

      {data.gear.length === 0 ? (
        <Card>
          <EmptyState
            title={m.emptyTitle}
            body={m.emptyBody}
            action={
              <Button variant="primary" onClick={() => setEditing("new")}>
                {m.add}
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{active.map(card)}</div>
      )}

      {retired.length > 0 && (
        <div className="flex flex-col gap-3">
          <button
            type="button"
            className="self-start text-[12.5px] text-ink-muted underline-offset-2 hover:underline"
            aria-expanded={showRetired}
            onClick={() => setShowRetired(!showRetired)}
          >
            {showRetired ? "▾" : "▸"} {m.retiredTitle(retired.length)}
          </button>
          {showRetired && <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{retired.map(card)}</div>}
        </div>
      )}

      {editing && (
        <GearDialog
          gear={editing === "new" ? null : editing}
          overview={data}
          onClose={() => setEditing(null)}
          onRemove={(g) => {
            setEditing(null);
            setRemoving(g);
          }}
        />
      )}
      {removing && <RemoveDialog g={removing} onClose={() => setRemoving(null)} />}
    </div>
  );
}
