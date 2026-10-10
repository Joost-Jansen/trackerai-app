"use client";

// Apple Health: import the export of the Health app (api/apple.py). Apple has no online account to connect to, so
// the steps to export on the iPhone are right here, then the file goes up in parts (Cloudflare refuses a request over
// 100 MB, and exports are often bigger) with one progress bar for the whole file (XMLHttpRequest: fetch has no upload
// progress). A part that fails is tried again a few times; if it keeps failing, "Try again" resumes from that part.
// The server reads the file in the background while this card polls how far it is. Importing a newer export later
// adds what is new; nothing is counted twice.

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import CollapsibleCard from "@trackerai/ui/components/CollapsibleCard";
import { HeartIcon } from "@trackerai/ui/icons";
import { Button } from "@/components/ds";
import { api, ApiError } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";

export type AppleImport = {
  running: boolean;
  progress: { step: "read" | "workouts" | "days" | "derive"; done: number | null; total: number | null } | null;
  last: null | {
    status: "done" | "failed";
    file?: string;
    workouts?: number;
    added?: number;
    merged?: number;
    nights?: number;
    staged_nights?: number;
    kept_garmin_days?: number;
    first?: string | null;
    last?: string | null;
    imported_at?: string;
    error?: string;
    failed_at?: string;
  };
};

function Bar({ label, pct }: { label: string; pct: number | null }) {
  return (
    <div className="flex max-w-md flex-col gap-1.5 text-[12.5px] text-ink-muted" role="status" aria-live="polite">
      <span>{label}{pct !== null && ` · ${pct}%`}</span>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-sunk">
        <div className={`h-full rounded-full bg-brand transition-[width] duration-500 ${pct === null ? "w-1/3 animate-pulse" : ""}`}
             style={pct === null ? undefined : { width: `${pct}%` }} />
      </div>
    </div>
  );
}

type Started = { upload_id: string; chunk_size: number; size: number };
/** An upload under way: what "Try again" needs to go on from the part that failed. */
type Pending = { file: File; started: Started; next: number };

const ATTEMPTS = 3; // per part, before the card asks the user

function errorFrom(xhr: XMLHttpRequest): ApiError {
  let body: { code?: string; detail?: string; params?: Record<string, unknown> } = {};
  try { body = JSON.parse(xhr.responseText); } catch { /* not json */ }
  return new ApiError(xhr.status, typeof body.detail === "string" ? body.detail : xhr.statusText, body.code, body.params);
}

/** One part as the raw body; `onProgress` gets the bytes of this part sent so far. */
function sendPart(id: string, index: number, blob: Blob, onProgress: (loaded: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/apple/upload/${encodeURIComponent(id)}/${index}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(errorFrom(xhr)));
    xhr.onerror = () => reject(new ApiError(0, "network", "network"));
    xhr.send(blob);
  });
}

/** Retry what may pass a second time: the network, a server or proxy hiccup, a part that arrived cut short. */
const retryable = (err: unknown) =>
  err instanceof ApiError && (err.status === 0 || err.status >= 500 || err.status === 408 || err.code === "upload_size_mismatch");

/** Send the parts from `p.next` on; resolves with the import's state once the server has the whole file. */
async function sendFrom(p: Pending, onPart: (next: number) => void, onProgress: (pct: number) => void): Promise<AppleImport> {
  const { file, started } = p;
  const parts = Math.ceil(started.size / started.chunk_size);
  for (let i = p.next; i < parts; i++) {
    const from = i * started.chunk_size;
    const blob = file.slice(from, Math.min(from + started.chunk_size, started.size));
    for (let attempt = 1; ; attempt++) {
      try {
        await sendPart(started.upload_id, i, blob, (loaded) => onProgress(Math.round(((from + loaded) / started.size) * 100)));
        break;
      } catch (err) {
        if (attempt >= ATTEMPTS || !retryable(err)) throw err;
        await new Promise((r) => setTimeout(r, 1000 * attempt));
      }
    }
    onPart(i + 1);
  }
  return api.post<AppleImport>(`/api/apple/upload/${encodeURIComponent(started.upload_id)}/finish`);
}

export default function AppleHealthCard({ highlight = false }: { highlight?: boolean }) {
  const t = useT();
  const m = t.connections.apple;
  const f = useFormat();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState<number | null>(null);
  const [pending, setPending] = useState<Pending | null>(null); // a failed upload that "Try again" can resume
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["apple-import"],
    queryFn: () => api.get<AppleImport>("/api/apple/import"),
    refetchInterval: (query) => (query.state.data?.running ? 1500 : false),
  });
  const running = !!q.data?.running;

  useEffect(() => {
    if (highlight) document.getElementById("apple")?.scrollIntoView({ block: "start" });
  }, [highlight]);

  // an import that was running and is now done: everything on the site may have changed
  const was = useRef(false);
  useEffect(() => {
    if (was.current && !running) qc.invalidateQueries();
    was.current = running;
  }, [running, qc]);

  async function run(p: Pending) {
    setError(null);
    setNote(null);
    setPending(null);
    setUploading(Math.round(((p.next * p.started.chunk_size) / p.started.size) * 100));
    let next = p.next;
    try {
      const state = await sendFrom(p, (n) => { next = n; }, setUploading);
      qc.setQueryData(["apple-import"], state);
      was.current = true;
    } catch (err) {
      const gone = err instanceof ApiError && (err.code === "upload_not_found" || err.code === "not_an_export" || err.status === 413);
      if (!gone) setPending({ ...p, next }); // resumable: the parts so far are on the server
      setError(err instanceof ApiError && err.status === 0 ? m.network : errorText(err, t, m.failed));
    } finally {
      setUploading(null);
    }
  }

  async function pick(file: File | undefined) {
    if (input.current) input.current.value = "";
    if (!file) return;
    setError(null);
    try {
      const started = await api.post<Started>("/api/apple/upload", { name: file.name, size: file.size });
      await run({ file, started, next: 0 });
    } catch (err) {
      setError(errorText(err, t, m.failed));
    }
  }

  async function removeAll() {
    if (!confirm(m.removeConfirm)) return;
    try {
      const r = await api.del<{ removed: number; days: number }>("/api/apple/import");
      setNote(m.removed(r.removed, r.days));
      qc.invalidateQueries();
    } catch (err) {
      setError(errorText(err, t, m.failed));
    }
  }

  const p = q.data?.progress;
  const stepLabel = !p ? m.progress.starting
    : p.step === "read" ? m.progress.read
    : p.step === "workouts" ? m.progress.workouts(p.done, p.total)
    : p.step === "days" ? m.progress.days
    : m.progress.derive;
  const pct = p?.total && p.done != null ? Math.min(100, Math.round((p.done / p.total) * 100)) : null;
  const last = q.data?.last;
  const done = last?.imported_at ? last : null; // also after a failed later import: that earlier data is still here

  return (
    <CollapsibleCard id="apple" title={m.title} icon={<HeartIcon className="h-5 w-5" />}
      summary={uploading !== null ? `${m.uploading} · ${uploading}%` : running ? stepLabel
        : last?.status === "failed" || error ? <span className="text-loss">{m.failed}</span> : m.manual}
      reveal={highlight || running || uploading !== null || !!error || last?.status === "failed"}
      className={highlight ? "ring-2 ring-[var(--border-focus)]" : ""}>
        <div className="flex flex-col gap-3 text-[13px]">
          {!done && <p className="max-w-prose leading-relaxed text-ink-muted">{m.intro}</p>}
          {note && <p className="max-w-prose text-[12.5px]">{note}</p>}
          {error && <p className="max-w-prose text-[12.5px] text-loss">{error}</p>}
          {last?.status === "failed" && !running && uploading === null && (
            <p className="max-w-prose text-[12.5px] text-loss">{errorText(new ApiError(422, "", last.error), t, m.failed)}</p>
          )}

          {uploading !== null ? (
            <Bar label={m.uploading} pct={uploading} />
          ) : running ? (
            <Bar label={stepLabel} pct={pct} />
          ) : done ? (
            <dl className="grid max-w-md grid-cols-[150px_1fr] gap-y-1.5">
              <dt className="text-ink-muted">{m.lastImport}</dt>
              <dd>{done.imported_at ? f.dateTime(done.imported_at) : "–"}</dd>
              <dt className="text-ink-muted">{m.workouts}</dt>
              <dd>{m.workoutsValue(done.workouts ?? 0, done.merged ?? 0)}</dd>
              <dt className="text-ink-muted">{m.nights}</dt>
              <dd>{m.nightsValue(done.nights ?? 0, done.staged_nights ?? 0)}</dd>
              <dt className="text-ink-muted">{m.period}</dt>
              <dd>{done.first && done.last ? `${f.day(done.first)} – ${f.day(done.last)}` : "–"}</dd>
              {!!done.kept_garmin_days && (<><dt className="text-ink-muted">Garmin</dt><dd>{m.keptGarmin(done.kept_garmin_days)}</dd></>)}
            </dl>
          ) : null}

          {!done && !running && uploading === null && (
            <ol className="flex max-w-prose list-decimal flex-col gap-1 pl-5 text-[12.5px] leading-relaxed">
              {m.steps.map((s) => <li key={s}>{s}</li>)}
            </ol>
          )}

          <input ref={input} type="file" accept=".zip,.xml,application/zip,application/xml,text/xml" className="hidden"
                 onChange={(e) => pick(e.target.files?.[0])} />
          {pending && uploading === null && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="primary" onClick={() => run(pending)}>{m.retry}</Button>
              <Button size="sm" variant="ghost" onClick={() => {
                api.del(`/api/apple/upload/${encodeURIComponent(pending.started.upload_id)}`).catch(() => {});
                setPending(null);
                setError(null);
              }}>{m.cancel}</Button>
            </div>
          )}
          {!running && uploading === null && !pending && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant={done ? "secondary" : "primary"} onClick={() => input.current?.click()}>
                {done ? m.again : m.choose}
              </Button>
              {done && <Button size="sm" variant="ghost" onClick={removeAll}>{m.remove}</Button>}
            </div>
          )}
          {done && <p className="max-w-prose text-[12px] text-ink-muted">{m.againHint}</p>}

          <details className="max-w-prose text-[12px] text-ink-muted">
            <summary className="cursor-pointer select-none hover:text-[var(--text-primary)]">{m.whatTitle}</summary>
            <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-5 leading-relaxed">
              {m.what.map((s) => <li key={s}>{s}</li>)}
            </ul>
          </details>
        </div>
    </CollapsibleCard>
  );
}
