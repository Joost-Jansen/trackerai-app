"use client";

import AgentAssistant, { agentName, type AgentClient as Client } from "@trackerai/ui/account/AgentAssistant";
import AgentConnections from "@trackerai/ui/account/AgentConnections";
import AgentAdvanced from "@trackerai/ui/account/AgentAdvanced";

// Settings: access for coaching agents. You create a token here; with it an AI assistant talks to your data
// over MCP (Claude, ChatGPT, Codex, Copilot, Cursor, Gemini or any other MCP client), or tools/tr.py does.
// Only the hash is stored. You pick the assistant and see only its steps.

import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button } from "@/components/ds";
import { api } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";
import type { Messages } from "@/lib/i18n/nl";
import { rich } from "@/lib/i18n/rich";

type TokenRow = { id: string; name: string; created_at: string };
type NewToken = TokenRow & { token: string };

function Copy({ label, value, secret = false }: { label: string; value: string; secret?: boolean }) {
  const t = useT();
  const [done, setDone] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11.5px] text-ink-muted">{label}</span>
      <div className="flex items-start gap-2">
        <code
          className={`min-w-0 flex-1 whitespace-pre-wrap break-all rounded bg-[var(--surface-sunken)] px-2 py-1.5 font-mono text-[12px] ${secret ? "select-all" : ""}`}
        >
          {value}
        </code>
        <Button
          size="sm"
          onClick={async () => {
            await navigator.clipboard.writeText(value);
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          }}
        >
          {done ? t.common.copied : t.common.copy}
        </Button>
      </div>
    </div>
  );
}

const SITE = "health-tracker";

// Where you connect the assistant: one choice per set of steps. Every client gets the same server: streamable HTTP
// with the token as a Bearer header, or in the URL for a client that only takes a URL (a connector in a web app). A
// claude.ai connector also works in the Claude app and in Claude Code logged in with that account, so Claude is one
// choice.

function clientLabel(c: Client, t: Messages) {
  return c === "claude" || c === "copilot" || c === "other" ? t.agents.clients[c] : agentName(c);
}

function howTo(c: Client, t: Messages, origin: string, token: string): { intro: ReactNode; snippets: { label: string; value: string }[] } {
  const a = t.agents;
  const url = `${origin}/api/mcp`;
  const urlToken = `${url}/${token}`;
  const bearer = `Bearer ${token}`;
  switch (c) {
    case "claude":
      return {
        intro: rich(a.appText, {
          link: (x) => (
            <a className="underline" href="https://claude.ai/customize/connectors" target="_blank" rel="noreferrer">
              {x}
            </a>
          ),
        }),
        snippets: [
          { label: a.connectorUrl, value: urlToken },
          { label: a.apiKeyCode, value: `claude mcp add --transport http --scope user ${SITE} ${url} --header "Authorization: ${bearer}"` },
        ],
      };
    case "openai":
      return {
        intro: (
          <>
            {a.chatgpt}
            <br />
            {a.codex}
          </>
        ),
        snippets: [
          { label: a.connectorUrl, value: urlToken },
          { label: "config.toml", value: `[mcp_servers.${SITE}]\nurl = "${url}"\nhttp_headers = { "Authorization" = "${bearer}" }` },
        ],
      };
    case "copilot":
      return {
        intro: a.copilot,
        snippets: [
          {
            label: "VS Code: mcp.json",
            value: JSON.stringify({ servers: { [SITE]: { type: "http", url, headers: { Authorization: bearer } } } }, null, 2),
          },
          { label: a.copilotCli, value: `copilot mcp add --transport http ${SITE} ${urlToken}` },
        ],
      };
    case "other":
      return {
        intro: a.other,
        snippets: [
          { label: "URL", value: url },
          { label: "Header", value: `Authorization: ${bearer}` },
          { label: a.urlWithToken, value: urlToken },
        ],
      };
  }
}

export default function AgentsPage() {
  const t = useT();
  const f = useFormat();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["agent-tokens"], queryFn: () => api.get<TokenRow[]>("/api/agent-tokens") });
  const [client, setClient] = useState<Client>("claude");
  // The name follows the chosen assistant until you type one yourself.
  const [typed, setTyped] = useState<string | null>(null);
  const name = typed ?? agentName(client);
  const [made, setMade] = useState<NewToken | null>(null);
  const [error, setError] = useState<string | null>(null);
  const origin = typeof window === "undefined" ? "" : window.location.origin;

  async function create() {
    setError(null);
    try {
      setMade(await api.post<NewToken>("/api/agent-tokens", { name }));
      qc.invalidateQueries({ queryKey: ["agent-tokens"] });
    } catch (e) {
      setError(errorText(e, t, t.common.failed));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <AgentAssistant
        value={client}
        onChange={setClient}
        title={t.agents.title}
        intro={
          <>
            {t.agents.intro1} {t.agents.intro2}
          </>
        }
      />
      {client === "openai" && <AgentConnections api={api} />}
      <AgentAdvanced collapsed={client === "openai"}>
        <Card title={t.agents.newToken}>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input className="ds-input w-56" value={name} onChange={(e) => setTyped(e.target.value)} aria-label={t.agents.tokenName} />
            <Button variant="primary" size="sm" onClick={create} disabled={!name.trim()}>
              {t.agents.newToken}
            </Button>
            {error && <span className="text-[12.5px] text-loss">{error}</span>}
          </div>
        </Card>

        {made && (
          <Card
            title={t.agents.madeTitle(made.name)}
            action={
              <Button size="sm" variant="ghost" onClick={() => setMade(null)}>
                {t.common.done}
              </Button>
            }
          >
            <div className="flex flex-col gap-4">
              <Copy label={t.agents.token} value={made.token} secret />
              {(() => {
                const how = howTo(client, t, origin, made.token);
                return (
                  <div className="flex flex-col gap-2">
                    <h3 className="text-[13px] font-semibold">{clientLabel(client, t)}</h3>
                    <p className="text-[12.5px] text-ink-muted">{how.intro}</p>
                    {how.snippets.map((x) => (
                      <Copy key={x.label} label={x.label} value={x.value} secret />
                    ))}
                    <p className="text-[12px] text-ink-muted">{t.agents.otherAssistant}</p>
                  </div>
                );
              })()}
              <div>
                <h3 className="mb-1.5 text-[13px] font-semibold">{t.agents.cliTitle}</h3>
                <p className="mb-2 text-[12.5px] text-ink-muted">
                  {rich(t.agents.cliText, {
                    code: () => <code className="font-mono text-[12px]">{origin.replace(/^https?:\/\//, "")}</code>,
                  })}
                </p>
                <Copy label={t.agents.variables} value={`TRAINING_API_URL=${origin}\nTRAINING_API_TOKEN=${made.token}`} secret />
              </div>
            </div>
          </Card>
        )}

        <Card title={t.agents.active}>
          {q.isLoading ? (
            <p className="text-sm text-ink-muted">{t.common.loading}</p>
          ) : !q.data?.length ? (
            <p className="text-[13px] text-ink-muted">{t.agents.none}</p>
          ) : (
            <ul className="flex flex-col">
              {q.data.map((tok) => (
                <li
                  key={tok.id}
                  className="flex items-center justify-between gap-3 border-t border-border py-2 text-[13px] first:border-t-0"
                >
                  <span>
                    <span className="font-medium">{tok.name}</span>
                    <span className="text-ink-muted"> · {t.agents.created(f.day(tok.created_at))}</span>
                  </span>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      if (!confirm(t.agents.revokeConfirm(tok.name))) return;
                      await api.del(`/api/agent-tokens/${tok.id}`);
                      qc.invalidateQueries({ queryKey: ["agent-tokens"] });
                    }}
                  >
                    {t.common.revoke}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </AgentAdvanced>
    </div>
  );
}
