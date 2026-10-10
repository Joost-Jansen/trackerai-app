"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@trackerai/ui/ds/Button";
import Card from "@trackerai/ui/components/Card";
import { useTr } from "@trackerai/ui/i18n";
import type { createApi } from "@trackerai/ui/lib/api";

export type AccountApi = Pick<ReturnType<typeof createApi>, "get" | "post" | "del">;
type Connection = { id: string; name: string; app: "health" | "wealth"; scope: "read" | "write"; last_used_at: string | null };
type Options = { enabled: boolean; plugin_url: string | null; resource: string | null; connections: Connection[] };

export default function AgentConnections({ api }: { api: AccountApi }) {
  const tr = useTr();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["agent-connections"], queryFn: () => api.get<Options>("/api/account/agent-connections"), retry: false });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [copied, setCopied] = useState(false);
  return (
    <Card>
      <div className="flex flex-col gap-4 text-[13px] leading-relaxed">
        <p className="max-w-prose text-ink-muted">{tr("Use your TrackerAI account for health and wealth. Sign in once, then choose which tracker the assistant may read. No token to copy.")}</p>
        {q.isPending ? <p>{tr("Loading…")}</p> : q.isError ? <p role="alert">{tr("Connections could not be loaded. Try again.")}</p> : q.data?.enabled ? (
          <>
            {q.data.plugin_url && <>
            <div className="flex flex-wrap gap-2">
              <a className="ds-btn ds-btn--primary ds-btn--md" href={q.data.plugin_url} target="_blank" rel="noreferrer">{tr("Connect ChatGPT / Codex")}</a>
            </div>
            <p className="max-w-prose text-ink-muted">{tr("Open the TrackerAI plugin, add it in your assistant and choose Connect. You return here to approve access. Read-only is selected first; editing is optional.")}</p>
            </>}
            {q.data.resource && <details>
              <summary className="cursor-pointer font-medium">{tr("Use a custom connection")}</summary>
              <p className="mt-2 max-w-prose text-ink-muted">{tr("If the plugin is not available in your assistant account, add a custom MCP connection with this server URL and choose OAuth. Use your existing TrackerAI login.")}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <code className="break-all text-xs">{q.data.resource}</code>
                <Button size="sm" onClick={async () => {
                  try { await navigator.clipboard.writeText(q.data!.resource!); setCopied(true); setTimeout(() => setCopied(false), 1500); }
                  catch { setError(true); }
                }}>{copied ? tr("Copied") : tr("Copy server URL")}</Button>
              </div>
            </details>}
          </>
        ) : <p className="text-ink-muted">{tr("Account-based connections are not available yet. You can use Advanced setup below.")}</p>}
        <div className="border-t border-border pt-3">
          <h3 className="mb-2 font-medium">{tr("Connected apps")}</h3>
          {!q.data?.connections.length ? <p className="text-ink-muted">{tr("No connected apps yet.")}</p> : (
            <ul className="flex flex-col divide-y divide-border">
              {q.data.connections.map(c => (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <span><strong>{c.name}</strong><span className="text-ink-muted"> · {c.app === "health" ? tr("Health") : tr("Wealth")} · {c.scope === "read" ? tr("Read-only") : tr("Read and edit")}</span>
                    {!c.last_used_at && <span className="block text-xs text-ink-muted">{tr("Not used yet")}</span>}
                  </span>
                  <Button size="sm" variant="danger" disabled={busy === c.id} onClick={async () => {
                    if (!window.confirm(tr("Disconnect {0}? It will lose access to this tracker.", c.name))) return;
                    setBusy(c.id); setError(false);
                    try { await api.del(`/api/account/agent-connections/${encodeURIComponent(c.id)}`); await qc.invalidateQueries({ queryKey: ["agent-connections"] }); }
                    catch { setError(true); } finally { setBusy(null); }
                  }}>{tr("Disconnect")}</Button>
                </li>
              ))}
            </ul>
          )}
          {error && <p role="alert" className="text-loss">{tr("That did not work. Try again.")}</p>}
        </div>
      </div>
    </Card>
  );
}
