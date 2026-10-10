"use client";

import AgentAssistant, { agentName, type AgentClient as Client } from "@trackerai/ui/account/AgentAssistant";
import AgentConnections from "@trackerai/ui/account/AgentConnections";
import AgentAdvanced from "@trackerai/ui/account/AgentAdvanced";

// Agents — let an AI assistant (Claude, ChatGPT, Codex, Copilot or any other MCP
// client) read along and keep things up to date, with a token of its own
// instead of your password. The server lives in backend/app/routers/mcp.py; what a
// token may do is in backend/app/deps.py.
//
// One token works for stock-tracker *and* wealth-tracker: they share the same API.

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Button, Input, Section, Select } from "@/components/ds";
import { SettingRow } from "../page";
import { intlLocale, tr, trx } from "@/lib/i18n";

type Token = {
  id: string; name: string; scope: "read" | "write"; created_at: string; last_used?: string | null;
  expires_at?: string | null; expired?: boolean;
};
type Made = Token & { token: string };

const LEVEL: Record<Token["scope"], string> = {
  read: tr("Read: view everything, change nothing."),
  write: tr("Read and write: also label transactions, keep budgets, labelling rules, categories and settings, enter balances and add transactions. Never upload, delete transactions or accounts, bank connections or your account."),
};

function Copy({ label, value }: { label: string; value: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-ink-muted">{label}</span>
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 whitespace-pre-wrap break-all rounded-md px-3 py-2 font-mono text-[12px]" style={{ background: "var(--surface-sunken)" }}>
          {value}
        </code>
        <Button
          size="sm"
          onClick={() => {
            navigator.clipboard?.writeText(value).then(() => setDone(true), () => undefined);
            setTimeout(() => setDone(false), 1500);
          }}
        >
          {done ? tr("Copied") : tr("Copy")}
        </Button>
      </div>
    </div>
  );
}

// Where you connect the assistant: one choice per set of steps. Every client gets the same server:
// streamable HTTP with the token as a Bearer header, or in the URL for a client that only takes a URL (a
// connector in a web app). A claude.ai connector also works in the Claude app and in Claude Code when it is
// logged in with that account, so Claude is one choice.


function clientLabel(c: Client) {
  switch (c) {
    case "claude":
      return "Claude (app, claude.ai, Claude Code)";
    case "copilot":
      return "GitHub Copilot (VS Code, CLI)";
    case "other":
      return tr("Another MCP client (Cursor, Gemini CLI, …)");
    default:
      return agentName(c);
  }
}

// A token's default name: short, it shows in the list of tokens.
function defaultName(c: Client) {
  return c === "other" ? tr("AI assistant") : agentName(c);
}

type Snippet = { label: string; value: string };

function howTo(client: Client, site: string, origin: string, token: string): { intro: ReactNode; snippets: Snippet[] } {
  const url = `${origin}/api/mcp`;
  const urlToken = `${url}/${token}`;
  const bearer = `Bearer ${token}`;
  switch (client) {
    case "claude":
      return {
        intro: trx("In {0}, “Add custom connector”. Name: {1}. Paste this URL (the token is in it). Once per account: it then works in the Claude app, on claude.ai and in Claude Code logged in with that account.", <a className="underline underline-offset-2" href="https://claude.ai/customize/connectors" target="_blank" rel="noreferrer">claude.ai/customize/connectors</a>, site),
        snippets: [
          { label: "Connector-URL", value: urlToken },
          { label: tr("Only for Claude Code with an API key instead of a claude.ai login, once in a terminal"), value: `claude mcp add --transport http --scope user ${site} ${url} --header "Authorization: ${bearer}"` },
        ],
      };
    case "openai":
      return {
        intro: <>{tr("In ChatGPT on the web, switch on Developer mode under Settings (Apps or Connectors, Advanced). Then create a connector named {0} with this URL and authentication “No authentication” (the token is in the URL):", site)}<br />{tr("Add this to ~/.codex/config.toml. It works for the Codex CLI and the IDE extension:")}</>,
        snippets: [
          { label: "Connector-URL", value: urlToken },
          { label: "config.toml", value: `[mcp_servers.${site}]\nurl = "${url}"\nhttp_headers = { "Authorization" = "${bearer}" }` },
        ],
      };
    case "copilot":
      return {
        intro: tr("VS Code and the Copilot CLI each keep their own list, so add it where you use Copilot. In VS Code: Command Palette, “MCP: Open User Configuration”, and add this server (inside the existing “servers”, if there is one)."),
        snippets: [
          { label: "VS Code: mcp.json", value: JSON.stringify({ servers: { [site]: { type: "http", url, headers: { Authorization: bearer } } } }, null, 2) },
          { label: tr("Copilot CLI, once in a terminal"), value: `copilot mcp add --transport http ${site} ${urlToken}` },
        ],
      };
    case "other":
      return {
        intro: tr("The server speaks MCP over streamable HTTP (no session, answers as JSON). Give the client the URL and the header, or, if it only takes a URL, the URL with the token in it."),
        snippets: [
          { label: "URL", value: url },
          { label: "Header", value: `Authorization: ${bearer}` },
          { label: tr("URL with the token in it"), value: urlToken },
        ],
      };
  }
}

const date = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString(intlLocale, { day: "numeric", month: "short", year: "numeric" }) : tr("not yet"));
const moment = (iso?: string | null) => (iso ? new Date(iso).toLocaleString(intlLocale, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : tr("not yet"));
const until = (t: Token) => (t.expired ? tr("expired") : t.expires_at ? tr("valid until {0}", date(t.expires_at)) : tr("no end date"));

export default function AgentsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["agent-tokens"], queryFn: () => api.get<{ tokens: Token[] }>("/api/agent-tokens") });
  const [client, setClient] = useState<Client>("claude");
  // The name follows the chosen assistant until you type one yourself.
  const [typed, setTyped] = useState<string | null>(null);
  const name = typed ?? defaultName(client);
  // Read-only unless you choose otherwise; an end date unless you choose none.
  const [scope, setScope] = useState<Token["scope"]>("read");
  const [expires, setExpires] = useState<string>("90");
  const [made, setMade] = useState<Made | null>(null);
  const [error, setError] = useState<string | null>(null);

  const make = useMutation({
    mutationFn: () => api.post<Made>("/api/agent-tokens", { name: name, scope, expires_days: expires === "never" ? null : Number(expires) }),
    onSuccess: (t) => {
      setMade(t);
      setError(null);
      qc.invalidateQueries({ queryKey: ["agent-tokens"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : tr("The token could not be created")),
  });
  const away = useMutation({
    mutationFn: (id: string) => api.del(`/api/agent-tokens/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-tokens"] }),
  });

  const origin = typeof window === "undefined" ? "" : window.location.origin;
  // The name of this site (stock-tracker or wealth-tracker), as in the browser tab.
  const site = (typeof document === "undefined" ? "" : document.title.split(/\s+[—-]\s+/)[0].trim()) || "wealth-tracker";
  const tokens = q.data?.tokens ?? [];

  return (
    <div className="flex max-w-[760px] flex-col gap-11">
      <AgentAssistant value={client} onChange={setClient}
        title={tr("Connect an AI assistant")}
        intro={tr("An AI assistant (Claude, ChatGPT, Codex, Copilot, Gemini or any other MCP client) can view your portfolio, net worth and spending and, if you allow it, label transactions and manage budgets. Choose your assistant below to connect it. You can revoke its access here at any time.")} />
      {client === "openai" && <AgentConnections api={api} />}
      <AgentAdvanced collapsed={client === "openai"}>
      <Section label="Agents">
        <form
          className="flex max-w-md flex-col gap-4 py-5"
          onSubmit={(e) => {
            e.preventDefault();
            make.mutate();
          }}
        >
          <Input id="agent-name" label={tr("Name")} value={name} onChange={(e) => setTyped(e.target.value)} maxLength={60} />
          <Select id="agent-scope" label={tr("What may it do?")} hint={LEVEL[scope]} value={scope} onChange={(e) => setScope(e.target.value as Token["scope"])}>
            <option value="read">{tr("Read")}</option>
            <option value="write">{tr("Read and write")}</option>
          </Select>
          <Select id="agent-expires" label={tr("Valid for")} hint={tr("After that the token stops working and you make a new one. You can revoke it earlier at any time.")} value={expires} onChange={(e) => setExpires(e.target.value)}>
            <option value="30">{tr("30 days")}</option>
            <option value="90">{tr("90 days")}</option>
            <option value="365">{tr("1 year")}</option>
            <option value="never">{tr("No end date")}</option>
          </Select>
          {error && <p className="text-sm" style={{ color: "var(--text-loss)" }}>{error}</p>}
          <div>
            <Button type="submit" variant="primary" disabled={make.isPending}>
              {make.isPending ? tr("Working…") : tr("Create token")}
            </Button>
          </div>
        </form>

        {made && (
          <div className="flex flex-col gap-4 rounded-lg p-4" style={{ border: "1px solid var(--border-hairline)" }}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[14.5px] font-medium">{trx("Token “{0}” (visible only now)", made.name)}</p>
                <p className="text-[13px] text-ink-muted">{trx("Keep it like a password. Whoever has it can {0}.", made.scope === "read" ? tr("read your data") : tr("read and update your data"))}</p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setMade(null)}>{tr("Done")}</Button>
            </div>
            {(() => {
              const how = howTo(client, site, origin, made.token);
              return (
                <div className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <p className="text-[13px] font-medium">{clientLabel(client)}</p>
                    <p className="text-[12.5px] text-ink-muted">{how.intro}</p>
                  </div>
                  {how.snippets.map((x) => (
                    <Copy key={x.label} label={x.label} value={x.value} />
                  ))}
                  <p className="text-[12.5px] text-ink-muted">{tr("Another assistant? Choose it above; this token works there too.")}</p>
                </div>
              );
            })()}
            <Copy label={tr("Token (for scripts: Authorization: Bearer …)")} value={made.token} />
          </div>
        )}
      </Section>

      <Section label="Tokens">
        {tokens.length === 0 ? (
          <p className="py-3 text-[13px] text-ink-muted">{tr("No tokens yet.")}</p>
        ) : (
          tokens.map((t, i) => (
            <SettingRow
              key={t.id}
              last={i === tokens.length - 1}
              title={t.name}
              body={tr("{0} · created {1} · last used {2} · {3}", t.scope === "read" ? tr("Read") : tr("Read and write"), date(t.created_at), moment(t.last_used), until(t))}
              control={
                <Button size="sm" variant="ghost" disabled={away.isPending} onClick={() => away.mutate(t.id)}>{tr("Revoke")}</Button>
              }
            />
          ))
        )}
      </Section>
      </AgentAdvanced>
    </div>
  );
}
