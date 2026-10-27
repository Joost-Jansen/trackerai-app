"use client";

// The Agents page of every tracker: connect an AI assistant to this tracker over MCP. One page for health and
// wealth; the app passes its name, its API and what read and write mean for its data.
//
// Two ways in, the first one first:
//   * Your TrackerAI account (OAuth, packages/accounts/trackerai_accounts/oauth.py): the assistant opens TrackerAI,
//     you sign in and approve, read-only unless you also allow editing. No token to copy. Claude, ChatGPT, Codex,
//     Gemini CLI and VS Code do this themselves; Gemini Enterprise asks for a client ID and secret, which you make
//     here (one per tracker, for your account only).
//   * A token (Advanced setup), for a client that cannot sign in, and for scripts.
// Both tokens and connections are listed here and can be ended here.

import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button } from "@trackerai/ui/ds/Button";
import { Input, Select } from "@trackerai/ui/ds/Field";
import { useTr, useUiLocale } from "@trackerai/ui/i18n";
import type { createApi } from "@trackerai/ui/lib/api";

export type AccountApi = Pick<ReturnType<typeof createApi>, "get" | "post" | "del">;
export type Tracker = "health" | "wealth";

const ASSISTANTS = ["claude", "openai", "gemini", "gemini-cli", "copilot", "other"] as const;
type Assistant = (typeof ASSISTANTS)[number];

type Connection = { id: string; name: string; app: Tracker; scope: "read" | "write"; last_used_at: string | null };
type OwnedClient = { id: string; name: string; app: Tracker; redirect_host: string; created_at: string };
type Options = {
  enabled: boolean;
  plugin_url: string | null;
  resource: string | null;
  authorization_url: string | null;
  token_url: string | null;
  connections: Connection[];
  clients: OwnedClient[];
};
type MadeClient = {
  client_id: string;
  client_secret: string;
  name: string;
  server_url: string;
  authorization_url: string;
  token_url: string;
  scopes: string;
  redirect_uri: string;
};
type Token = {
  id: string;
  name: string;
  scope: "read" | "write";
  created_at: string;
  last_used?: string | null;
  expires_at?: string | null;
  expired?: boolean;
};
type MadeToken = Token & { token: string };
type Snippet = { label: string; value: string };

function Copy({ label, value }: { label: string; value: string }) {
  const tr = useTr();
  const [done, setDone] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[12px] font-medium text-ink-muted">{label}</span>
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 select-all whitespace-pre-wrap break-all rounded bg-[var(--surface-sunken)] px-2.5 py-1.5 font-mono text-[12px]">
          {value}
        </code>
        <Button
          size="sm"
          onClick={() => {
            navigator.clipboard?.writeText(value).then(
              () => {
                setDone(true);
                setTimeout(() => setDone(false), 1500);
              },
              () => undefined,
            );
          }}
        >
          {done ? tr("Copied") : tr("Copy")}
        </Button>
      </div>
    </div>
  );
}

const Steps = ({ intro, snippets }: { intro: ReactNode; snippets: Snippet[] }) => (
  <div className="flex flex-col gap-3">
    <p className="max-w-prose text-[13px] leading-relaxed text-ink-muted">{intro}</p>
    {snippets.map((s) => (
      <Copy key={s.label} label={s.label} value={s.value} />
    ))}
  </div>
);

const link = (href: string, text: string) => (
  <a className="underline underline-offset-2" href={href} target="_blank" rel="noreferrer">
    {text}
  </a>
);

export default function AgentsPage({
  api,
  app,
  site,
  title,
  intro,
  levels,
  tokenExtra,
}: {
  api: AccountApi;
  app: Tracker;
  /** The server's name in the assistant, e.g. "wealth-tracker". */
  site: string;
  title: string;
  intro: ReactNode;
  /** What a read and a read-and-write token may do in this tracker. */
  levels: { read: string; write: string };
  /** More for a new token, below the assistant's steps (health: the variables for its command-line tool). */
  tokenExtra?: (token: string, origin: string) => ReactNode;
}) {
  const tr = useTr();
  const locale = useUiLocale();
  const qc = useQueryClient();
  const [assistant, setAssistant] = useState<Assistant>("claude");
  const options = useQuery({
    queryKey: ["agent-connections"],
    queryFn: () => api.get<Options>("/api/account/agent-connections"),
    retry: false,
  });
  const tokens = useQuery({ queryKey: ["agent-tokens"], queryFn: () => api.get<{ tokens: Token[] }>("/api/agent-tokens") });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [madeClient, setMadeClient] = useState<MadeClient | null>(null);
  const [madeToken, setMadeToken] = useState<MadeToken | null>(null);
  const [typed, setTyped] = useState<string | null>(null);
  const [scope, setScope] = useState<Token["scope"]>("read");
  const [expires, setExpires] = useState("90");

  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const o = options.data;
  const signIn = !!o?.enabled; // false: this installation has no OAuth, tokens only
  const server = o?.resource ?? `${origin}/api/mcp`;
  const trackerName = app === "health" ? tr("Health") : tr("Wealth");
  const labels: Record<Assistant, string> = {
    claude: "Claude (app, claude.ai, Claude Code)",
    openai: "ChatGPT / Codex",
    gemini: tr("Gemini (Workspace, Gemini Enterprise)"),
    "gemini-cli": "Gemini CLI",
    copilot: "GitHub Copilot (VS Code, CLI)",
    other: tr("Another MCP client (Cursor, …)"),
  };
  const day = (iso?: string | null) =>
    iso
      ? new Date(iso).toLocaleDateString(locale === "nl" ? "nl-NL" : "en-GB", { day: "numeric", month: "short", year: "numeric" })
      : tr("not yet");
  const refresh = () => qc.invalidateQueries({ queryKey: ["agent-connections"] });

  async function run(key: string, work: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await work();
    } catch {
      setError(tr("That did not work. Try again."));
    } finally {
      setBusy(null);
    }
  }

  // Signing in with your TrackerAI account: what to do in each assistant.
  function signInSteps(a: Assistant): ReactNode {
    switch (a) {
      case "claude":
        return (
          <Steps
            intro={
              <>
                {tr(
                  "In Claude, Settings, Connectors, “Add custom connector”. Name: {0}. Paste the server URL and leave the OAuth fields empty. Choose Connect: TrackerAI opens, you sign in and approve. Once per account: it then works in the Claude app, on claude.ai and in Claude Code logged in with that account.",
                  site,
                )}{" "}
                {link("https://claude.ai/settings/connectors", "claude.ai/settings/connectors")}
              </>
            }
            snippets={[
              { label: tr("Server URL"), value: server },
              {
                label: tr("Claude Code with an API key instead of a claude.ai login: once in a terminal, then /mcp to sign in"),
                value: `claude mcp add --transport http --scope user ${site} ${server}`,
              },
            ]}
          />
        );
      case "openai":
        return (
          <div className="flex flex-col gap-3">
            {o?.plugin_url && (
              <div>
                <a className="ds-btn ds-btn--primary ds-btn--md" href={o.plugin_url} target="_blank" rel="noreferrer">
                  {tr("Connect ChatGPT / Codex")}
                </a>
              </div>
            )}
            <Steps
              intro={tr(
                "In ChatGPT on the web: Settings, Apps & Connectors, Advanced, switch on Developer mode. Then create a connector named {0} with the server URL and authentication OAuth. In Codex, run the two commands. Both open TrackerAI to sign in and approve.",
                site,
              )}
              snippets={[
                { label: tr("Server URL"), value: server },
                { label: tr("Codex, once in a terminal"), value: `codex mcp add ${site} --url ${server}\ncodex mcp login ${site}` },
              ]}
            />
          </div>
        );
      case "gemini":
        return (
          <div className="flex flex-col gap-3">
            <p className="max-w-prose text-[13px] leading-relaxed text-ink-muted">
              {tr(
                "Gemini in a work account (Google Workspace, Gemini Enterprise) connects to a custom MCP server with a client ID and secret. Make them here, for {0} and your account only, and fill them in where Gemini asks for a custom MCP server with OAuth 2.0. The personal Gemini app cannot add your own servers yet: use Gemini CLI.",
                trackerName,
              )}
            </p>
            {madeClient ? (
              <div className="flex flex-col gap-3 rounded border border-border p-3">
                <p className="text-[13px] font-medium">{tr("Client “{0}”: the secret is visible only now", madeClient.name)}</p>
                <Copy label={tr("Server URL")} value={madeClient.server_url} />
                <Copy label={tr("Authorization URL")} value={madeClient.authorization_url} />
                <Copy label={tr("Token URL")} value={madeClient.token_url} />
                <Copy label={tr("Client ID")} value={madeClient.client_id} />
                <Copy label={tr("Client secret")} value={madeClient.client_secret} />
                <Copy label={tr("Scopes")} value={madeClient.scopes} />
                <p className="max-w-prose text-[12.5px] text-ink-muted">
                  {tr(
                    "Leave the extra authorization parameters empty; PKCE may be on or off. Gemini sends you back to {0}. When you connect, TrackerAI asks you to sign in and approve, read-only unless you also allow editing.",
                    madeClient.redirect_uri,
                  )}
                </p>
                <div>
                  <Button size="sm" variant="ghost" onClick={() => setMadeClient(null)}>
                    {tr("Done")}
                  </Button>
                </div>
              </div>
            ) : (
              <div>
                <Button
                  variant="primary"
                  disabled={busy === "client"}
                  onClick={() =>
                    run("client", async () => {
                      setMadeClient(await api.post<MadeClient>("/api/account/agent-clients", { app, name: "Gemini" }));
                      await refresh();
                    })
                  }
                >
                  {busy === "client" ? tr("Working…") : tr("Make a client ID and secret")}
                </Button>
              </div>
            )}
          </div>
        );
      case "gemini-cli":
        return (
          <Steps
            intro={tr(
              "Once in a terminal; then in Gemini CLI run /mcp auth {0}. TrackerAI opens in your browser to sign in and approve.",
              site,
            )}
            snippets={[{ label: tr("Terminal"), value: `gemini mcp add --transport http --scope user ${site} ${server}` }]}
          />
        );
      case "copilot":
        return (
          <Steps
            intro={tr(
              "In VS Code: Command Palette, “MCP: Open User Configuration”, and add this server (inside the existing “servers”, if there is one). VS Code asks you to sign in with TrackerAI the first time. The Copilot CLI needs a token: Advanced setup.",
            )}
            snippets={[
              { label: "VS Code: mcp.json", value: JSON.stringify({ servers: { [site]: { type: "http", url: server } } }, null, 2) },
            ]}
          />
        );
      case "other":
        return (
          <Steps
            intro={tr(
              "Give the client the server URL (MCP over streamable HTTP). A client that can sign in to MCP servers (OAuth) opens TrackerAI to approve. One that cannot needs a token: Advanced setup.",
            )}
            snippets={[{ label: tr("Server URL"), value: server }]}
          />
        );
    }
  }

  // With a token instead: what to put where. Every client gets the same server, the token as a Bearer header, or in
  // the URL for a client that only takes a URL.
  function tokenSteps(a: Assistant, token: string): { intro: ReactNode; snippets: Snippet[] } {
    const url = `${origin}/api/mcp`;
    const urlToken = `${url}/${token}`;
    const bearer = `Bearer ${token}`;
    switch (a) {
      case "claude":
        return {
          intro: tr(
            "In Claude, “Add custom connector”, name {0}, with this URL (the token is in it); or in Claude Code, once in a terminal.",
            site,
          ),
          snippets: [
            { label: tr("Connector URL"), value: urlToken },
            {
              label: "Claude Code",
              value: `claude mcp add --transport http --scope user ${site} ${url} --header "Authorization: ${bearer}"`,
            },
          ],
        };
      case "openai":
        return {
          intro: tr(
            "In ChatGPT (Developer mode), a connector named {0} with this URL and authentication “No authentication” (the token is in the URL); for Codex, add this to ~/.codex/config.toml.",
            site,
          ),
          snippets: [
            { label: tr("Connector URL"), value: urlToken },
            { label: "config.toml", value: `[mcp_servers.${site}]\nurl = "${url}"\nhttp_headers = { "Authorization" = "${bearer}" }` },
          ],
        };
      case "gemini":
      case "gemini-cli":
        return {
          intro: tr("Gemini CLI, once in a terminal. Gemini in a work account signs in instead: see above."),
          snippets: [
            {
              label: tr("Terminal"),
              value: `gemini mcp add --transport http --scope user ${site} ${url} --header "Authorization: ${bearer}"`,
            },
          ],
        };
      case "copilot":
        return {
          intro: tr("VS Code: in mcp.json. Copilot CLI: once in a terminal."),
          snippets: [
            {
              label: "VS Code: mcp.json",
              value: JSON.stringify({ servers: { [site]: { type: "http", url, headers: { Authorization: bearer } } } }, null, 2),
            },
            { label: "Copilot CLI", value: `copilot mcp add --transport http ${site} ${urlToken}` },
          ],
        };
      case "other":
        return {
          intro: tr("The URL and the header, or, for a client that only takes a URL, the URL with the token in it."),
          snippets: [
            { label: "URL", value: url },
            { label: "Header", value: `Authorization: ${bearer}` },
            { label: tr("URL with the token in it"), value: urlToken },
          ],
        };
    }
  }

  const name = typed ?? (assistant === "other" ? tr("AI assistant") : labels[assistant].split(" (")[0]);
  const connections = o?.connections ?? [];
  const owned = o?.clients ?? [];
  const tokenList = tokens.data?.tokens ?? [];

  const advanced = (
    <div className="flex flex-col gap-4">
      <Card title={tr("New token")}>
        <form
          className="flex max-w-md flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            run("token", async () => {
              const t = await api.post<MadeToken>("/api/agent-tokens", {
                name: name.trim(),
                scope,
                expires_days: expires === "never" ? null : Number(expires),
              });
              setMadeToken(t);
              await qc.invalidateQueries({ queryKey: ["agent-tokens"] });
            });
          }}
        >
          <Input label={tr("Name")} value={name} onChange={(e) => setTyped(e.target.value)} maxLength={60} />
          <Select
            label={tr("What may it do?")}
            hint={levels[scope]}
            value={scope}
            onChange={(e) => setScope(e.target.value as Token["scope"])}
          >
            <option value="read">{tr("Read")}</option>
            <option value="write">{tr("Read and write")}</option>
          </Select>
          <Select
            label={tr("Valid for")}
            hint={tr("After that the token stops working and you make a new one. You can revoke it earlier at any time.")}
            value={expires}
            onChange={(e) => setExpires(e.target.value)}
          >
            <option value="30">{tr("30 days")}</option>
            <option value="90">{tr("90 days")}</option>
            <option value="365">{tr("1 year")}</option>
            <option value="never">{tr("No end date")}</option>
          </Select>
          <div>
            <Button type="submit" variant="primary" disabled={busy === "token" || !name.trim()}>
              {busy === "token" ? tr("Working…") : tr("Create token")}
            </Button>
          </div>
        </form>
      </Card>
      {madeToken && (
        <Card
          title={tr("Token “{0}”: visible only now", madeToken.name)}
          action={
            <Button size="sm" variant="ghost" onClick={() => setMadeToken(null)}>
              {tr("Done")}
            </Button>
          }
        >
          <div className="flex flex-col gap-4">
            <p className="text-[13px] text-ink-muted">
              {tr(
                "Keep it like a password. Whoever has it can {0}.",
                madeToken.scope === "read" ? tr("read your data") : tr("read and update your data"),
              )}
            </p>
            <Steps {...tokenSteps(assistant, madeToken.token)} />
            <Copy label={tr("Token (for scripts: Authorization: Bearer …)")} value={madeToken.token} />
            {tokenExtra?.(madeToken.token, origin)}
          </div>
        </Card>
      )}
      <Card title={tr("Tokens")}>
        {tokens.isPending ? (
          <p className="text-[13px] text-ink-muted">{tr("Loading…")}</p>
        ) : !tokenList.length ? (
          <p className="text-[13px] text-ink-muted">{tr("No tokens yet.")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {tokenList.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-[13px]">
                <span>
                  <strong className="font-medium">{t.name}</strong>
                  <span className="text-ink-muted">
                    {" · "}
                    {t.scope === "read" ? tr("Read") : tr("Read and write")}
                    {" · "}
                    {tr("created {0}", day(t.created_at))}
                    {t.last_used !== undefined && <> · {tr("last used {0}", day(t.last_used))}</>}
                    {" · "}
                    {t.expired ? tr("expired") : t.expires_at ? tr("valid until {0}", day(t.expires_at)) : tr("no end date")}
                  </span>
                </span>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={busy === t.id}
                  onClick={() => {
                    if (!window.confirm(tr("Revoke {0}? Whoever uses it loses access.", t.name))) return;
                    run(t.id, async () => {
                      await api.del(`/api/agent-tokens/${encodeURIComponent(t.id)}`);
                      await qc.invalidateQueries({ queryKey: ["agent-tokens"] });
                    });
                  }}
                >
                  {tr("Revoke")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );

  return (
    <div className="flex max-w-[760px] flex-col gap-4">
      <Card title={title}>
        <p className="mb-4 max-w-prose text-[13px] leading-relaxed text-ink-muted">{intro}</p>
        <Select label={tr("Assistant")} value={assistant} onChange={(e) => setAssistant(e.target.value as Assistant)} className="max-w-sm">
          {ASSISTANTS.map((a) => (
            <option key={a} value={a}>
              {labels[a]}
            </option>
          ))}
        </Select>
      </Card>

      {options.isPending ? null : signIn ? (
        <Card title={tr("Sign in with your TrackerAI account")}>
          <div className="flex flex-col gap-4">
            <p className="max-w-prose text-[13px] leading-relaxed text-ink-muted">
              {tr(
                "No token to copy: the assistant opens TrackerAI, you sign in and choose what it may do with {0}, read-only unless you also allow editing. It never gets the other tracker, your password, bank connections or admin tools.",
                trackerName,
              )}
            </p>
            {signInSteps(assistant)}
          </div>
        </Card>
      ) : (
        <Card>
          <p className="text-[13px] text-ink-muted">
            {tr("Signing in with your account is not available on this installation. Use a token: Advanced setup.")}
          </p>
        </Card>
      )}

      <Card title={tr("Connected")}>
        {!connections.length && !owned.length ? (
          <p className="text-[13px] text-ink-muted">{tr("No connected assistants yet.")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {connections.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-[13px]">
                <span>
                  <strong className="font-medium">{c.name}</strong>
                  <span className="text-ink-muted">
                    {" · "}
                    {c.app === "health" ? tr("Health") : tr("Wealth")} · {c.scope === "read" ? tr("Read-only") : tr("Read and edit")}
                    {!c.last_used_at && <> · {tr("not used yet")}</>}
                  </span>
                </span>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={busy === c.id}
                  onClick={() => {
                    if (!window.confirm(tr("Disconnect {0}? It will lose access to this tracker.", c.name))) return;
                    run(c.id, async () => {
                      await api.del(`/api/account/agent-connections/${encodeURIComponent(c.id)}`);
                      await refresh();
                    });
                  }}
                >
                  {tr("Disconnect")}
                </Button>
              </li>
            ))}
            {owned.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-[13px]">
                <span>
                  <strong className="font-medium">{c.name}</strong>
                  <span className="text-ink-muted">
                    {" · "}
                    {c.app === "health" ? tr("Health") : tr("Wealth")} · {tr("client ID, made {0}", day(c.created_at))}
                  </span>
                </span>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={busy === c.id}
                  onClick={() => {
                    if (!window.confirm(tr("Remove {0}? Its secret stops working and its connections end.", c.name))) return;
                    run(c.id, async () => {
                      await api.del(`/api/account/agent-clients/${encodeURIComponent(c.id)}`);
                      await refresh();
                    });
                  }}
                >
                  {tr("Remove")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {error && (
        <p role="alert" className="text-[13px] text-loss">
          {error}
        </p>
      )}

      {signIn ? (
        <details className="flex flex-col gap-4">
          <summary className="cursor-pointer py-2 text-sm font-medium">{tr("Advanced setup: tokens")}</summary>
          {advanced}
        </details>
      ) : (
        advanced
      )}
    </div>
  );
}
