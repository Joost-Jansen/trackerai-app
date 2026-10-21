"use client";

// Voeding on Settings, Zones and profile (where the body weight lives): photo analysis on or off (it sends the photo to
// Anthropic, so off until you switch it on, and only offered when the server can), how long photos are kept, an
// optional calorie target (none by default), and the carbohydrate and protein targets per day type, read-only.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button, Input, Select, Switch } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";
import type { DayType, NutritionSettings as Settings } from "@/lib/nutrition";

const ORDER: DayType[] = ["rest", "easy", "moderate", "long", "race"];

export default function NutritionSettings() {
  const tt = useT();
  const t = tt.nutrition.settings;
  const f = useFormat();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["nutrition-settings"], queryFn: () => api.get<Settings>("/api/nutrition/settings") });
  const [kcal, setKcal] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!q.data) return null;
  const s = q.data;

  async function put(body: Record<string, unknown>) {
    setError(null);
    try {
      qc.setQueryData(["nutrition-settings"], await api.put<Settings>("/api/nutrition/settings", body));
      qc.invalidateQueries({ queryKey: ["nutrition-day"] });
    } catch (err) {
      setError(errorText(err, tt, t.failed));
    }
  }

  const range = (r: [number, number]) => `${f.trim(r[0], 1)}–${f.trim(r[1], 1)}`;
  return (
    <Card title={t.title}>
      <div id="nutrition" className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <Switch checked={s.ai} disabled={!s.ai_available} onChange={(v) => put({ ai: v })} label={t.ai} />
          <p className="text-[12px] leading-relaxed text-ink-muted">{s.ai_available ? t.aiHelp : t.aiUnavailable}</p>
        </div>
        <Select label={t.photos} value={s.photos} onChange={(e) => put({ photos: e.target.value })} className="max-w-xs">
          <option value="30d">{t.keep30}</option>
          <option value="keep">{t.keepAlways}</option>
          <option value="never">{t.keepNever}</option>
        </Select>
        <Select
          label={t.norms}
          hint={t.normsHint}
          value={s.norms ?? "none"}
          onChange={(e) => put({ norms: e.target.value })}
          className="max-w-xs"
        >
          <option value="none">{t.normsNone}</option>
          <option value="men">{t.normsMen}</option>
          <option value="women">{t.normsWomen}</option>
        </Select>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const v = f.parse(kcal ?? "");
            put(v ? { kcal_target: Math.round(v) } : { clear_kcal_target: true });
            setKcal(null);
          }}
        >
          <Input
            label={t.kcalTarget}
            hint={t.kcalHint}
            inputMode="numeric"
            className="w-40"
            value={kcal ?? (s.kcal_target != null ? String(s.kcal_target) : "")}
            onChange={(e) => setKcal(e.target.value)}
          />
          {kcal != null && (
            <Button type="submit" variant="secondary" size="sm">
              {tt.common.save}
            </Button>
          )}
        </form>
        <div className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-medium">{s.weight_kg ? t.targetsFor(f.num(s.weight_kg)) : t.targets}</span>
          <table className="text-[12.5px] tabular-nums">
            <thead>
              <tr className="text-left text-ink-muted">
                <th className="py-1 pr-4 font-normal">{t.dayType}</th>
                <th className="py-1 pr-4 font-normal">{tt.nutrition.nutrients.carbs_g}</th>
                <th className="py-1 font-normal">{tt.nutrition.nutrients.protein_g}</th>
              </tr>
            </thead>
            <tbody>
              {ORDER.map((d) => (
                <tr key={d} className="border-t border-border">
                  <td className="py-1 pr-4">{tt.nutrition.dayTypes[d]}</td>
                  <td className="py-1 pr-4">{tt.nutrition.perKg(range(s.day_types[d].carbs_per_kg))}</td>
                  <td className="py-1">{tt.nutrition.perKg(range(s.day_types[d].protein_per_kg))}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11.5px] text-ink-muted">{t.targetsNote}</p>
        </div>
        {error && (
          <p className="text-[12.5px] text-loss" role="alert">
            {error}
          </p>
        )}
      </div>
    </Card>
  );
}
