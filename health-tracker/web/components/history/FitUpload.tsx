"use client";

// Upload FIT files: activities that are not on Garmin (a Wahoo bike computer, ...). One request per file, the file
// as the raw body (api/uploads.py). Zones and routes are recomputed once, after the last file.

import { useRef, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Dialog } from "@/components/ds";
import { SportBadge } from "@/components/plan/SportIcon";
import { api } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";

type Result = { status: "added" | "merged"; id: string; sport: string; start_local: string; distance_km?: number; source: string; merged_with: string[] };
type Row = { file: string; result?: Result; error?: string };

const SOURCE_NAME: Record<string, string> = { garmin: "Garmin", strava: "Strava", wahoo: "Wahoo", fit: "FIT" };

export default function FitUpload() {
  const t = useT();
  const f = useFormat();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState<{ i: number; n: number } | null>(null);

  async function send(files: File[]) {
    const out: Row[] = [];
    setRows([]);
    for (let i = 0; i < files.length; i++) {
      setBusy({ i: i + 1, n: files.length });
      const file = files[i];
      const last = i === files.length - 1;
      try {
        const result = await api.upload<Result>(
          `/api/activities/upload?name=${encodeURIComponent(file.name)}&recompute=${last ? "true" : "false"}`,
          file,
        );
        out.push({ file: file.name, result });
      } catch (err) {
        out.push({ file: file.name, error: errorText(err, t, t.history.upload.failed) });
        if (last && out.some((r) => r.result)) await api.post("/api/activities/recompute").catch(() => undefined);
      }
      setRows([...out]);
    }
    setBusy(null);
    qc.invalidateQueries();
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>{t.history.upload.button}</Button>
      <Dialog
        open={open}
        onClose={() => { if (!busy) setOpen(false); }}
        title={t.history.upload.title}
        description={t.history.upload.hint}
        actions={<Button variant="ghost" disabled={!!busy} onClick={() => setOpen(false)}>{t.history.upload.close}</Button>}
      >
        <div className="flex flex-col gap-3">
          <input
            ref={input}
            type="file"
            accept=".fit,.zip"
            multiple
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (files.length) void send(files);
            }}
          />
          <div>
            <Button variant="primary" disabled={!!busy} onClick={() => input.current?.click()}>{t.history.upload.choose}</Button>
          </div>
          {busy && <p className="text-[13px] text-ink-muted">{t.history.upload.working(busy.i, busy.n)}</p>}
          {rows.length > 0 && (
            <ul className="flex flex-col">
              {rows.map((r, i) => (
                <li key={`${r.file}-${i}`} className="flex items-center gap-2 border-t border-border py-2 text-[13px] first:border-t-0">
                  {r.result ? (
                    <>
                      <SportBadge sport={r.result.sport} size={20} />
                      <Link className="underline underline-offset-2" href={`/history/activity/?id=${encodeURIComponent(r.result.id)}`} onClick={() => setOpen(false)}>
                        {f.dayMonth(r.result.start_local)}
                      </Link>
                      <span className="text-ink-muted">{r.result.distance_km ? f.km(r.result.distance_km) : ""}</span>
                      <span className="ml-auto text-[12px] text-ink-muted">
                        {r.result.status === "merged"
                          ? t.history.upload.merged(r.result.merged_with.map((s) => SOURCE_NAME[s] ?? s).join(", "))
                          : t.history.upload.added}
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="truncate">{r.file}</span>
                      <span className="ml-auto text-[12px]" style={{ color: "var(--text-loss, var(--neg))" }}>{r.error}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          {!busy && rows.length > 0 && <p className="text-[12px] text-ink-muted">{t.history.upload.done(rows.filter((r) => r.result).length)}</p>}
        </div>
      </Dialog>
    </>
  );
}
