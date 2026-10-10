"use client";

// Zones and profile: your own heart-rate zones per sport (as % of your max) and a few fixed facts. Everything on the site
// calculates with these zones; after saving, the time per zone of all your activities is recalculated.

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button, Checkbox, Input } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/i18n";
import { ZONE_COLOUR, ZONES } from "@/lib/training";

type SportZone = { max_hr: number; bounds: number[]; estimate?: boolean };
type ZonesResp = { percent: number[]; zones: Record<string, SportZone>; suggested_max: Record<string, number | null>; estimate_offset: Record<string, number> };
type Facts = { birth_year?: number; weight_kg?: number; height_cm?: number; resting_hr?: number };
const SPORTS = ["run", "ride", "swim"] as const;

function boundsFor(max: number, p: number[]) {
  return [Math.round((max * p[0]) / 100), ...p.slice(1).map((x) => Math.round((max * x) / 100) + 1)];
}

function ZonePreview({ max, percent }: { max: number; percent: number[] }) {
  const b = boundsFor(max, percent);
  const ranges = [`< ${b[0]}`, `${b[0]}-${b[1] - 1}`, `${b[1]}-${b[2] - 1}`, `${b[2]}-${b[3] - 1}`, `≥ ${b[3]}`];
  return (
    <div className="grid grid-cols-5 gap-1 text-[11.5px] tabular-nums">
      {ZONES.map((z, i) => (
        <span key={z} className="rounded px-1.5 py-1" style={{ background: `color-mix(in srgb, ${ZONE_COLOUR[z]} 45%, transparent)` }}>
          <span className="font-medium">{z}</span> {ranges[i]}
        </span>
      ))}
    </div>
  );
}

function ZonesCard({ data }: { data: ZonesResp }) {
  const t = useT();
  const qc = useQueryClient();
  const [percent, setPercent] = useState(data.percent.map(String));
  const [max, setMax] = useState<Record<string, string>>({});
  const [estimate, setEstimate] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    setMax(Object.fromEntries(SPORTS.map((s) => [s, data.zones[s]?.max_hr ? String(data.zones[s].max_hr) : ""])));
    setEstimate(Object.fromEntries(SPORTS.map((s) => [s, Boolean(data.zones[s]?.estimate)])));
  }, [data]);
  const p = percent.map(Number);
  const runMax = Number(max.run) || data.suggested_max.run || null;

  async function save() {
    setMsg(null);
    try {
      await api.put("/api/settings/zones", {
        percent: p,
        sports: Object.fromEntries(SPORTS.map((s) => [s, { max_hr: max[s] ? Number(max[s]) : null, estimate: estimate[s] }])),
      });
      setMsg({ ok: true, text: t.zonesSettings.saved });
      qc.invalidateQueries();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, t, t.common.saveFailed) });
    }
  }

  return (
    <Card title={t.zonesSettings.title} action={<Button size="sm" variant="primary" onClick={save}>{t.common.save}</Button>}>
      <p className="mb-4 max-w-prose text-[12.5px] leading-relaxed text-ink-muted">
        {t.zonesSettings.intro}
      </p>
      <div className="flex flex-col gap-5">
        {SPORTS.map((s) => {
          const suggestion = data.suggested_max[s];
          const fallback = s !== "run" && runMax ? runMax - (data.estimate_offset[s] ?? 0) : null;
          const m = Number(max[s]);
          return (
            <div key={s} className="flex flex-col gap-2 border-t border-border pt-4 first:border-t-0 first:pt-0">
              <div className="flex flex-wrap items-end gap-3">
                <Input label={t.zonesSettings.maxFor(s)} inputMode="numeric" className="w-28" value={max[s] ?? ""} onChange={(e) => setMax({ ...max, [s]: e.target.value.replace(/\D/g, "") })} />
                <Checkbox label={t.zonesSettings.estimate} checked={estimate[s] ?? false} onChange={(v) => setEstimate({ ...estimate, [s]: v })} />
                {suggestion && String(suggestion) !== max[s] && (
                  <Button size="sm" variant="ghost" onClick={() => setMax({ ...max, [s]: String(suggestion) })}>{t.zonesSettings.suggestion(suggestion)}</Button>
                )}
                {!suggestion && fallback && !max[s] && (
                  <Button size="sm" variant="ghost" onClick={() => { setMax({ ...max, [s]: String(fallback) }); setEstimate({ ...estimate, [s]: true }); }}>
                    {t.zonesSettings.fromRunning(fallback)}
                  </Button>
                )}
              </div>
              {m >= 100 && m <= 230 ? <ZonePreview max={m} percent={p} /> : <p className="text-[12px] text-ink-muted">{t.zonesSettings.noMax(s)}</p>}
            </div>
          );
        })}
      </div>
      <details className="mt-5 text-[12.5px]">
        <summary className="cursor-pointer text-ink-muted">{t.zonesSettings.bounds}</summary>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          {["Z2", "Z3", "Z4", "Z5"].map((z, i) => (
            <Input key={z} label={t.zonesSettings.from(z)} inputMode="decimal" className="w-20" value={percent[i]} onChange={(e) => setPercent(percent.map((x, j) => (j === i ? e.target.value.replace(",", ".") : x)))} />
          ))}
          <Button size="sm" variant="ghost" onClick={() => setPercent(["70", "77", "85", "92.5"])}>{t.zonesSettings.defaults}</Button>
        </div>
      </details>
      {msg && <p className={`mt-3 text-[12.5px] ${msg.ok ? "text-gain" : "text-loss"}`}>{msg.text}</p>}
    </Card>
  );
}

function FactsCard() {
  const t = useT();
  const q = useQuery({ queryKey: ["profile-facts"], queryFn: () => api.get<Facts>("/api/settings/profile") });
  // what the site calculates now: the entered resting HR is only a fallback for when there are no measured nights
  const rhr = useQuery({ queryKey: ["resting-hr"], queryFn: () => api.get<{ value: number | null; source: string | null }>("/api/settings/resting-hr") });
  const [f, setF] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (q.data) setF(Object.fromEntries(Object.entries(q.data).map(([k, v]) => [k, String(v)])));
  }, [q.data]);
  const field = (k: keyof Facts, label: string) => (
    <Input label={label} inputMode="decimal" className="w-28" value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value.replace(",", ".") })} />
  );
  return (
    <Card title={t.zonesSettings.profile}>
      <p className="mb-4 max-w-prose text-[12.5px] text-ink-muted">{t.zonesSettings.profileIntro}</p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const body = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)]));
            await api.put("/api/settings/profile", body);
            setMsg(t.common.saved);
          } catch (err) {
            setMsg(errorText(err, t, t.common.saveFailed));
          }
        }}
      >
        {field("birth_year", t.zonesSettings.birthYear)}
        {field("height_cm", t.zonesSettings.height)}
        {field("weight_kg", t.zonesSettings.weight)}
        {field("resting_hr", t.zonesSettings.restingHr)}
        <Button type="submit" size="sm" variant="primary">{t.common.save}</Button>
        {msg && <span className="text-[12.5px] text-ink-muted">{msg}</span>}
      </form>
      {rhr.data && <p className="mt-3 max-w-prose text-[12px] text-ink-muted">{t.zonesSettings.restingHrHint(rhr.data.value, rhr.data.source)}</p>}
    </Card>
  );
}

export default function ZonesPage() {
  const t = useT();
  const q = useQuery({ queryKey: ["settings-zones"], queryFn: () => api.get<ZonesResp>("/api/settings/zones") });
  if (!q.data) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  return (
    <div className="flex flex-col gap-4">
      <ZonesCard data={q.data} />
      <FactsCard />
    </div>
  );
}
